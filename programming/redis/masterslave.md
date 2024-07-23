> 基于`redis`源码分支`5.0`
# 主从复制
主从复制主要解决以下问题：
+ 读写分离：可以部署一台主节点，多台从节点，主节点负责写请求，从节点负责读请求，减轻主节点压力。从节点通过复制功能同步主节点数据。
也可以关闭主节点持久化操作，让从节点执行持久化操作。
+ 数据备份：从节点通过复制功能同步主节点数据，一旦主节点宕机，可以将请求切换到从节点，避免`redis`服务中断。

主从复制能力主要分为以下四个阶段：
+ 初始化；
+ 主从节点建立连接；
+ 主从节点握手；
+ 复制类型判断与执行；

每一个`redis`实例都对应一个`redisServer`结构体对象，里面保存了服务实例各种信息配置。下面部分变量是`redisServer`结构体中和从库复制相关的：
```c
struct redisServer {
    ...
    /* Replication (slave) */
    char *masterauth;               /* AUTH with this password with master */
    char *masterhost;               /* Hostname of master */
    int masterport;                 /* Port of master */
    ...
    client *master;     /* Client that is master for this slave */
    client *cached_master; /* Cached master to be reused for PSYNC. */
    ...
    int repl_state;          /* Replication status if the instance is a slave */
    ...
} 
```
`redis`的主从复制是基于**状态机**实现，`redisServer`结构体中的`repl_state`表示复制过程中的各个状态。
基于状态机实现主从复制的好处就是只需要考虑清楚在不同状态下具体要执行的操作，以及状态之间的跳转条件。

## 初始化
将一个`redis`实例设置为从节点有三种方式实现：
+ 通过一个客户端给准备作为从节点的实例发送`replicaof <masterip> <masterport>`命令，其中`<masterip>`为主节点的地址，`<masterport>`为主节点的端口。
  ```bash
  // 启动两个`redis`实例，其中`my-redis`容器是主节点，`my-redis-6380`容器是从节点
  $ sudo docker run --rm -itd --name my-redis --network redis redis
  $ sudo docker run --rm -itd --name my-redis-6380 --network redis redis --port 6380
  ```
  下面打开一个客户端连接从节点`my-redis-6380`，并执行`replicaof my-redis 6379`同步复制主节点数据：
  ```bash
  $ sudo docker run --network redis --rm -it redis redis-cli -h my-redis-6380 -p 6380
  my-redis-6380:6380> REPLICAOF my-redis 6379
  OK
  ```
  连接主节点`my-redis`，添加一个键值对：
  ```bash
  $ sudo docker run --network redis --rm -it redis redis-cli -h my-redis
  my-redis:6379> get key
  (nil)
  my-redis:6379> set key "hello, i am 6379"
  OK
  my-redis:6379> get key
  "hello, i am 6379"
  ```
  此时查看从节点`my-redis-6380`，发现复制了主节点添加的数据：
  ```bash
  $ sudo docker run --network redis --rm -it redis redis-cli -h my-redis-6380 -p 6380
  my-redis-6380:6380> 
  my-redis-6380:6380> REPLICAOF my-redis 6379
  OK
  my-redis-6380:6380> get key
  (nil)
  my-redis-6380:6380> get key
  "hello, i am 6379"
  ```
+ 准备作为从节点实例的配置文件设置`replicaof <masterip> <masterport>`参数。
+ 准备作为从节点实例运行的时候指定`–replicaof <masterip> <masterport>`参数。

在服务启动初始化阶段，`initServerConfig`函数中会将从库复制状态进行初始化为`REPL_STATE_NONE`：
```c
void initServerConfig(void) {
    ...
    server.repl_state = REPL_STATE_NONE;
    ...
}
```
当服务实例收到`replicaof <masterhost> <masterport>`命令后，`replicaofCommand`函数会被调用：
```c
void replicaofCommand(client *c) {
    ...
    // 检查是否已记录主库信息，如果已经记录了，那么直接返回连接已建立的消息
    if (server.masterhost && !strcasecmp(server.masterhost,c->argv[1]->ptr)
        && server.masterport == port) {
        serverLog(LL_NOTICE,"REPLICAOF would result into synchronization with the master we are already connected with. No operation performed.");
        addReplySds(c,sdsnew("+OK Already connected to specified master\r\n"));
        return;
    }
    // 如果没有记录主库的IP和端口号，设置主库的信息
    replicationSetMaster(c->argv[1]->ptr, port);
    ...
}
```
`replicaofCommand`函数如果判断指定的主库信息（`ip + port`）没有记录，则调用`replicationSetMaster`函数进行设置：
```c
void replicationSetMaster(char *ip, int port) {
    int was_master = server.masterhost == NULL;

    sdsfree(server.masterhost);
    // 记录主节点 ip
    server.masterhost = sdsnew(ip);
    // 记录主节点 port
    server.masterport = port;
    if (server.master) {
        freeClient(server.master);
    }
    disconnectAllBlockedClients(); /* Clients blocked in master, now slave. */

    disconnectSlaves();
    cancelReplicationHandshake();
    if (was_master) {
        replicationDiscardCachedMaster();
        replicationCacheMasterUsingMyself();
    }
    // 状态机的状态更新为 REPL_STATE_CONNECT
    server.repl_state = REPL_STATE_CONNECT;
}
```
初始化阶段完成后，从库实例状态更新为`REPL_STATE_CONNECT`。

## 主从节点建立连接
初始化完成后，从库的状态变为`REPL_STATE_CONNECT`，接下来就需要从库和主库建立`TCP`连接，并且会在建立好的网络连接上，监听是否有主库发送的命令。

连接的建立是在`redis`的定时任务`serverCron`函数中执行：
```c
int serverCron(struct aeEventLoop *eventLoop, long long id, void *clientData) {
    ...
    // 1s 执行一次
    run_with_period(1000) replicationCron();
    ...
}
```
`replicationCron`函数中有一段逻辑就是检查从库的复制状态`repl_state`，如果状态是`REPL_STATE_CONNECT`就会执行和主库建立连接：
```c
void replicationCron(void) {
    ...
    /* Check if we should connect to a MASTER */
    if (server.repl_state == REPL_STATE_CONNECT) {
        serverLog(LL_NOTICE,"Connecting to MASTER %s:%d",
            server.masterhost, server.masterport);
        // 和主库建立连接
        if (connectWithMaster() == C_OK) {
            serverLog(LL_NOTICE,"MASTER <-> REPLICA sync started");
        }
    }
    ...
}
```
和主库建立连接是通过`connectWithMaster`函数实现：
```c
int connectWithMaster(void) {
    int fd;
    // 和主节点建立 tcp 连接，返回通信的客户端 socket 文件描述符
    fd = anetTcpNonBlockBestEffortBindConnect(NULL,
        server.masterhost,server.masterport,NET_FIRST_BIND_ADDR);
    if (fd == -1) {
        serverLog(LL_WARNING,"Unable to connect to MASTER: %s",
            strerror(errno));
        return C_ERR;
    }
    // 在通信的客户端 socket 上注册事件处理函数 syncWithMaster
    if (aeCreateFileEvent(server.el,fd,AE_READABLE|AE_WRITABLE,syncWithMaster,NULL) ==
            AE_ERR)
    {
        close(fd);
        serverLog(LL_WARNING,"Can't create readable event for SYNC");
        return C_ERR;
    }

    server.repl_transfer_lastio = server.unixtime;
    server.repl_transfer_s = fd;
    // 更新从库的复制状态为 REPL_STATE_CONNECTING
    server.repl_state = REPL_STATE_CONNECTING;
    return C_OK;
}
```
和主库的`TCP`连接建立完成后，从库的复制状态更新为`REPL_STATE_CONNECTING`

## 主从节点握手
和主库的网络连接建立完成后，从库开始和主库进行握手。握手过程就是主从库间相互发送`ping-pong`消息，同时从库根据配置信息向主库进行验证。
最后，从库把自己的`IP`、端口号等信息发给主库。

因为在和主库建立网络连接的过程中注册的网络事件是可读可写：
```c
aeCreateFileEvent(server.el,fd,AE_READABLE|AE_WRITABLE,syncWithMaster,NULL)
```
所以，开始阶段`socket`发送缓存区为空，可写事件触发，所以事件处理函数`syncWithMaster`会立刻执行。由于此时从库的复制状态为`REPL_STATE_CONNECTING`，
则从库会发送`PING`消息给主库，同时将从库复制状态设置为`REPL_STATE_RECEIVE_PONG`以等待主库回复`PONG`：
```c
void syncWithMaster(aeEventLoop *el, int fd, void *privdata, int mask) {
    ...
    if (server.repl_state == REPL_STATE_CONNECTING) {
        serverLog(LL_NOTICE,"Non blocking connect for SYNC fired the event.");
        // 删除写事件注册，保留读事件以接收主库回复 PONG，不删除的话，从库会一直发 PING
        aeDeleteFileEvent(server.el,fd,AE_WRITABLE);
        // 更新从库复制状态为 REPL_STATE_RECEIVE_PONG
        server.repl_state = REPL_STATE_RECEIVE_PONG;
        // 给主库发送 PING 消息，等待主库回 PONG 消息
        err = sendSynchronousCommand(SYNC_CMD_WRITE,fd,"PING",NULL);
        if (err) goto write_error;
        // 返回
        return;
    }
    ...
}
```
当主库回复`PONG`时，`socket`变为可读，则`syncWithMaster`会再次被调用，此时从库的复制状态为`REPL_STATE_RECEIVE_PONG`：
```c
void syncWithMaster(aeEventLoop *el, int fd, void *privdata, int mask) {
    ...
    /* Receive the PONG command. */
    if (server.repl_state == REPL_STATE_RECEIVE_PONG) {
        // 返回值 err 就是读到的回复内容
        err = sendSynchronousCommand(SYNC_CMD_READ,fd,NULL);

        // "+PONG" 和验证错误回复是有效的
        if (err[0] != '+' &&
            strncmp(err,"-NOAUTH",7) != 0 &&
            strncmp(err,"-ERR operation not permitted",28) != 0)
        {
            serverLog(LL_WARNING,"Error reply to PING from master: '%s'",err);
            sdsfree(err);
            goto error;
        } else {
            serverLog(LL_NOTICE,
                "Master replied to PING, replication can continue...");
        }
        sdsfree(err);
        // 收到主节点回复的 PONG 消息后，更新从库复制状态为 REPL_STATE_SEND_AUTH
        server.repl_state = REPL_STATE_SEND_AUTH;
    }
    ...
}
```
成功收到主节点回复的消息，从库的复制状态被更新为`REPL_STATE_SEND_AUTH`。此时`syncWithMaster`函数并未返回，接着往下执行：
```c
void syncWithMaster(aeEventLoop *el, int fd, void *privdata, int mask) {
    ...
    /* AUTH with the master if required. */
    if (server.repl_state == REPL_STATE_SEND_AUTH) {
        // 用户配置了 `masterauth <master-password>`
        if (server.masterauth) {
            err = sendSynchronousCommand(SYNC_CMD_WRITE,fd,"AUTH",server.masterauth,NULL);
            if (err) goto write_error;
            // 更新状态接收 REPL_STATE_RECEIVE_AUTH
            server.repl_state = REPL_STATE_RECEIVE_AUTH;
            return;
        } else {
            // 不需要验证主节点，更新状态 REPL_STATE_SEND_PORT
            server.repl_state = REPL_STATE_SEND_PORT;
        }
    }
    ...
}
```
如果用户配置了`masterauth <master-password>`，则向主节点发送`AUTH <password>`命令进行验证。接下里从节点继续发送自身的`port`、`ip`及`eof`和`psync2`等能力。
+ `eof`：表示`slave`支持直接接收从`socket`发送过来的`RDB`数据流，也就是无盘加载，适合磁盘读写速度慢但网络带宽非常高的环境；
+ `psync2`：表示`slave`支持`redis 4.0`引入的部分重同步`v2`版本；

最终主从节点握手完成后，从节点复制状态变为`REPL_STATE_RECEIVE_CAPA`。

## 复制类型判断与执行
握手阶段完成后，从库会等待主库回复`CAPA`消息，此时从库的复制状态为`REPL_STATE_RECEIVE_CAPA`，当收到主库回复的`CAPA`消息后：
```c
void syncWithMaster(aeEventLoop *el, int fd, void *privdata, int mask) {
    ...
    /* Receive CAPA reply. */
    if (server.repl_state == REPL_STATE_RECEIVE_CAPA) {
        err = sendSynchronousCommand(SYNC_CMD_READ,fd,NULL);
        ...
        server.repl_state = REPL_STATE_SEND_PSYNC;
    }
    // 向主库发送 PSYNC 命令
    if (server.repl_state == REPL_STATE_SEND_PSYNC) {
        if (slaveTryPartialResynchronization(fd,0) == PSYNC_WRITE_ERROR) {
            err = sdsnew("Write error sending the PSYNC command.");
            goto write_error;
        }
        server.repl_state = REPL_STATE_RECEIVE_PSYNC;
        return;
    }
    ...
}
```
首先将从库复制状态设置为`REPL_STATE_SEND_PSYNC`，表示开始往主库发送`PSYNC`命令，开始实际的数据同步。接着`syncWithMaster`函数继续往下执行，
调用`slaveTryPartialResynchronization`函数向主库发送`PSYNC`命令。

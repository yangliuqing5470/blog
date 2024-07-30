> 基于`redis`源码分支`5.0`

主从复制主要解决以下问题：
+ 读写分离：可以部署一台主节点，多台从节点，主节点负责写请求，从节点负责读请求，减轻主节点压力。从节点通过复制功能同步主节点数据。
也可以关闭主节点持久化操作，让从节点执行持久化操作。
+ 数据备份：从节点通过复制功能同步主节点数据，一旦主节点宕机，可以将请求切换到从节点，避免`redis`服务中断。

# 主从复制实现
## 从节点

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

### 初始化
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

### 主从节点建立连接
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

### 主从节点握手
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

### 复制类型判断与执行
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
调用`slaveTryPartialResynchronization`函数向主库发送`PSYNC`命令，最后将从库复制状态设置为`REPL_STATE_RECEIVE_PSYNC`。

从库调用的`slaveTryPartialResynchronization`函数，负责向主库发送数据同步的命令。主库收到命令后，会根据从库发送的主库`ID`、
复制进度值`offset`，来判断是进行全量复制还是增量复制，或者是返回错误。`slaveTryPartialResynchronization`函数代码如下：
```c
int slaveTryPartialResynchronization(int fd, int read_reply) {
    ...
    // 给主库发送 PSYNC 命令
    if (!read_reply) {
        server.master_initial_offset = -1;
        ...
        // 调用 sendSynchronousCommand 发送 PSYNC 命令
        reply = sendSynchronousCommand(SYNC_CMD_WRITE,fd,"PSYNC",psync_replid,psync_offset,NULL);
        ...
        // 发送命令后，等待主库响应
        return PSYNC_WAIT_REPLY;
    }

    // 读主库的响应
    reply = sendSynchronousCommand(SYNC_CMD_READ,fd,NULL);
    ...
    // 取消读事件，因为此函数还是在事件处理函数 syncWithMaster 上下文中调用，不需要监听读事件，
    // 如果遇到错误，也可以确保 socket 上注册的事件都移除
    aeDeleteFileEvent(server.el,fd,AE_READABLE);

    // 主库返回 FULLRESYNC，全量复制
    if (!strncmp(reply,"+FULLRESYNC",11)) {
        ...
        return PSYNC_FULLRESYNC;
    }
    // 主库返回 CONTINUE，执行增量复制，增量复制就和普通的客户端命令请求差不多，
    // 依次请求从节点需要“复制”的每一个命令
    if (!strncmp(reply,"+CONTINUE",9)) {
        ...
        return PSYNC_CONTINUE;
    }

    // 主库返回 NOMASTERLINK 或者 LOADING 表示应该稍后重试同步
    if (!strncmp(reply,"-NOMASTERLINK",13) ||
        !strncmp(reply,"-LOADING",8))
    {
        ...
        return PSYNC_TRY_LATER;
    }
    // 主库返回 ERR
    if (strncmp(reply,"-ERR",4)) {
        /* If it's not an error, log the unexpected event. */
        serverLog(LL_WARNING,
            "Unexpected reply to PSYNC from master: %s", reply);
    } else {
        serverLog(LL_NOTICE,
            "Master does not support PSYNC or is in "
            "error state (reply: %s)", reply);
    }
    sdsfree(reply);
    replicationDiscardCachedMaster();
    return PSYNC_NOT_SUPPORTED;
}
```
因为`slaveTryPartialResynchronization`是在`syncWithMaster`函数中调用，当该函数返回`PSYNC`命令不同的结果时，
`syncWithMaster`函数就会根据结果值执行不同处理。
```c
void syncWithMaster(aeEventLoop *el, int fd, void *privdata, int mask) {
    ...
    // 读取主库回复的 PSYNC 命令结果
    psync_result = slaveTryPartialResynchronization(fd,1);
    // 主库还没有回复 PSYNC 命令，函数执行完成（此时读事件还在监听，没有取消）
    if (psync_result == PSYNC_WAIT_REPLY) return; /* Try again later... */
    // 主库执行 PSYNC 命令遇到错误，直接回复初始状态，从头开始尝试，此时从库复制状态是 REPL_STATE_CONNECT
    if (psync_result == PSYNC_TRY_LATER) goto error;
    // 走到这里，读事件在 slaveTryPartialResynchronization 函数中已经被移除了
    // 增量复制，直接返回，后续执行增量复制（slaveTryPartialResynchronization 
    // 内部会修改从节点复制状态为 REPL_STATE_CONNECTED）
    if (psync_result == PSYNC_CONTINUE) {
        serverLog(LL_NOTICE, "MASTER <-> REPLICA sync: Master accepted a Partial Resynchronization.");
        return;
    }

    ...
    // 全量同步，注册读事件，事件处理函数是 readSyncBulkPayload
    if (aeCreateFileEvent(server.el,fd, AE_READABLE,readSyncBulkPayload,NULL)
            == AE_ERR)
    {
        serverLog(LL_WARNING,
            "Can't create readable event for SYNC: %s (fd=%d)",
            strerror(errno),fd);
        goto error;
    }
    // 更新从节点复制状态为 REPL_STATE_TRANSFER
    server.repl_state = REPL_STATE_TRANSFER;
    server.repl_transfer_size = -1;
    server.repl_transfer_read = 0;
    server.repl_transfer_last_fsync_off = 0;
    server.repl_transfer_fd = dfd;
    server.repl_transfer_lastio = server.unixtime;
    server.repl_transfer_tmpfile = zstrdup(tmpfile);
    return;
    ...
}
```
如果返回的是`PSYNC_CONTINUE`，表明可以执行部分重同步（函数`slaveTryPartialResynchronization`内部会修改状态为`REPL_STATE_CONNECTED`）。
否则说明需要执行完整重同步，从服务器需要准备接收主服务器发送的`RDB`文件，进而创建文件读事件，处理函数为`readSyncBulkPayload`，
并修改状态为`REPL_STATE_TRANSFER`。

函数`readSyncBulkPayload`实现了`RDB`文件的接收与加载，加载完成后同时会修改状态为`REPL_STATE_CONNECTED`。
当从服务器状态成为`REPL_STATE_CONNECTED`时，表明从服务器已经成功与主服务器建立连接，从服务器只需要接收并执行主服务器同步过来的命令请求即可。

## 主节点
从节点和主节点建立连接后，从节点会通过`replconf`命令往主节点同步信息，主节点执行`replconf`命令：
```c
void replconfCommand(client *c) {
    ...
    /* Process every option-value pair. */
    for (j = 1; j < c->argc; j+=2) {
        if (!strcasecmp(c->argv[j]->ptr,"listening-port")) {
            long port;

            if ((getLongFromObjectOrReply(c,c->argv[j+1],
                    &port,NULL) != C_OK))
                return;
            c->slave_listening_port = port;
        } else if (!strcasecmp(c->argv[j]->ptr,"ip-address")) {
            sds ip = c->argv[j+1]->ptr;
            if (sdslen(ip) < sizeof(c->slave_ip)) {
                memcpy(c->slave_ip,ip,sdslen(ip)+1);
            } else {
                addReplyErrorFormat(c,"REPLCONF ip-address provided by "
                    "replica instance is too long: %zd bytes", sdslen(ip));
                return;
            }
        } else if (!strcasecmp(c->argv[j]->ptr,"capa")) {
            /* Ignore capabilities not understood by this master. */
            if (!strcasecmp(c->argv[j+1]->ptr,"eof"))
                c->slave_capa |= SLAVE_CAPA_EOF;
            else if (!strcasecmp(c->argv[j+1]->ptr,"psync2"))
                c->slave_capa |= SLAVE_CAPA_PSYNC2;
        }
    ...
    }
    addReply(c,shared.ok);
}
```
`replconfCommand`函数主要解析客户端（从节点）请求参数并存储在客户端对象`client`中。主要解析如下信息：
+ 从节点的`IP`和端口，分别存储在客户端对象`c->slave_ip`和`c->slave_listening_port`中。
+ 当前从节点支持的能力，存储在客户端对象（从节点）的`c->slave_capa`中。
  + `eof`：主服务器可以直接将数据库中数据以`RDB`协议格式通过`socket`发送给从服务器，免去了本地磁盘文件不必要
的读写操作；
  + `psync2`：从服务器支持`psync2`协议，从服务器可以识别主服务器回复的`+CONTINUE <new_repl_id>`；
+ 从服务器的复制偏移量以及交互时间，存放在`c->repl_ack_off`和`repl_ack_time`中。
  ```c
  if ((getLongLongFromObject(c->argv[j+1], &offset) != C_OK))
      return;
  if (offset > c->repl_ack_off)
      c->repl_ack_off = offset;
  c->repl_ack_time = server.unixtime;
  ```

### 部分同步
下面主节点继续响应从节点发送的`psync`命令。先调用命令处理函数`syncCommand`，其中首先调用`masterTryPartialResynchronization`函数判断是否可以执行部分同步。
满足下面条件才可以进行部分同步：
+ 服务器的运行`ID`合法，复制偏移量合法。
  ```c
  int masterTryPartialResynchronization(client *c) {
      long long psync_offset, psync_len;
      char *master_replid = c->argv[1]->ptr;
      ...
      if (getLongLongFromObjectOrReply(c,c->argv[2],&psync_offset,NULL) != C_OK) goto need_full_resync;
      ...
      // 服务器运行 ID 和复制偏移量合法
      if (strcasecmp(master_replid, server.replid) &&
        (strcasecmp(master_replid, server.replid2) ||
         psync_offset > server.second_replid_offset))
      {
          ...
          goto need_full_resync;
      }
  }
  ```
+ 复制偏移量必须包含在复制缓冲区中。
  ```c
  int masterTryPartialResynchronization(client *c) {
      long long psync_offset, psync_len;
      char *master_replid = c->argv[1]->ptr;
      ...
      if (getLongLongFromObjectOrReply(c,c->argv[2],&psync_offset,NULL) != C_OK) goto need_full_resync;
      ...
      // 复制偏移量必须包含在复制缓冲区中
      if (!server.repl_backlog ||
          psync_offset < server.repl_backlog_off ||
          psync_offset > (server.repl_backlog_off + server.repl_backlog_histlen))
      {
            ...
            goto need_full_resync;
      }
  }
  ```
当部分同步条件满足时，在`masterTryPartialResynchronization`函数中将当前客户端（从节点）标记为`CLIENT_SLAVE`，状态设置为`SLAVE_STATE_ONLINE`，
并将客户端（从节点）添加到`server.slaves`链表中：
```c
int masterTryPartialResynchronization(client *c) {
    ...
    c->flags |= CLIENT_SLAVE;
    c->replstate = SLAVE_STATE_ONLINE;
    c->repl_ack_time = server.unixtime;
    c->repl_put_online_on_ack = 0;
    listAddNodeTail(server.slaves,c);
    ...
}
```
然后主节点根据从节点同步的能力是否有`psync2`决定返回`+CONTINUE`还是`+CONTINUE <replid>`：
```c
int masterTryPartialResynchronization(client *c) {
    ...
    if (c->slave_capa & SLAVE_CAPA_PSYNC2) {
        buflen = snprintf(buf,sizeof(buf),"+CONTINUE %s\r\n", server.replid);
    } else {
        buflen = snprintf(buf,sizeof(buf),"+CONTINUE\r\n");
    }
    if (write(c->fd,buf,buflen) != buflen) {
        freeClientAsync(c);
        return C_OK;
    }
    ...
}
```
接着主节点根据`psync`命令指定的复制偏移量，将复制缓存区中命令同步给从节点：
```c
int masterTryPartialResynchronization(client *c) {
    ...
    psync_len = addReplyReplicationBacklog(c,psync_offset);
    ...
}
```
最后主节点更新有效从节点数目，以实现`min_slaves`功能：
```c
void refreshGoodSlavesCount(void) {
    listIter li;
    listNode *ln;
    int good = 0;

    if (!server.repl_min_slaves_to_write ||
        !server.repl_min_slaves_max_lag) return;

    listRewind(server.slaves,&li);
    while((ln = listNext(&li))) {
        client *slave = ln->value;
        time_t lag = server.unixtime - slave->repl_ack_time;
        // 有效节点判断
        if (slave->replstate == SLAVE_STATE_ONLINE &&
            lag <= server.repl_min_slaves_max_lag) good++;
    }
    server.repl_good_slaves_count = good;
}
```

### 全量同步
当部分同步条件不满足时，`syncCommand`命令处理函数会执行全量同步逻辑。

首先，将当前客户端（从节点）标记为`CLIENT_SLAVE`，状态设置为`SLAVE_STATE_WAIT_BGSAVE_START`，
并将客户端（从节点）添加到`server.slaves`链表中：
```c
void syncCommand(client *c) {
    ...
    c->replstate = SLAVE_STATE_WAIT_BGSAVE_START;
    if (server.repl_disable_tcp_nodelay)
        anetDisableTcpNoDelay(NULL, c->fd); /* Non critical if it fails. */
    c->repldbfd = -1;
    c->flags |= CLIENT_SLAVE;
    listAddNodeTail(server.slaves,c);
    ...
}
```
然后在周期执行函数`replicationCron`周期执行函数或者当前`syncCommand`函数中调用`startBgsaveForReplication`函数执行实际的全量同步。

根据客户端同步的能力，全量同步有两种：
+ 将数据库进行`RDB`持久化，然后直接通过`socket`发送给从节点。
+ 持久化数据到本地文件（`RDB`持久化），待持久化完成后再将该文件发送给从节点。

```c
int startBgsaveForReplication(int mincapa) {
    ...
    int socket_target = server.repl_diskless_sync && (mincapa & SLAVE_CAPA_EOF);
    ...
    rsiptr = rdbPopulateSaveInfo(&rsi);
    if (rsiptr) {
        if (socket_target)
            // 直接通过 socket 发送
            retval = rdbSaveToSlavesSockets(rsiptr);
        else
            // 先保存本地文件，然后发送文件
            retval = rdbSaveBackground(server.rdb_filename,rsiptr);
    }
}
```
其中变量`server.repl_diskless_sync`可通过配置文件参数`repl-disklesssync`进行设置，默认为`0`。**持久化操作都是在子进行中进行**。

全量同步会回复从节点`+FULLRESYNC <replid> <offset>`，其中`<replid>`表示主节点的`RUN_ID`，`<offset>`表示主节点**开始**复制偏移量。

### 命令广播
主节点每次接收到写命令请求时，都会将该命令请求广播给所有从节点，同时记录在复制缓冲区中。通过`replicationFeedSlaves`函数实现。

函数`replicationFeedSlaves`逻辑主要有以下三步：
+ 当前客户端（从节点）连接的数据库可能并不是上次向从节点同步数据的数据库，因此可能需要先向从节点同步`select`命令修改数据库；
+ 将命令请求同步给所有从节点；
+ 将命令记录到缓存区；

## 部分同步原理
每台`redis`服务器都有一个运行`ID`，从节点每次发送`psync`请求同步数据时，会携带自己需要同步主节点的运行`ID`。
主节点接收到`psync`命令时，需要判断命令参数指定的`ID`与自己的运行`ID`是否相等，只有相等才有可能执行部分重同步。

部分同步需要满足以下两个条件：
+ `RUN_ID`必须一样；
+ 复制偏移量必须包含在复制缓冲区中；

实际生产中还会存在以下情况：
+ 从节点重启（复制信息丢失）；
+ 主节点故障导致主从切换（从多个从节点重新选举出一台机器作为主节点，主节点运行`ID`发生改变）；

针对上面发生的两种情况，从`redis4.0`开始提出优化`psync2`协议：
+ 针对从节点重启情况，持久化主从复制信息到`RDB`中（复制的主服务器`RUN_ID`与复制偏移量），等到节点重启加载`RDB`文件时，回复主从复制信息。
  ```c
  int rdbSaveInfoAuxFields(rio *rdb, int flags, rdbSaveInfo *rsi) {
      ...
      if (rsi) {
          if (rdbSaveAuxFieldStrInt(rdb,"repl-stream-db",rsi->repl_stream_db)
              == -1) return -1;
          if (rdbSaveAuxFieldStrStr(rdb,"repl-id",server.replid)
              == -1) return -1;
          if (rdbSaveAuxFieldStrInt(rdb,"repl-offset",server.master_repl_offset)
              == -1) return -1;
      }
      ...
  }
  ```
+ 针对主从切换情况，存储上一个主节点复制信息。从节点的`server->replid`存储是主节点的`RUN_ID`。在全量同步的时候，
从节点会更新`server->replid`和`server->master_repl_offset`：
  ```c
  void readSyncBulkPayload(aeEventLoop *el, int fd, void *privdata, int mask) {
      ...
      // 更新 server->master 属性
      replicationCreateMasterClient(server.repl_transfer_s,rsi.repl_stream_db);
      server.repl_state = REPL_STATE_CONNECTED;
      server.repl_down_since = 0;
      memcpy(server.replid,server.master->replid,sizeof(server.replid));
      server.master_repl_offset = server.master->reploff;
      clearReplicationId2();
      ...
  }
  ```
  当某个从节点变为主节点时候，`shiftReplicationId`函数会调用：
  ```c
  // 将老的主节点 RUN_ID 和复制偏移值保存在 replid2 和 second_replid_offset 中
  void shiftReplicationId(void) {
      memcpy(server.replid2,server.replid,sizeof(server.replid));
      server.second_replid_offset = server.master_repl_offset+1;
      changeReplicationId();
  }
  // 随机设置 server->replid 值
  void changeReplicationId(void) {
      getRandomHexChars(server.replid,CONFIG_RUN_ID_SIZE);
      server.replid[CONFIG_RUN_ID_SIZE] = '\0';
  }
  ```
  判断是否可执行部分同步比较主节点`RUN_ID`条件更新为：
  ```c
  if (strcasecmp(master_replid, server.replid) &&
    (strcasecmp(master_replid, server.replid2) ||
     psync_offset > server.second_replid_offset))
  {
      ...
      goto need_full_resync;
  }
  ```
# 主从复制流程
## 流程

+ 从库执行`replicaof <masterip> <masterport>`命令和主节点建立连接，包括建立`TCP`连接，信息同步等；
+ 从库发送`psync <master_runid> <offset>`命令请求同步，第一次从库不知道主库`RUN_ID`，会发送`psync ? -1`，
主库会回复`+FULLRESYNC <RUN_ID> <offset>`，然后**从库**会更新`master_replid`和`master_initial_offset`字段：
  ```c
  int slaveTryPartialResynchronization(int fd, int read_reply) {
      ...
      memcpy(server.master_replid, replid, offset-replid-1);
      server.master_replid[CONFIG_RUN_ID_SIZE] = '\0';
      server.master_initial_offset = strtoll(offset,NULL,10);
      ...
  }
  ```
+ 主库开始执行全量同步（第一次）。主库子进程执行`RDB`将数据库持久化，持久化完成后，主库将`RDB`发送给从库，从库加载`RDB`文件，完成数据同步。
在主库数据持久化和`RDB`发送期间，主库可以继续处理新的写命令，并将新的写命令存放到客户端（从库）回复缓存中；
  ```c
  void replicationFeedSlaves(list *slaves, int dictid, robj **argv, int argc) {
      ...
      /* Write the command to every slave. */
      listRewind(slaves,&li);
      while((ln = listNext(&li))) {
          client *slave = ln->value;

          if (slave->replstate == SLAVE_STATE_WAIT_BGSAVE_START) continue;
          // 将新的命令存放在客户端（从节点）回复缓存中
          addReplyMultiBulkLen(slave,argc);
          for (j = 0; j < argc; j++)
              addReplyBulk(slave,argv[j]);
      }
      ...
  }
  ```
  在子进程执行`RDB`持久化操作前，主节点就将从节点复制状态更新为`SLAVE_STATE_WAIT_BGSAVE_END`，所以主节点新的写命令都可以存放在客户端（从节点）回复缓存中。<br>
  时间事件循环`serverCron`函数中会检查后台的`RDB`保存或者`AOF`进程是否结束：
  ```c
  int serverCron(struct aeEventLoop *eventLoop, long long id, void *clientData) {
      ...
      if (server.rdb_child_pid != -1 || server.aof_child_pid != -1 ||
          ldbPendingChildren())
      {
          ...
          else if (pid == server.rdb_child_pid) {
              // RDB 子任务
              backgroundSaveDoneHandler(exitcode,bysignal);
              if (!bysignal && exitcode == 0) receiveChildInfo();
          } else if (pid == server.aof_child_pid) {
              // AOF 子任务
              backgroundRewriteDoneHandler(exitcode,bysignal);
              if (!bysignal && exitcode == 0) receiveChildInfo();
          }
          ...
      }
      ...
  }
  ```
  继续跟踪函数调用关系，主库在函数`updateSlaveWaitingBgsave`函数中会注册和从库通信`socket`的可写事件：
  ```c
  void updateSlavesWaitingBgsave(int bgsaveerr, int type) {
      ...
      // 删除旧的可写事件
      aeDeleteFileEvent(server.el,slave->fd,AE_WRITABLE);
      // 注册新的写事件，事件处理函数是 sendBulkToSlave
      if (aeCreateFileEvent(server.el, slave->fd, AE_WRITABLE, sendBulkToSlave, slave) == AE_ERR) {
          freeClient(slave);
          continue;
      }
  }
  ```
  写事件处理函数`sendBulkToSlave`会将`RDB`发送给从库。
+ 从库通过注册的`readSyncBulkPayload`写事件函数接收主库发送的`RDB`，从库接收完`RDB`文件后，会将`RDB`保存到本地磁盘，
然后清空自身老的数据库，加载接收的`RDB`文件到内存数据库。接着调用`replicationCreateMasterClient`创建一个和主库正常通信的客户端对象（接收常规的命令）：
  ```c
  void replicationCreateMasterClient(int fd, int dbid) {
      server.master = createClient(fd);
      ...
  }
  ```
  在`createClient`中会注册读事件函数`readQueryFromClient`用于接收命令。
+ 主库继续将客户端（从库）回复缓存中命令发送给从库。在上一步主库通过写事件处理函数`sendBulkToSlave`将`RDB`发送给从库后，
会调用`putSlaveOnline`函数将从库设置为在线：
  ```c
  void putSlaveOnline(client *slave) {
      // 更新当前从库状态为 SLAVE_STATE_ONLINE
      slave->replstate = SLAVE_STATE_ONLINE;
      slave->repl_put_online_on_ack = 0;
      slave->repl_ack_time = server.unixtime; /* Prevent false timeout. */
      // 注册一个写事件，将对应从库回复缓存中数据发送给从库
      if (aeCreateFileEvent(server.el, slave->fd, AE_WRITABLE,
          sendReplyToClient, slave) == AE_ERR) {
          serverLog(LL_WARNING,"Unable to register writable event for replica bulk transfer: %s", strerror(errno));
          freeClient(slave);
          return;
      }
      refreshGoodSlavesCount();
      serverLog(LL_NOTICE,"Synchronization with replica %s succeeded",
          replicationGetSlaveName(slave));
  }
  ```
  主库会通过`sendReplyToClient`写事件函数将对应从库（客户端）回复缓冲区中的命令发送给从库。
+ 后续新的写命令都会通过命令广播发送给从库；
  ```c
  void replicationFeedSlaves(list *slaves, int dictid, robj **argv, int argc) {
      ...
      /* Write the command to every slave. */
      listRewind(slaves,&li);
      while((ln = listNext(&li))) {
          client *slave = ln->value;

          if (slave->replstate == SLAVE_STATE_WAIT_BGSAVE_START) continue;
          // 将新的命令存放在客户端（从节点）回复缓存中
          addReplyMultiBulkLen(slave,argc);
          for (j = 0; j < argc; j++)
              addReplyBulk(slave,argv[j]);
      }
      ...
  }
  ```
## 样例
启动两个`redis`服务实例，其中`172.17.0.2:6379`是主库，`172.17.0.3:6380`是从库。启动一个客户端连接从库，并执行`REPLICAOF`命令和主库同步，
观察主库和从库日志。
### 主库日志
+ 从库给主库发送`psync`命令后，主库开始执行`syncCommand`函数处理，会打印如下日志：
  ```bash
  1:M 29 Jul 2024 07:34:26.118 * Replica 172.18.0.3:6380 asks for synchronization
  ```
+ 在`syncCommand`函数中首先调用`masterTryPartialResynchronization`函数，判断能否进行部分同步，判断条件不满足，输出如下日志：
  ```bash
  1:M 29 Jul 2024 07:34:26.118 * Partial resynchronization not accepted: Replication ID mismatch (Replica asked for '827139ed6e5f903a6b54573a34b125cb3471560f', my replication IDs are '4b9069ee4a91a5c997561525852e39903d8475b4' and '0000000000000000000000000000000000000000')
  ```
+ 在`syncCommand`函数中走全量同步逻辑，调用`startBgsaveForReplication`函数开始生成`RDB`，输出如下日志：
  ```bash
  1:M 29 Jul 2024 07:34:26.118 * Starting BGSAVE for SYNC with target: disk
  ```
+ 接着调用`rdbSaveBackground`函数的父进程更新相关状态信息，打印如下日志返回，子进行开始执行`RDB`持久化操作：
  ```bash
  1:M 29 Jul 2024 07:34:26.118 * Background saving started by pid 15
  ```
+ 执行`RDB`持久化子进程执行完后继续输出如下日志：
  ```bash
  15:C 29 Jul 2024 07:34:26.120 * DB saved on disk
  15:C 29 Jul 2024 07:34:26.120 * RDB: 0 MB of memory used by copy-on-write
  ```
+ 在时间时间函数`serverCron`中检测到执行`RDB`持久化子进行结束，会调用`backgroundSaveDoneHandler`函数，然后根据配置文件配置，
`RDB`先保存为文件然后发送给从库策略，会继续调用`backgroundSaveDoneHandlerDisk`函数，进而输出如下日志：
  ```bash
  1:M 29 Jul 2024 07:34:26.213 * Background saving terminated with success
  ```
+ 最后会调用`updateSlavesWaitingBgsave`函数将`RDB`文件发送给从库，发送完成后会调用`putSlaveOnline`函数，将从库（客服端）输出缓存命令发送给从库，
最后输出如下日志：
  ```bash
  1:M 29 Jul 2024 07:34:26.213 * Synchronization with replica 172.18.0.3:6380 succeeded
  ```

### 从库日志
+ 从库接收`replicaof`命令执行`replicaofCommand`命令处理函数，在内部会调用`replicationSetMaster`函数设置主库的地址和端口号等。
如果当前的从库之前不是从库（主库）会调用`replicationCacheMasterUsingMyself`函数执行将`master`转为`slave`设置，会输出如下日志：
  ```bash
  1:S 29 Jul 2024 07:34:25.212 * Before turning into a replica, using my master parameters to synthesize a cached master: I may be able to synchronize with the new master with just a partial transfer.
  ```
+ 在`replicaofCommand`函数中最后会打印如下日志：
  ```bash
  1:S 29 Jul 2024 07:34:25.212 * REPLICAOF my-redis:6379 enabled (user request from 'id=3 addr=172.18.0.4:54308 fd=8 name= age=558 idle=0 flags=N db=0 sub=0 psub=0 multi=-1 qbuf=43 qbuf-free=32725 obl=0 oll=0 omem=0 events=r cmd=replicaof')
  ```
+ 然后在周期执行函数`replicationCron`函数执行`connectWithMaster`函数和`master`建立`TCP`连接操作，输出如下日志：
  ```bash
  1:S 29 Jul 2024 07:34:26.112 * Connecting to MASTER my-redis:6379
  # 和 master 建立 TCP 成功后会输出此日志
  1:S 29 Jul 2024 07:34:26.117 * MASTER <-> REPLICA sync started
  ```
+ 开始执行上一步注册的事件处理函数`syncWithMaster`，输出如下日志：
  ```bash
  1:S 29 Jul 2024 07:34:26.117 * Non blocking connect for SYNC fired the event.
  ```
+ 在事件处理函数`syncWithMaster`中完成和`master`的`PING`操作，身份验证，信息同步等：
  ```bash
  1:S 29 Jul 2024 07:34:26.118 * Master replied to PING, replication can continue...
  ```
+ 在事件处理函数`syncWithMaster`中调用`slaveTryPartialResynchronization`发送`psync`同步命令及读取`master`返回结果：
  ```bash
  1:S 29 Jul 2024 07:34:26.118 * Trying a partial resynchronization (request 827139ed6e5f903a6b54573a34b125cb3471560f:1).
  1:S 29 Jul 2024 07:34:26.119 * Full resync from master: 69f3f72c743522c5ac74fba9f397a3c7231901d5:0
  ```
+ 在上一步判断走全量同步逻辑，接着会继续调用`replicationDiscardCachedMaster`函数设置`cached_master`属性为空：
  ```bash
  1:S 29 Jul 2024 07:34:26.119 * Discarding previously cached master state.
  ```
+ 在`syncWithMaster`中会注册事件处理函数`readSyncBulkPayload`，用于接收主库发送的`RDB`及加载`RDB`到内存：
  ```bash
  1:S 29 Jul 2024 07:34:26.213 * MASTER <-> REPLICA sync: receiving 225 bytes from master
  1:S 29 Jul 2024 07:34:26.214 * MASTER <-> REPLICA sync: Flushing old data
  1:S 29 Jul 2024 07:34:26.214 * MASTER <-> REPLICA sync: Loading DB in memory
  1:S 29 Jul 2024 07:34:26.214 * MASTER <-> REPLICA sync: Finished with success
  ```

# 缓存实现
用于主从同步的缓存有两种：客户端输出缓存（用于缓存回复客户端内容，在主从复制中存放是发送给从库的命令），循环缓存（用于主从断开重连的增量同步）。
## 输出缓存
每个客户端对象都有一个自己的输出缓存配置：
```c
typedef struct client {
    ...
    list *reply;            /* List of reply objects to send to the client. */
    ...
    /* Response buffer */
    int bufpos;
    char buf[PROTO_REPLY_CHUNK_BYTES];
} client;
```
输出缓存大小限制可通过配置项`client-output-buffer-limit`配置，`client-output-buffer-limit`说明如下：
+ 对于客户端没有足够快读取服务端输出缓存数据场景，例如对于发布/订阅模式下，消费者消费慢于生产者。客户端输出缓存大小限制可以用于强制断开客户端连接。
+ 服务端可以针对三种不同的客户端对象分别设置缓存大小限制：
  ```bash
  client-output-buffer-limit normal 0 0 0
  client-output-buffer-limit replica 256mb 64mb 60
  client-output-buffer-limit pubsub 32mb 8mb 60
  ```
  + `normal`：表示正常普通的客户端；
  + `replica`：针对主从复制从节点；
  + `pubsub`：订阅某个模式或者通道的客户端；
+ 配置格式如下：
  ```bash
  client-output-buffer-limit <class> <hard limit> <soft limit> <soft seconds>
  ```
  如果客户端缓存达到`<hard limit>`，则立刻断开客户端连接。或者`<soft limit>`达到且连续`<soft seconds>`时间都达到软限制，则断开客户端连接。

每次将回复数据写到客户端缓存中时（列表对象），都会检查缓存是否达到限制：
```c
void _addReplyStringToList(client *c, const char *s, size_t len) {
    ...
    asyncCloseClientOnOutputBufferLimitReached(c);
}
```
**在主从复制中，客户端输出缓存主要用于记录全量同步过程中新的写命令，用于全量同步完成后，将新增写命令同步给从库，保证数据一致性**。

## 循环缓存
循环缓存工作原理：
+ 循环缓冲区有**一个写指针**，表示主节点在缓冲区中的当前写入位置。如果写指针已经指向了缓冲区末尾，那么此时主节点再写入数据，
写指针就会重新指向缓冲区头部，从头部开始再次写入数据，这样就可以复用缓冲区空间了。
+ 循环缓冲区有**一个或多个读指针**，表示不同从节点在缓冲区中的当前读取位置。表示不同从节点在缓冲区中的当前读取位置。
当读指针指向缓冲区末尾时，从节点也会把读指针重新指向缓冲区头部，从缓冲区头部开始继续读取数据。

循环缓存主要用于主从断开重连后的增量同步，也就是将断开期间的命令同步给从库，避免全量同步操作。**每个主库只有一个循环缓存**，所有的从库共享此循环缓存。
和循环缓存相关的数据结构如下：
```c
struct redisServer {
...
char *repl_backlog;             //基于字符数组的循环缓冲区
long long repl_backlog_size;    //循环缓冲区总长度
long long repl_backlog_histlen; //循环缓冲区中当前累积的数据的长度
long long repl_backlog_idx;     //循环缓冲区的写指针位置
long long repl_backlog_off;   //循环缓冲区最早保存的数据的首字节在全局范围内的偏移
...
}
```
+ `repl_backlog_size`：记录循环缓冲区本身的总长度。这个值也对应了`redis.conf`配置文件中的`repl-backlog-size`配置项（默认`1Mb`）。
+ `repl_backlog_histlen`：记录循环缓冲区中目前累积的数据的长度，这个值不会超过缓冲区的总长度。
+ `repl_backlog_idx`：记录循环缓冲区接下来写数据时应该写入的位置，也就是循环缓冲区的写指针。
+ `repl_backlog_off`：记录循环缓冲区中最早保存的数据的首字节在全局范围内的偏移值。因为循环缓冲区会被重复使用，
所以一旦缓冲区写满后，又开始从头写数据时，缓冲区中的旧数据会被覆盖。因此，这个值就记录了仍然保存在缓冲区中，
又是最早写入的数据的首字节，在全局范围内的偏移量。

在主从复制中，主节点会累积记录它收到的要进行复制的命令总长度，这个总长度我们称之为全局范围内的复制偏移量，对应`master_repl_offset`变量。
从节点从主节点读取命令时，也会记录它读到的累积命令的位置，这个位置称之为全局范围内的读取偏移量。

假设主节点收到三条命令，每条命令长度都是`16`字节，那么此时，全局复制偏移量是`48`。假设一个从节点从主节点上读了一条命令，此时，该从节点的全局读取位置就是`16`。

循环缓存的创建`createReplicationBacklog`的实现如下：
```c
void createReplicationBacklog(void) {
    serverAssert(server.repl_backlog == NULL);
    server.repl_backlog = zmalloc(server.repl_backlog_size);
    server.repl_backlog_histlen = 0;
    server.repl_backlog_idx = 0;

    /* We don't have any data inside our buffer, but virtually the first
     * byte we have is the next byte that will be generated for the
     * replication stream. */
    server.repl_backlog_off = server.master_repl_offset+1;
}

void syncCommand(client *c) {
    ...
    /* Create the replication backlog if needed. */
    if (listLength(server.slaves) == 1 && server.repl_backlog == NULL) {
        ...
        createReplicationBacklog();
    }
    ...
}
```
循环缓存的写操作由`feedReplicationBacklog`函数实现，主要分以下几部分：
+ 更新全局范围内的复制偏移量`master_repl_offset`值（主库接收的命令总长度）：
  ```c
  void feedReplicationBacklog(void *ptr, size_t len) {
      unsigned char *p = ptr;
      server.master_repl_offset += len;
      ...
  }
  ```
+ 通过循环，将数据写入到循环缓存区：
  ```c
  void feedReplicationBacklog(void *ptr, size_t len) {
      ...
      while(len) {
          // 计算本轮循环能写入的数据长度 thislen
          size_t thislen = server.repl_backlog_size - server.repl_backlog_idx;
          if (thislen > len) thislen = len;
          // 将数据写入到循环缓存中，写入的起始位置是 repl_backlog_idx
          memcpy(server.repl_backlog+server.repl_backlog_idx,p,thislen);
          // 更新写指针
          server.repl_backlog_idx += thislen;
          // 如果写指针指向循环缓存末尾，说明缓存区已满，将写指针指向缓存区起始位置，从头开始写
          if (server.repl_backlog_idx == server.repl_backlog_size)
              server.repl_backlog_idx = 0;
          // 更新剩余待写数据大小
          len -= thislen;
          // 更新要写入循环缓冲区的数据指针位置
          p += thislen;
          // 更新缓冲区已写数据大小
          server.repl_backlog_histlen += thislen;
      }
      ...
  }
  ```
+ 循环写结束后，检查并更新`repl_backlog_histlen`和`repl_backlog_off`属性值：
  ```c
  void feedReplicationBacklog(void *ptr, size_t len) {
      ...
      if (server.repl_backlog_histlen > server.repl_backlog_size)
          server.repl_backlog_histlen = server.repl_backlog_size;
      /* Set the offset of the first byte we have in the backlog. */
      server.repl_backlog_off = server.master_repl_offset -
                                server.repl_backlog_histlen + 1;
  }
  ```
  如果`repl_backlog_histlen`大小超过缓存区总大小`repl_backlog_size`，则更新`repl_backlog_histlen`为缓冲区总长度。
  即，一旦缓冲区写满后，就维持`repl_backlog_histlen`为缓冲区总长度。`repl_backlog_off`值会被更新为全局复制偏移量减去`repl_backlog_histlen`值再加`1`。

循环缓存的读操作由`addReplyReplicationBacklog`函数实现。当从库发送`psync <runid> <offset>`时，主库处理`psync`命令会先尝试调用`masterTryPartialResynchronization`执行部分同步，
若可以执行部分同步，在`masterTryPartialResynchronization`中会调用`addReplyReplicationBacklog`执行实际的部分同步操作。

`addReplyReplicationBacklog`执行逻辑主要分为以下几部分：
+ 用从节点发送的全局读取位置`offset`减去`repl_backlog_off`的值，从而得到从节点读数据时要跳过的数据长度`skip`：
  ```c
  long long addReplyReplicationBacklog(client *c, long long offset) {
      ...
      /* Compute the amount of bytes we need to discard. */
      skip = offset - server.repl_backlog_off;
  }
  ```
  `repl_backlog_off`表示仍在缓冲区中的最早保存的数据的首字节在全局范围内的偏移量。
+ 计算缓冲区中，最早保存的数据的首字节对应在缓冲区中的位置：
  ```c
  long long addReplyReplicationBacklog(client *c, long long offset) {
      ...
      j = (server.repl_backlog_idx +
        (server.repl_backlog_size-server.repl_backlog_histlen)) %
        server.repl_backlog_size;
      ...
  }
  ```
  如果缓存区没有写满，则`repl_backlog_histlen = repl_backlog_idx`，所以计算结果`j = 0`，即最早保存数据的首字节在缓冲区起始位置。
  如果缓存区写满，则`repl_backlog_histlen = repl_backlog_size`，所以计算结果`j = repl_backlog_idx`，即最早保存数据的首字节在缓冲区的`repl_backlog_idx`位置。
+ 计算从节点的全局读取位置在缓冲区中的对应位置：
  ```c
  long long addReplyReplicationBacklog(client *c, long long offset) {
      ...
      /* Discard the amount of data to seek to the specified 'offset'. */
      j = (j + skip) % server.repl_backlog_size;
      ...
  }
  ```
  此时，可知从节点要在缓冲区的哪个位置开始读取数据。
+ 计算实际要读取的数据长度`len`，最终是要将缓存区中所有的数据都发送给从库：
  ```c
  long long addReplyReplicationBacklog(client *c, long long offset) {
      ...
      len = server.repl_backlog_histlen - skip;
      ...
  }
  ```
+ 将缓存中的数据发送给从库：
  ```c
  long long addReplyReplicationBacklog(client *c, long long offset) {
      ...
      while(len) {
          long long thislen =
              ((server.repl_backlog_size - j) < len) ?
              (server.repl_backlog_size - j) : len;
  
          serverLog(LL_DEBUG, "[PSYNC] addReply() length: %lld", thislen);
          addReplySds(c,sdsnewlen(server.repl_backlog + j, thislen));
          len -= thislen;
          j = 0;
      }
      return server.repl_backlog_histlen - skip;
  }
  ```
  需要考虑在循环缓冲区中，从节点可能从读取起始位置一直读到缓冲区尾后，还没有读完，还要再从缓冲区头继续读取。

继续看下可以执行部分同步的条件，在`masterTryPartialResynchronization`中：
```c
int masterTryPartialResynchronization(client *c) {
    ...
    if (!server.repl_backlog ||
        psync_offset < server.repl_backlog_off ||
        psync_offset > (server.repl_backlog_off + server.repl_backlog_histlen))
    {
        ...
        goto need_full_resync;
    }
}
```
需要同时满足下面三个条件：
+ 循环缓存存在；
+ 从节点发送的全局读位置大于主节点循环缓存中最早保存数据的位置；
+ 从节点发送的全局读位置和主节点循环缓存中最早保存数据位置差值要小于`repl_backlog_histlen`值；

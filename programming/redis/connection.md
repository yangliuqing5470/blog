> 服务端基于`redis`源码分支`5.0`，客户端基于`redis-py`版本`5.0.9`

# 服务端连接管理
## 连接创建
`redis`服务端对象使用一个列表对象记录每一个连接的客户端对象：
```c
struct redisServer{
    list *clients;              /* List of active clients */
}
```
在`redis`[服务启动](./server.md)完成后，会通过`acceptTcpHandler`读事件函数完成对客户端的连接。在`acceptTcpHandler`函数内部，`accept`成功后，
会调用`acceptCommonHandler`完成客户端对象`client`的创建（调用`createClient`函数），以及将客户端对象添加到`server->clients`链表中。
```c
client *createClient(int fd) {
    if (fd != -1) {
        anetNonBlock(NULL,fd);
        anetEnableTcpNoDelay(NULL,fd);
        if (server.tcpkeepalive)
            anetKeepAlive(NULL,fd,server.tcpkeepalive);
        // 新连接的客户端对象，注册读事件处理函数 readQueryFromClient，用于处理命令请求
        if (aeCreateFileEvent(server.el,fd,AE_READABLE,
            readQueryFromClient, c) == AE_ERR)
        {
            close(fd);
            zfree(c);
            return NULL;
        }
    }
    ...
    // 添加创建的客户端对象到 server.clients 链表中
    if (fd != -1) linkClient(c);
    ...
}

void linkClient(client *c) {
    listAddNodeTail(server.clients,c);
    // 记录客户端对象在 clients 链表的位置，用于后面常数时间删除
    c->client_list_node = listLast(server.clients);
    uint64_t id = htonu64(c->id);
    raxInsert(server.clients_index,(unsigned char*)&id,sizeof(id),c,NULL);
```

## 连接释放
在多种场景下`redis`服务端会释放客户端连接对象。
+ 在服务端接受客户端的请求连接，但服务端已连接客户端对象超过配置的最大连接数`maxclients`时，服务端会拒绝连接，释放客户端对象：
  ```c
  static void acceptCommonHandler(int fd, int flags, char *ip) {
      ...
      if (listLength(server.clients) > server.maxclients) {
          char *err = "-ERR max number of clients reached\r\n";
  
          /* That's a best effort error message, don't check write errors */
          if (write(c->fd,err,strlen(err)) == -1) {
              /* Nothing to do, Just to avoid the warning... */
          }
          server.stat_rejected_conn++;
          freeClient(c);
          return;
      }
  }
  ```
+ 服务端给客户端发送数据遇到错误（回复客户端），服务端会释放客户端：
  ```c
  int writeToClient(int fd, client *c, int handler_installed) {
      ...
      // nwritten 为 socket write 的返回值
      if (nwritten == -1) {
          if (errno == EAGAIN) {
              nwritten = 0;
          } else {
              serverLog(LL_VERBOSE,
                  "Error writing to client: %s", strerror(errno));
              freeClient(c);
              return C_ERR;
          }
      }
  }
  ```
+ 从客户端`socket`读数据遇到错误（例如配置了`tcp-keepalive`，遇到客户端异常断开），或者客户端对象关闭，则服务端释放客户端对象：
  ```c
  void readQueryFromClient(aeEventLoop *el, int fd, void *privdata, int mask) {
      ...
      nread = read(fd, c->querybuf+qblen, readlen);
      if (nread == -1) {
          if (errno == EAGAIN) {
              return;
          } else {
              serverLog(LL_VERBOSE, "Reading from client: %s",strerror(errno));
              freeClient(c);
              return;
          }
      } else if (nread == 0) {
          serverLog(LL_VERBOSE, "Client closed connection");
          freeClient(c);
          return;
      }
      ...
  }
  ```
+ 客户端输入请求数据缓存满的时候（服务端处理命令太慢，导致客户端请求数据一直积压），服务端会释放客户端对象：
  ```c
  void readQueryFromClient(aeEventLoop *el, int fd, void *privdata, int mask) {
      ...
      // querybuf 客户端输入缓存，存放客户端请求数据
      if (sdslen(c->querybuf) > server.client_max_querybuf_len) {
          sds ci = catClientInfoString(sdsempty(),c), bytes = sdsempty();
  
          bytes = sdscatrepr(bytes,c->querybuf,64);
          serverLog(LL_WARNING,"Closing client that reached max query buffer length: %s (qbuf initial bytes: %s)", ci, bytes);
          sdsfree(ci);
          sdsfree(bytes);
          freeClient(c);
          return;
      }
  }
  ```
+ 客户端主动`CLIENT KILL`命令时，服务端会释放客户端对象：
  ```c
  void clientCommand(client *c) {
      ...
      else if (!strcasecmp(c->argv[1]->ptr,"kill")) {
          ...
          freeClient(client);
          ...
      }
  }
  ```
+ 某些场景下，需要服务端回复完客户端后，释放客户端对象，例如客户端执行`quit`命令，其他异常情况：
  ```c
  int processCommand(client *c) {
      ...
      if (!strcasecmp(c->argv[0]->ptr,"quit")) {
          addReply(c,shared.ok);
          // 设置客户端标志 CLIENT_CLOSE_AFTER_REPLY，服务端回复完后就关闭客户端对象
          c->flags |= CLIENT_CLOSE_AFTER_REPLY;
          return C_ERR;
      }
      ...
  }

  int writeToClient(int fd, client *c, int handler_installed) {
      ...
      // 客户端输出缓存发送完，没有数据
      if (!clientHasPendingReplies(c)) {
          c->sentlen = 0;
          if (handler_installed) aeDeleteFileEvent(server.el,c->fd,AE_WRITABLE);
  
          /* Close connection after entire reply has been sent. */
          if (c->flags & CLIENT_CLOSE_AFTER_REPLY) {
              freeClient(c);
              return C_ERR;
          }
      }
      return C_OK;
  }
  ```
+ 如果服务端配置了客户端超时时间（多长时间和客户端没有交互），超时的时候会释放对应的客户端，此操作在`serverCron`函数中周期检查：
  ```c
  int clientsCronHandleTimeout(client *c, mstime_t now_ms) {
      ...
      // lastinteraction 表示客户端上次和服务端交互的时间
      if (server.maxidletime &&
          !(c->flags & CLIENT_SLAVE) &&    /* no timeout for slaves and monitors */
          !(c->flags & CLIENT_MASTER) &&   /* no timeout for masters */
          !(c->flags & CLIENT_BLOCKED) &&  /* no timeout for BLPOP */
          !(c->flags & CLIENT_PUBSUB) &&   /* no timeout for Pub/Sub clients */
          (now - c->lastinteraction > server.maxidletime))
      {
          serverLog(LL_VERBOSE,"Closing idle client");
          freeClient(c);
          return 1;
      }
      ...
  }
  ```
  `maxidletime`参数值通过配置文件`timeout`指定，默认是`0`，表示不开启此功能。

`redis`服务端是根据`TCP`**长连接**设计实现的，也就是服务端每次执行完客户端的请求命令不会主动关闭`TCP`，`TCP`的关闭通过客户端主动断开或者超时配置。

**客户端主动断开**，例如调用`socket.close()`方法，服务端调用`read`会返回`0`，进而释放客户端：
```c
void readQueryFromClient(aeEventLoop *el, int fd, void *privdata, int mask) {
    ...
    nread = read(fd, c->querybuf+qblen, readlen);
    ...
    else if (nread == 0) {
        serverLog(LL_VERBOSE, "Client closed connection");
        freeClient(c);
        return;
    }
    ...
}
```
**超时**有两种配置，一种是配置`timeout`参数，指定客户端最大空闲超时时间（上面已介绍）。另一种是配置`tcp-keepalive`参数，
通过`socket`的`SO_KEEPALIVE`属性开启`TCP`保活探测。相关的三个属性说明如下：
+ `tcp_keepalive_time`：在发送`TCP`保活探针前，`TCP`连接空闲时间（没有数据交互），单位是秒。
+ `tcp_keepalive_probes`：发送`TCP`保活探针的最大次数，如果最大次数达到，对端依然没有响应，则关闭连接。
+ `tcp_keepalive_intvl`：保活探测发送的时间间隔，单位是秒。

在`redis`服务中`tcp-keepalive`配置默认值是`300`，默认会将`tcp_keepalive_time`设置为`300`，`tcp_keepalive_intvl`设置为`300/3 = 100`，`tcp_keepalive_probes`设置为`3`。

也就是说，一个客户端如果`300s`没有和服务端交互（可能客户端异常关闭，客户端服务端网络不通），则服务端会发送一个`TCP`保活探针，最多发送`3`次，
每次时间间隔是`100s`，如果客户端一直不响应，则服务端调用`read`会返回错误，关闭客户端对象：
```c
void readQueryFromClient(aeEventLoop *el, int fd, void *privdata, int mask) {
    ...
    nread = read(fd, c->querybuf+qblen, readlen);
    if (nread == -1) {
        if (errno == EAGAIN) {
            return;
        } else {
            serverLog(LL_VERBOSE, "Reading from client: %s",strerror(errno));
            freeClient(c);
            return;
        }
    }
    ...
}
```
实验说明如下：
+ 启动`redis`服务端，便于观察，调整日志水平为`verbose`；
  ```bash
  $ sudo docker run -it --rm --network redis --name my-redis -p 6379:6379 redis:5.0.0 --loglevel verbose
  1:C 01 Aug 2024 08:23:29.768 # oO0OoO0OoO0Oo Redis is starting oO0OoO0OoO0Oo
  1:C 01 Aug 2024 08:23:29.768 # Redis version=5.0.0, bits=64, commit=00000000, modified=0, pid=1, just started
  1:C 01 Aug 2024 08:23:29.768 # Configuration loaded
                  _._                                                  
             _.-``__ ''-._                                             
        _.-``    `.  `_.  ''-._           Redis 5.0.0 (00000000/0) 64 bit
    .-`` .-```.  ```\/    _.,_ ''-._                                   
   (    '      ,       .-`  | `,    )     Running in standalone mode
   |`-._`-...-` __...-.``-._|'` _.-'|     Port: 6379
   |    `-._   `._    /     _.-'    |     PID: 1
    `-._    `-._  `-./  _.-'    _.-'                                   
   |`-._`-._    `-.__.-'    _.-'_.-'|                                  
   |    `-._`-._        _.-'_.-'    |           http://redis.io        
    `-._    `-._`-.__.-'_.-'    _.-'                                   
   |`-._`-._    `-.__.-'    _.-'_.-'|                                  
   |    `-._`-._        _.-'_.-'    |                                  
    `-._    `-._`-.__.-'_.-'    _.-'                                   
        `-._    `-.__.-'    _.-'                                       
            `-._        _.-'                                           
                `-.__.-'                                               
  
  1:M 01 Aug 2024 08:23:29.770 # Server initialized
  1:M 01 Aug 2024 08:23:29.770 * Ready to accept connections
  1:M 01 Aug 2024 08:24:39.540 - 0 clients connected (0 replicas), 791872 bytes in use
  ```
+ 启动一个客户端连接服务端；
  ```bash
  1:M 01 Aug 2024 08:24:42.030 - Accepted 10.211.55.2:56624
  1:M 01 Aug 2024 08:34:43.745 - 1 clients connected (0 replicas), 812760 bytes in use
  ```
+ 断开服务端和客户端的网络连接，此时一直打印如下日志；
  ```bash
  1:M 01 Aug 2024 08:34:43.745 - 1 clients connected (0 replicas), 812760 bytes in use
  ```
+ 根据`redis`服务的默认配置，`300s`后服务端会发送第一个`TCP`探针，最多发送`3`次，每次间隔`100s`，因此大概`600s`后服务端会释放客户端对象；
  ```bash
  1:M 01 Aug 2024 08:34:48.670 - Reading from client: Connection timed out
  1:M 01 Aug 2024 08:34:51.254 - 0 clients connected (0 replicas), 791888 bytes in use
  ```

# 客户端连接管理
## 短连接
短连接指的是客户端每进行一次操作，都会建立一次连接，操作完成后立即关闭连接。短连接适用于不频繁通信的场景，
或需要保证每次操作都使用新的连接的情况。短连接步骤如下：
+ 建立连接。
+ 执行操作。
+ 关闭连接。
+ 需要再次操作时，重新建立连接。

短连接实现样例如下：
```python
import redis

def redis_operation():
    # 每次操作都创建新的连接
    client = redis.StrictRedis(host='localhost', port=6379, db=0)
    
    # 进行 Redis 操作
    client.set('key', 'value')
    value = client.get('key')
    print(value)
    
    # 操作完成后立即关闭连接
    client.close()

# 进行多次操作时，每次都建立和关闭连接
redis_operation()
redis_operation()
```

## 长连接
长连接指的是客户端与服务器之间建立一个连接后，在整个会话过程中持续使用该连接，直到客户端主动关闭连接或者连接因某些原因中断。
长连接通常用于需要频繁通信的场景，减少了连接和断开连接的开销。长连接步骤如下：
+ 建立连接。
+ 保持连接，在需要时进行读写操作。
+ 关闭连接（当不再需要时）。

长连接实现样例如下：
```python
import redis

# 创建 Redis 连接对象
client = redis.StrictRedis(host='localhost', port=6379, db=0)

# 进行一些 Redis 操作
client.set('key', 'value')
value = client.get('key')
print(value)

# 在需要时关闭连接
client.close()
```

## 连接池
连接池主要用来管理长连接，用于并发场景下。`redis-py`客户端默认使用连接池，每个`redis-py`实例默认有自己的连接池。
```python
class Redis(RedisModuleCommands, CoreCommands, SentinelCommands):
    ...
    if not connection_pool:
        connection_pool = ConnectionPool(**kwargs)
        ...
```
可以使用自定义连接池：
```python
import redis

# 创建一个连接池，设置最大连接数
pool = redis.ConnectionPool(host='localhost', port=6379, db=0, max_connections=10)

# 使用这个连接池创建 Redis 对象
client = redis.StrictRedis(connection_pool=pool)
```
每次执行命令的流程如下：
+ 从连接池获取一个可用连接，如果没有可以连接，则新创建一个连接；
+ 命令执行完后将连接归还到池子中；

命令执行流程实现：
```python
def execute_command(self, *args, **options):
    """Execute a command and return a parsed response"""
    command_name = args[0]
    keys = options.pop("keys", None)
    pool = self.connection_pool
    # 从连接池中获取一个连接
    conn = self.connection or pool.get_connection(command_name, **options)
    response_from_cache = conn._get_from_local_cache(args)
    try:
        if response_from_cache is not None:
            return response_from_cache
        else:
            response = conn.retry.call_with_retry(
                lambda: self._send_command_parse_response(
                    conn, command_name, *args, **options
                ),
                lambda error: self._disconnect_raise(conn, error),
            )
            if keys:
                conn._add_to_local_cache(args, response, keys)
            return response
    finally:
        # 命令执行完释放连接到池子中
        if not self.connection:
            pool.release(conn)
```
从连接池获取一个连接实现如下：
```python
def get_connection(self, command_name: str, *keys, **options) -> "Connection":
    "Get a connection from the pool"
    self._checkpid()
    with self._lock:
        try:
            connection = self._available_connections.pop()
        except IndexError:
            connection = self.make_connection()
        self._in_use_connections.add(connection)
    # 下面逻辑判断连接的可用性
    ...
```

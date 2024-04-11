# Socket
基于 TCP 的 socket 编程一般流程如下：
![socket编程流程](./images/socket编程流程.png)
详细的入门指导可参考 [同步socket编程](https://realpython.com/python-sockets/)。Asyncio 库提供了 socket 编程 API 部分同步接口的
异步版本，具体如下表所示：
| 阻塞 socket <img width=250/>| 异步 socket <img width=250/>|
| :---------- | :---------- |
|`socket`|-|
|`bind`|-|
|`listen`|-|
|`accept`|`sock_accept`|
|`connect`|`sock_connect`|
|`recv`|`sock_recv`|
|`send`|-|
|`sendall`|`sock_sendall`|

在介绍异步 socket API 源码之前，先看一个具体的基于 asyncio 实现的 socket 编程。服务端代码如下：
```python
import socket
import asyncio

port = 9006

async def handle_client(client, addr):
    loop = asyncio.get_event_loop()
    result = None
    while result != "quit":
        result = await loop.sock_recv(client, 1024)
        result = result.decode()
        print("got from {0}: {1}".format(addr, result))
        response = "got message"
        await loop.sock_sendall(client, response.encode())
    client.close()

async def run_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("", port))
    server.listen(5)
    server.setblocking(False)

    loop = asyncio.get_event_loop()

    while True:
        client, addr = await loop.sock_accept(server)
        print("connected to client: ", addr)
        loop.create_task(handle_client(client, addr))

asyncio.run(run_server())
```
客户端代码如下：
```python
import socket
import asyncio

async def request():
    loop = asyncio.get_event_loop()
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    await loop.sock_connect(client, ("127.0.0.1", 9006))
    await loop.sock_sendall(client, "ack from client connect success".encode())
    result = await loop.sock_recv(client, 1024)
    print(result.decode())
    while True:
        send_message = input()
        await loop.sock_sendall(client, send_message.encode())
        if send_message == "quit":
            break
        receive_message = await loop.sock_recv(client, 1024)
        print("got message from server: ", receive_message.decode())
    client.close()

asyncio.run(request())
```
运行服务端代码和客户端代码，输出结果如下:
```bash
# 服务端结果
$ python3 server.py
connected to client:  ('127.0.0.1', 57404)
got from ('127.0.0.1', 57404): ack from client connect success
got from ('127.0.0.1', 57404): hello world
got from ('127.0.0.1', 57404): quit

# 客户端结果
$ python3 client.py
got message
hello world
got message from server:  got message
quit
$
```
上面的服务端和客户端在建立连接过程中分别使用了`sock_accept`和`sock_connect`异步接口，其源码实现如下：
```python
async def sock_accept(self, sock):
    """Accept a connection.

    The socket must be bound to an address and listening for connections.
    The return value is a pair (conn, address) where conn is a new socket
    object usable to send and receive data on the connection, and address
    is the address bound to the socket on the other end of the connection.
    """
    # 如果是 ssl socket 则抛出异常
    _check_ssl_socket(sock)
    if self._debug and sock.gettimeout() != 0:
        raise ValueError("the socket must be non-blocking")
    # 创建一个 Future 对象，表示此操作未来结果
    fut = self.create_future()
    self._sock_accept(fut, sock)
    return await fut

def _sock_accept(self, fut, sock):
    fd = sock.fileno()
    try:
        conn, address = sock.accept()
        conn.setblocking(False)
    except (BlockingIOError, InterruptedError):
        # 确保当前的 sock 没有绑定 在运行的 transport 对象
        self._ensure_fd_no_transport(fd)
        # 走到这里表示还没有新的 client 连接，将监听 socket 注册到 epoll/iocp/select/... 可读事件
        handle = self._add_reader(fd, self._sock_accept, fut, sock)
        fut.add_done_callback(
            functools.partial(self._sock_read_done, fd, handle=handle))
    except (SystemExit, KeyboardInterrupt):
        raise
    except BaseException as exc:
        # 设置异常，传递给上层调用
        fut.set_exception(exc)
    else:
        # 新的 client 连接成功，设置 sock_accept 操作结果以通知上层调用恢复执行
        fut.set_result((conn, address))

def _sock_read_done(self, fd, fut, handle=None):
    if handle is None or not handle.cancelled():
        self.remove_reader(fd)
```
`sock_accept`内部会创建一个 Future 对象表示未来执行的结果，当新的连接建立后，会更新此 Future 结果以通知上层调用继续执行。
继续看`sock_connect`的源码：
```python

```

# Transport&Prorocols

# Streams

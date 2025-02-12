# 引言
在介绍`aiohttp`实现`WebSocket`客户端之前，先看下`WebSocket`客户端样例代码：
```python
import aiohttp
import asyncio

async def websocket_client():
    url = "ws://example.com/ws"  # 替换为实际 WebSocket 服务器地址
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url) as ws:
            print("WebSocket 连接已建立")
            # 发送消息
            await ws.send_str("你好，服务器！")
            # 监听接收消息
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    print(f"收到消息: {msg.data}")

                    if msg.data == "close":
                        await ws.close()
                        break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print("WebSocket 连接出错")
                    break

            print("WebSocket 连接已关闭")
# 运行 WebSocket 客户端
asyncio.run(websocket_client())
```
和`HTTP`客户端相比，`WebSocket`客户端也是使用会话模式，差异是通过`session.ws_connect`方法发起客户端请求。
返回获取一个`ClientWebSocketResponse`对象`ws`，基于此对象实现`WebSocket`通信。

**会话**的原理可以参考 [`HTTP`客户端实现](./framework_client.md)。这里只关注`WebSocket`协议部分的内容。
`WebSocket`客户端请求主要分如下几步：
+ 构建请求头，通过`HTTP`协议发送`WebSocket`客户端请求。
+ 对`WebSocket`客户端请求响应进行`WebSocket`协议验证检查，也就是完成握手过程。
+ 返回`ClientWebSocketResponse`对象用于`WebSocket`通信。

# WebSocket 连接建立
`WebSocket`连接建立分为如下步骤：
+ **请求头构建**：`WebSocket`客户端发起请求自动构建的请求头如下。
  ```python
  {
      "Upgrade": "websocket",
      "Connection": "Upgrade",
      "Sec-WebSocket-Version": "13",
      "Sec-WebSocket-Key": "一个16位置的字符串",
      "Sec-WebSocket-Protocol": "如果参数指定了使用的子协议，值是字符串，每个子协议用逗号分割",
      "Origin": "如果参数指定了 Origin 值，有此头",
      "Sec-WebSocket-Extensions": "如果参数指定了 compress，则值是 permessage-deflate; client_max_window_bits; server_max_window_bits=<compress>",
  }
  ```
+ **请求发送**：通过`HTTP`协议发送客户端请求，并等待响应。
+ **握手**：客户端握手过程如下。
  + 检查响应状态码是`101`；检查响应头`Upgrade`、`Connection`、`Sec-WebSocket-Accept`。如果检查失败，关闭`WebSocket`连接。
  + 如果响应头`Sec-WebSocket-Protocol`存在，则设置客户端使用的具体子协议属性。使用子协议的服务端和客户端样例如下：
    ```python
    # 服务端代码----支持多个不同子协议通信
    import aiohttp
    from aiohttp import web
    import asyncio
    import json
    
    # 模拟子协议 A：基于 JSON 协议
    async def protocol_a_handler(ws, msg_data):
        data = json.loads(msg_data)
        return json.dumps({"response": f"Protocol-A received: {data}"})
    
    # 模拟子协议 B：基于换行符分隔消息
    async def protocol_b_handler(ws, msg_data):
        return f"Protocol-B received: {msg_data}"
    
    async def websocket_handler(request):
        ws = web.WebSocketResponse(protocols=['protocol-A', 'protocol-B'])
        await ws.prepare(request)
        print(f"客户端连接使用的子协议：{ws.protocol}")
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                print(f"收到消息：{msg.data}")
                # 根据客户端选择的协议进行不同的处理
                if ws.protocol == 'protocol-A':
                    response = await protocol_a_handler(ws, msg.data)
                elif ws.protocol == 'protocol-B':
                    response = await protocol_b_handler(ws, msg.data)
                await ws.send_str(response)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                print(f"WebSocket 连接异常：{ws.exception()}")
        print("WebSocket 连接关闭")
        return ws
    app = web.Application()
    app.router.add_get('/ws', websocket_handler)
    
    if __name__ == '__main__':
        web.run_app(app, port=8080)

    # 客户端代码----选择一个子协议通信
    import aiohttp
    import asyncio
    import json
    
    async def websocket_client():
        async with aiohttp.ClientSession() as session:
            # 客户端选择使用 'protocol-A'
            async with session.ws_connect('http://localhost:8080/ws', protocols=['protocol-A']) as ws:
                print(f"已连接，协商后的子协议：{ws.protocol}")
                # 向服务器发送 JSON 格式消息
                message = json.dumps({"message": "Hello, Server!"})
                await ws.send_str(message)
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        print(f"收到回响：{msg.data}")
                        break
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        print(f"连接异常：{ws.exception()}")
    
    if __name__ == '__main__':
        asyncio.run(websocket_client())
    ```
  + 根据响应头`Sec-WebSocket-Extensions`获取客户端和服务端协商后的数据压缩参数。
+ **返回`ClientWebSocketResponse`对象用于`WebSocket`通信**。

# WebSocket 通信
在`ClientWebSocketResponse`对象的数据通信流程和服务端数据通信原理及接口方法基本一致，可以参考之前在[WebSocket服务端原理](./websockets.md) 部分中**数据传输**部分。
关于心跳包的初始化启动的区别：
+ 在服务端是通过`prepare`方法实现。
+ 在客户端是通过`ClientWebSocketResponse`初始化时候实现。

# 超时时间
对于`WebSocket`客户端通信，`aiohttp`提供了用于`WebSocket`协议通信的超时时间对象`ClientWSTimeout`：
```python
@attr.s(frozen=True, slots=True)
class ClientWSTimeout:
    ws_receive = attr.ib(type=Optional[float], default=None)
    ws_close = attr.ib(type=Optional[float], default=None)
```
其中默认的超时时间是：
```python
DEFAULT_WS_CLIENT_TIMEOUT = ClientWSTimeout(ws_receive=None, ws_close=10.0)
```
各个字段的含义如下：
+ **ws_receive**：调用`received`方法到获取到响应数据的超时时间。
+ **ws_close**：`WebSocket`关闭期间获取`close`帧响应的超时时间，也就是调用`close`方法中获取`close`帧响应的超时时间。

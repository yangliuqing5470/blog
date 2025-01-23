# 原理
[websocket协议规范](https://www.rfc-editor.org/rfc/rfc6455#page-37)

[websocket服务端简介](https://developer.mozilla.org/zh-CN/docs/Web/API/WebSockets_API/Writing_WebSocket_servers)

`http`协议是个半双工通信协议，也即只能由客户端发起请求，服务端响应。对于需要双端通信的场景（客户端和服务端都需要实时感知对方数据的变化），
在`websocket`协议之前的解决方案是使用`http polling`或者`http long polling`。

**http polling**：
+ **工作原理**：客户端定期（例如周期 1s）向服务器发送请求，以获取最新的数据。客户端发送请求后，服务器会立即响应当前可用的数据（如果有的话），
然后客户端在收到响应后立即发起下一次请求。这样的请求/响应循环会周期性地重复。
+ **过程**：
  + 客户端发送 HTTP 请求到服务器。
  + 服务器处理请求，并立刻返回最新的数据（如果有的话，没有新数据也返回告知没有）。
  + 客户端收到响应后，立即发送下一个 HTTP 请求。
+ **存在问题**：
  + 时延：因为只有客户端请求，服务端才会响应更新后的数据，每次客户端轮询之间可能会有一段时间的等待；
  + 资源浪费：即使服务端没有新数据，客户端定期发送 http 请求，浪费网络带宽，系统等资源；

**HTTP long polling**：
+ **工作原理**：客户端发送一个请求到服务器，但是服务器不会立即返回响应。相反，服务器会等待直到有新数据可用时，
然后才返回响应给客户端。一旦客户端收到响应后，它会立即发送下一个请求，继续等待新数据。
+ **过程**：
  + 客户端发送 HTTP 请求到服务器。
  + 服务器收到请求后，检查是否有新数据可用。
  + 如果有新数据，则立即返回响应给客户端，客户端收到响应后处理数据，并立即发送下一个请求。
  + 如果没有新数据可用，则服务器保持连接打开，等待新数据到来或者达到超时时间后返回响应。
+ **存在问题**：
  + 时延：因为只有客户端请求，服务端才会响应更新后的数据，和`http polling`比减轻延迟，但还是存在；
  + 资源占用：虽然和`http polling`比减少 HTTP 请求数，但需要维持 HTTP 连接，占用服务器资源；

为了解决上述问题，`websocket`协议出现了，`websocket`协议是全双工通信，且是长连接的；
`websocket`协议使得在客户端和服务端通信过程中只需要建立一次 HTTP 连接。

`websocket`协议主要由两个阶段组成：**握手**和**数据传输**。
## 握手
握手由客户端发起，服务端解析并响应握手结果，客户端请求报文样例如下：
```bash
GET /chat HTTP/1.1
Host: server.example.com
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==
Origin: http://example.com
Sec-WebSocket-Protocol: chat, superchat
Sec-WebSocket-Version: 13
# 下面两个是可选的
Sec-WebSocket-Protocol: chat, superchat
Sec-WebSocket-Extensions: permessage-deflate; client_max_window_bits
```
+ `Upgrade: websocket`：请求升级为 WebSocket 连接；
+ `Connection: Upgrade`：表示协议升级；
+ `Origin: http://example.com`：可选，所有浏览器客户端都会有这个请求头，指示了客户端创建 WebSocket 连接的网页的源信息。
服务器可以根据 Origin 头部来验证请求的来源，以确保连接来自于合法的网页；
+ `Sec-WebSocket-Version: 13`：指定 WebSocket 协议的版本号，当前版本为 13；
+ `Sec-WebSocket-Key：dGhlIHNhbXBsZSBub25jZQ==`：当客户端发送一个 WebSocket 握手请求时，它会生成一个随机的 Sec-WebSocket-Key
并将其包含在请求头中发送给服务器。服务器在收到这个请求后，会使用一种算法来处理这个键，通常是将其与一个固定的 GUID 结合并进行一些哈希运算。
然后，服务器会在响应中包含自己的处理结果，并将其作为 Sec-WebSocket-Accept 头部的值返回给客户端。客户端接收到响应后，
会验证服务器的处理结果，如果验证成功，则建立 WebSocket 连接；
+ `Sec-WebSocket-Protocol: chat, superchat`：指定了两个子协议：chat 和 superchat。客户端向服务器表明它希望在 WebSocket 连接上使用这些协议之一进行通信。
服务器可以选择其中一个协议与客户端进行通信，或者在支持的协议列表中选择一个最合适的协议；
+ `Sec-WebSocket-Extensions: permessage-deflate; client_max_window_bits`：指示了客户端选择了一个名为 permessage-deflate 的扩展，
并且指定参数 client_max_window_bits。这个参数表示客户端在压缩过程中所允许的最大压缩窗口大小，默认值是 15；

服务端响应报文样例如下：
```bash
HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=
# 下面是可选的
Sec-WebSocket-Protocol: chat
Sec-WebSocket-Extensions: permessage-deflate; server_max_window_bits=15
```
+ `Sec-WebSocket-Protocol: chat`：服务器在与客户端协商后选择的子协议，表示服务器愿意在此连接上使用 chat 子协议进行通信；
+ `Sec-WebSocket-Extensions: permessage-deflate; server_max_window_bits=15`：指示了服务器选择了一个名为 permessage-deflate 的扩展，
并且指定参数 server_max_window_bits=15。这个参数表示服务器在压缩过程中所允许的最大压缩窗口大小；
+ `Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK`：确认客户端发起的 WebSocket 连接握手请求的合法性。
它是通过对客户端发送的 Sec-WebSocket-Key 进行处理得到的哈希值；

> `permessage-deflate`拓展参数有如下四个：
>   + client_no_context_takeover：指定客户端是否允许在消息传输过程中不保留压缩上下文。如果指定了该参数，表示客户端在每个消息之间不会保留压缩上下文，这可能会增加每个消息的压缩开销，但可以节省内存。默认情况下，保留压缩上下文。
>   + server_no_context_takeover：指定服务器是否允许在消息传输过程中不保留压缩上下文。与上述的 client_no_context_takeover 相似，但是应用于服务器端。
>   + client_max_window_bits：指定客户端在压缩过程中所允许的最大压缩窗口大小。窗口大小越大，可以提供更好的压缩效果，但也会消耗更多的内存。
>   + server_max_window_bits：指定服务器在压缩过程中所允许的最大压缩窗口大小。与 client_max_window_bits 相似，但应用于服务器端

## 数据传输
`websocket`协议的数据传输使用一系列的帧，帧是数据传输的最小单位。帧的结构如下：
```bash
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-------+-+-------------+-------------------------------+
|F|R|R|R| opcode|M| Payload len |    Extended payload length    |
|I|S|S|S|  (4)  |A|     (7)     |             (16/64)           |
|N|V|V|V|       |S|             |   (if payload len==126/127)   |
| |1|2|3|       |K|             |                               |
+-+-+-+-+-------+-+-------------+ - - - - - - - - - - - - - - - +
|     Extended payload length continued, if payload len == 127  |
+ - - - - - - - - - - - - - - - +-------------------------------+
|                               |Masking-key, if MASK set to 1  |
+-------------------------------+-------------------------------+
| Masking-key (continued)       |          Payload Data         |
+-------------------------------- - - - - - - - - - - - - - - - +
:                     Payload Data continued ...                :
+ - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - +
|                     Payload Data continued ...                |
+---------------------------------------------------------------+
```
+ `FIN`：指示当前帧是消息的最后一个帧；
+ `RSV 1~3`：用于协议拓展，不使用协议拓展是 0。若接收方收到`RSV 1~3` 不全为 0 的帧， 
并且双方没有协商使用扩展协议，则接收方应立即终止 WebSocket 连接；
+ `opcode`：表示`playload data`的类型，如果收到未知的`opcode`值，则接收方应终止 WebSocket 连接。
`opcode`取值含义如下：
  + `0x0`：表示`continuation frame`。服务器应该将帧的有效负载连接到从该客户机接收到的最后一个帧；
  + `0x1`：表示文本帧；
  + `0x2`：表示二进制帧；
  + `0x3-7`：被保留用于非控制帧；
  + `0x8`：表示连接关闭；
  + `0x9`：表示一个`ping`；
  + `0xA`：表示一个`pong`；
  + `0xB-F`：被保留用于控制帧；
+ `MASK`：是否对`playload data`进行掩码，如果为 1，掩码值在`Masking-key`中。
从客户端发往服务端的帧必须设置为 1；
+ `playload len`：`playload data`的长度；
  + 如果`payload len`值在 0-125 之间，`playload len`使用 7 位表示`playload data`的长度；
  + 如果`playload len`值为 126，表示需要额外的 16 位来表示`payload data`的长度，
  此时后续的 16 位就是`payload data`的实际长度；
  + 如果`playload len`值为 127，表示需要额外的 64 位来表示`payload data`的长度，
  此时后续的 64 位就是`payload data`的实际长度；
+ `Masking-key`：表示掩码的值，32位数据；
+ `playload data`：有效载荷数据；

`websocket`控制帧用于客户端和服务端交互有关`websocket`的状态，控制帧可以在握手之后的任意时刻发送。
控制帧有三种：
+ `close`
+ `ping`
+ `pong`

`websocket`协议支持消息分多帧发送的目的：
+ The primary purpose of fragmentation is to allow sending a message
that is of unknown size when the message is started without having to
buffer that message.  If messages couldn't be fragmented, then an
endpoint would have to buffer the entire message so its length could
be counted before the first byte is sent.  With fragmentation, a
server or intermediary may choose a reasonable size buffer and, when
the buffer is full, write a fragment to the network.
+ A secondary use-case for fragmentation is for multiplexing, where it
is not desirable for a large message on one logical channel to
monopolize the output channel, so the multiplexing needs to be free
to split the message into smaller fragments to better share the
output channel.

# 服务端实现
`websocket`服务端样例代码如下：
```python
from aiohttp import web

async def websocket_handler(request):

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            if msg.data == 'close':
                await ws.close()
            else:
                await ws.send_str(msg.data + '/answer')
        elif msg.type == aiohttp.WSMsgType.ERROR:
            print('ws connection closed with exception %s' %
                  ws.exception())

    print('websocket connection closed')

    return ws

app = web.Application()
app.add_routes([web.get('/ws', websocket_handler)])

if __name__ == '__main__':
    web.run_app(app)
```
`websocket`协议复用`http`协议数据接收，请求解析流程。`websocket`协议本身实现在`WebSocketResponse`中，
`WebSocketResponse`继承`StreamResponse`。
## WebSocketResponse
### 初始化
`WebSocketResponse`初始化源码实现如下：
```python
class WebSocketResponse(StreamResponse):
    def __init__(
        self,
        *,
        timeout: float = 10.0,
        receive_timeout: Optional[float] = None,
        autoclose: bool = True,
        autoping: bool = True,
        heartbeat: Optional[float] = None,
        protocols: Iterable[str] = (),
        compress: bool = True,
        max_msg_size: int = 4 * 1024 * 1024,
    ) -> None:
        # 设置响应码 101，此时没有响应体
        super().__init__(status=101)
        # 由于响应没有响应体数据，不需要 Content-Length 头，也不需要分块传输
        self._length_check = False
        # websocket 服务端支持的子协议集合
        self._protocols = protocols
        # 和客户端协商使用的子协议名，可能为 None
        self._ws_protocol: Optional[str] = None
        # 一个 WebSocketWriter 对象，用于 websocket 数据传输
        self._writer: Optional[WebSocketWriter] = None
        # 一个阻塞队列，存放解析后的 websocket 传输的数据
        self._reader: Optional[FlowControlDataQueue[WSMessage]] = None
        # 表示是否 websocket 关闭，close 方法被调用
        self._closed = False
        self._closing = False
        self._conn_lost = 0
        # 关闭码，查看协议文档了解
        self._close_code: Optional[int] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._waiting: Optional[asyncio.Future[bool]] = None
        self._exception: Optional[BaseException] = None
        self._timeout = timeout
        self._receive_timeout = receive_timeout
        self._autoclose = autoclose
        self._autoping = autoping
        # 心跳包执行的周期时间
        self._heartbeat = heartbeat
        self._heartbeat_cb: Optional[asyncio.TimerHandle] = None
        if heartbeat is not None:
            # pong 响应超时时间
            self._pong_heartbeat = heartbeat / 2.0
        self._pong_response_cb: Optional[asyncio.TimerHandle] = None
        self._compress = compress
        self._max_msg_size = max_msg_size
```
### 握手
`websocket`协议的握手阶段在`prepare`中完成，`prepare`源码如下：
```python
async def prepare(self, request: BaseRequest) -> AbstractStreamWriter:
    # make pre-check to don't hide it by do_handshake() exceptions
    if self._payload_writer is not None:
        return self._payload_writer
    # 完成和客户端的握手
    protocol, writer = self._pre_start(request)
    # 发送响应报文
    payload_writer = await super().prepare(request)
    assert payload_writer is not None
    # 初始化心跳功能设置，定时发送和接收 ping 和 pong 控制帧
    self._post_start(request, protocol, writer)
    # 如果底层写没有暂停，直接返回；如果底层写已经暂停（buffer数据太多），
    # 等待底层写恢复（buffer数据降低水位线之下）
    await payload_writer.drain()
    return payload_writer
```
`prepare`完成如下准备工作：
+ 和客户端握手；
+ 握手完成后发送响应报文；
+ 初始化心跳功能设置，定时发送和接收 ping 和 pong 控制帧，以用于检查连接是否还在；

握手操作在`self._pre_start`中实现，具体源码如下：
```python
def _pre_start(self, request: BaseRequest) -> Tuple[str, WebSocketWriter]:
    self._loop = request._loop
    # 握手
    headers, protocol, compress, notakeover = self._handshake(request)
    # 设置响应码 101
    self.set_status(101)
    # 设置响应头
    self.headers.update(headers)
    # 设置 keep-alive = False
    self.force_close()
    # 数据压缩窗口的大小
    self._compress = compress
    transport = request._protocol.transport
    assert transport is not None
    # 初始化一个 WebSocketWriter 对象，用于后续的数据帧和控制帧传输
    writer = WebSocketWriter(
        request._protocol, transport, compress=compress, notakeover=notakeover
    )

    return protocol, writer
```
在`_pre_start`中首先完成握手动作，然后会初始化一个`WebSocketWriter`对象用于后续的帧数据发送，
`WebSocketWriter`对象详细介绍在下小节。这里看下握手的具体实现，`self._handshake`源码如下：
```python
def _handshake(
    self, request: BaseRequest
) -> Tuple["CIMultiDict[str]", str, bool, bool]:
    headers = request.headers
    if "websocket" != headers.get(hdrs.UPGRADE, "").lower().strip():
        raise HTTPBadRequest(
            text=(
                "No WebSocket UPGRADE hdr: {}\n Can "
                '"Upgrade" only to "WebSocket".'
            ).format(headers.get(hdrs.UPGRADE))
        )

    if "upgrade" not in headers.get(hdrs.CONNECTION, "").lower():
        raise HTTPBadRequest(
            text="No CONNECTION upgrade hdr: {}".format(
                headers.get(hdrs.CONNECTION)
            )
        )

    # find common sub-protocol between client and server
    protocol = None
    if hdrs.SEC_WEBSOCKET_PROTOCOL in headers:
        req_protocols = [
            str(proto.strip())
            for proto in headers[hdrs.SEC_WEBSOCKET_PROTOCOL].split(",")
        ]

        for proto in req_protocols:
            if proto in self._protocols:
                protocol = proto
                break
        else:
            # No overlap found: Return no protocol as per spec
            ws_logger.warning(
                "Client protocols %r don’t overlap server-known ones %r",
                req_protocols,
                self._protocols,
            )

    # check supported version
    version = headers.get(hdrs.SEC_WEBSOCKET_VERSION, "")
    if version not in ("13", "8", "7"):
        raise HTTPBadRequest(text=f"Unsupported version: {version}")

    # check client handshake for validity
    key = headers.get(hdrs.SEC_WEBSOCKET_KEY)
    try:
        if not key or len(base64.b64decode(key)) != 16:
            raise HTTPBadRequest(text=f"Handshake error: {key!r}")
    except binascii.Error:
        raise HTTPBadRequest(text=f"Handshake error: {key!r}") from None

    accept_val = base64.b64encode(
        hashlib.sha1(key.encode() + WS_KEY).digest()
    ).decode()
    response_headers = CIMultiDict(
        {
            hdrs.UPGRADE: "websocket",
            hdrs.CONNECTION: "upgrade",
            hdrs.SEC_WEBSOCKET_ACCEPT: accept_val,
        }
    )

    notakeover = False
    compress = 0
    if self._compress:
        extensions = headers.get(hdrs.SEC_WEBSOCKET_EXTENSIONS)
        # Server side always get return with no exception.
        # If something happened, just drop compress extension
        # compress 表示压缩使用的窗口大小
        # notakeover 表示是否保留压缩上下文
        compress, notakeover = ws_ext_parse(extensions, isserver=True)
        if compress:
            enabledext = ws_ext_gen(
                compress=compress, isserver=True, server_notakeover=notakeover
            )
            response_headers[hdrs.SEC_WEBSOCKET_EXTENSIONS] = enabledext

    if protocol:
        response_headers[hdrs.SEC_WEBSOCKET_PROTOCOL] = protocol
    return (
        response_headers, # 一个字典对象，websocket 响应头
        protocol,  # 字符串，表示和客户端协商使用子协议，没有就是 None
        compress,  # 压缩窗口大小
        notakeover, # bool 值，表示数据传输中是否使用压缩上下文
    )  # type: ignore[return-value]
```
握手操作主要完成以下工作：
+ 检查请求报文的请求头中必须有`Upgrade: websocket`和`Connection: Upgrade`；
+ 协商和客户端使用的子协议。如果客户端指定了`Sec-WebSocket-Protocol`头，
服务器可以选择其中一个协议与客户端进行通信，如果服务端没有符合的子协议，返回 None；
+ 验证客户端指定的协议版本`Sec-WebSocket-Version`值必须在`("13", "8", "7")`中；
+ 服务端检查客户端指定的`Sec-WebSocket-Key`是否有效，并计算要响应给客户端的`Sec-WebSocket-Accept`值；
+ 解析客户端指定的`Sec-WebSocket-Extensions`值；

下面看下在`prepare`中完成握手以及响应报文发送后执行的`_post_start`方法，其源码如下：
```python
def _post_start(
    self, request: BaseRequest, protocol: str, writer: WebSocketWriter
) -> None:
    # 和客户端协商使用的子协议，可能为 None
    self._ws_protocol = protocol
    # 一个 WebSocketWriter 对象，用于后续帧发送
    self._writer = writer

    self._reset_heartbeat()

    loop = self._loop
    assert loop is not None
    # 一个阻塞队列
    self._reader = FlowControlDataQueue(request._protocol, 2**16, loop=loop)
    # 更新协议使用的负载解析对象，也就是解析收到的 websocket 帧数据
    request.protocol.set_parser(
        WebSocketReader(self._reader, self._max_msg_size, compress=self._compress)
    )
    # disable HTTP keepalive for WebSocket
    # 因为 websocket 何时关闭是由开发者决定
    request.protocol.keep_alive(False)
```
`_post_start`主要完成两个工作：
+ 调用`_reset_heartbeat`方法，初始化心跳包功能设置，用于检查连接是否存在；
+ 设置底层协议使用的负载解析对象`WebSocketReader`，用于解析帧数据；

`_reset_heartbeat`相关源码实现如下：
```python
def _reset_heartbeat(self) -> None:
    self._cancel_heartbeat()
    # 必须设置心跳包周期时间
    if self._heartbeat is not None:
        assert self._loop is not None
        self._heartbeat_cb = call_later(
            self._send_heartbeat,
            self._heartbeat,
            self._loop,
            timeout_ceil_threshold=(
                self._req._protocol._timeout_ceil_threshold
                if self._req is not None
                else 5
            ),
        )

def _cancel_heartbeat(self) -> None:
    if self._pong_response_cb is not None:
        self._pong_response_cb.cancel()
        self._pong_response_cb = None

    if self._heartbeat_cb is not None:
        self._heartbeat_cb.cancel()
        self._heartbeat_cb = None

def _send_heartbeat(self) -> None:
    if self._heartbeat is not None and not self._closed:
        assert self._loop is not None and self._writer is not None
        # fire-and-forget a task is not perfect but maybe ok for
        # sending ping. Otherwise we need a long-living heartbeat
        # task in the class.
        self._loop.create_task(self._writer.ping())  # type: ignore[unused-awaitable]

        if self._pong_response_cb is not None:
            self._pong_response_cb.cancel()
        self._pong_response_cb = call_later(
            self._pong_not_received,
            self._pong_heartbeat,
            self._loop,
            timeout_ceil_threshold=(
                self._req._protocol._timeout_ceil_threshold
                if self._req is not None
                else 5
            ),
        )

def _pong_not_received(self) -> None:
    if self._req is not None and self._req.transport is not None:
        self._closed = True
        self._set_code_close_transport(WSCloseCode.ABNORMAL_CLOSURE)
        self._exception = asyncio.TimeoutError()

def _set_code_close_transport(self, code: WSCloseCode) -> None:
    """Set the close code and close the transport."""
    self._close_code = code
    self._close_transport()

def _close_transport(self) -> None:
    """Close the transport."""
    if self._req is not None and self._req.transport is not None:
        self._req.transport.close()
# helper.py 中实现
def call_later(
    cb: Callable[[], Any],
    timeout: Optional[float],
    loop: asyncio.AbstractEventLoop,
    timeout_ceil_threshold: float = 5,
) -> Optional[asyncio.TimerHandle]:
    if timeout is not None and timeout > 0:
        when = loop.time() + timeout
        if timeout > timeout_ceil_threshold:
            when = ceil(when)
        return loop.call_at(when, cb)
    return None
```
`_reset_heartbeat`主要完成以下工作：
+ 创建一个定时执行发送`ping`控制帧的任务；
+ 创建一个定时接收`pong`控制帧的任务，如果超时没有`pong`帧，则关闭`websocket`；

> 在下面数据传输将介绍的`receive`中，如果接收到帧（不管是数据帧还是控制帧）都会调用
`_reset_heartbeat`重置心跳包功能。

### 数据传输
数据传输分为**发送**和**接收**两部分。

**发送**：
+ `ping`
  ```python
  async def ping(self, message: bytes = b"") -> None:
      if self._writer is None:
          raise RuntimeError("Call .prepare() first")
      await self._writer.ping(message)
  ```
+ `pong`
  ```python
  async def pong(self, message: bytes = b"") -> None:
      # unsolicited pong
      if self._writer is None:
          raise RuntimeError("Call .prepare() first")
      await self._writer.pong(message)
  ```
+ `send_str`
  ```python
  async def send_str(self, data: str, compress: Optional[bool] = None) -> None:
      if self._writer is None:
          raise RuntimeError("Call .prepare() first")
      if not isinstance(data, str):
          raise TypeError("data argument must be str (%r)" % type(data))
      await self._writer.send(data, binary=False, compress=compress)
  ```
+ `send_bytes`
  ```python
  async def send_bytes(self, data: bytes, compress: Optional[bool] = None) -> None:
      if self._writer is None:
          raise RuntimeError("Call .prepare() first")
      if not isinstance(data, (bytes, bytearray, memoryview)):
          raise TypeError("data argument must be byte-ish (%r)" % type(data))
      await self._writer.send(data, binary=True, compress=compress)
  ```
+ `send_json`
  ```python
  async def send_json(
      self,
      data: Any,
      compress: Optional[bool] = None,
      *,
      dumps: JSONEncoder = json.dumps,
  ) -> None:
      await self.send_str(dumps(data), compress=compress)
  ```
+ `close`
  ```python
  async def close(
      self, *, code: int = WSCloseCode.OK, message: bytes = b"", drain: bool = True
  ) -> bool:
      """Close websocket connection."""
      if self._writer is None:
          raise RuntimeError("Call .prepare() first")
      # 关闭心跳包
      self._cancel_heartbeat()
      reader = self._reader
      assert reader is not None

      # we need to break `receive()` cycle first,
      # `close()` may be called from different task
      if self._waiting is not None and not self._closed:
          # WS_CLOSING_MESSAGE = WSMessage(WSMsgType.CLOSING, None, None)
          # receive 接收到 WSMsgType.CLOSING 消息会退出
          reader.feed_data(WS_CLOSING_MESSAGE, 0)
          # 等待 receive 退出
          await self._waiting

      if self._closed:
          return False

      self._closed = True
      try:
          # 发送 close 帧，关闭握手
          await self._writer.close(code, message)
          writer = self._payload_writer
          assert writer is not None
          if drain:
              await writer.drain()
      except (asyncio.CancelledError, asyncio.TimeoutError):
          self._set_code_close_transport(WSCloseCode.ABNORMAL_CLOSURE)
          raise
      except Exception as exc:
          self._exception = exc
          self._set_code_close_transport(WSCloseCode.ABNORMAL_CLOSURE)
          return True
      # 需要关闭
      if self._closing:
          self._close_transport()
          return True

      reader = self._reader
      assert reader is not None
      try:
          # 等待读对方的 close 帧
          async with async_timeout.timeout(self._timeout):
              msg = await reader.read()
      except asyncio.CancelledError:
          self._set_code_close_transport(WSCloseCode.ABNORMAL_CLOSURE)
          raise
      except Exception as exc:
          self._exception = exc
          self._set_code_close_transport(WSCloseCode.ABNORMAL_CLOSURE)
          return True

      if msg.type == WSMsgType.CLOSE:
          self._set_code_close_transport(msg.data)
          return True

      self._set_code_close_transport(WSCloseCode.ABNORMAL_CLOSURE)
      self._exception = asyncio.TimeoutError()
      return True

  def _set_code_close_transport(self, code: WSCloseCode) -> None:
      """Set the close code and close the transport."""
      self._close_code = code
      self._close_transport()

  def _close_transport(self) -> None:
      """Close the transport."""
      if self._req is not None and self._req.transport is not None:
          self._req.transport.close()
  ```
  `close`工作流程如下：
  + 取消心跳包；
  + 如果`receive`在等待中，发送`WSMsgType.CLOSING`消息，并等待`receive`退出；
  + 发送 close 帧，关闭握手；
  + 关闭底层的 transport；

**接收**：
+ `receive`
  ```python
  async def receive(self, timeout: Optional[float] = None) -> WSMessage:
      if self._reader is None:
          raise RuntimeError("Call .prepare() first")

      loop = self._loop
      assert loop is not None
      while True:
          if self._waiting is not None:
              raise RuntimeError("Concurrent call to receive() is not allowed")
          # close() 被调用，发送 close 帧关闭握手
          if self._closed:
              self._conn_lost += 1
              if self._conn_lost >= THRESHOLD_CONNLOST_ACCESS:
                  raise RuntimeError("WebSocket connection is closed.")
              return WS_CLOSED_MESSAGE
          # 准备关闭
          elif self._closing:
              return WS_CLOSING_MESSAGE

          try:
              # 从缓存读消息
              self._waiting = loop.create_future()
              try:
                  async with async_timeout.timeout(timeout or self._receive_timeout):
                      msg = await self._reader.read()
                  # 有消息，说明连接正常，重置心跳包
                  self._reset_heartbeat()
              finally:
                  waiter = self._waiting
                  set_result(waiter, True)
                  self._waiting = None
          except asyncio.TimeoutError:
              raise
          except EofStream:
              # 缓存没数据，且读已经结束
              self._close_code = WSCloseCode.OK
              await self.close()
              return WSMessage(WSMsgType.CLOSED, None, None)
          except WebSocketError as exc:
              self._close_code = exc.code
              await self.close(code=exc.code)
              return WSMessage(WSMsgType.ERROR, exc, None)
          except Exception as exc:
              self._exception = exc
              self._set_closing(WSCloseCode.ABNORMAL_CLOSURE)
              await self.close()
              return WSMessage(WSMsgType.ERROR, exc, None)

          if msg.type == WSMsgType.CLOSE:
              self._set_closing(msg.data)
              # Could be closed while awaiting reader.
              if not self._closed and self._autoclose:  # type: ignore[redundant-expr]
                  # The client is likely going to close the
                  # connection out from under us so we do not
                  # want to drain any pending writes as it will
                  # likely result writing to a broken pipe.
                  await self.close(drain=False)
          elif msg.type == WSMsgType.CLOSING:
              self._set_closing(WSCloseCode.OK)
          # 收到 ping 需要回复一个 pong
          elif msg.type == WSMsgType.PING and self._autoping:
              await self.pong(msg.data)
              continue
          # 收到 pong，不做任何处理
          elif msg.type == WSMsgType.PONG and self._autoping:
              continue

          return msg

  def _set_closing(self, code: WSCloseCode) -> None:
      """Set the close code and mark the connection as closing."""
      self._closing = True
      self._close_code = code
  ```
  `receive`用于获取数据帧消息，否则会一直循环运行等待。

+ `receive_str`
  ```python
  async def receive_str(self, *, timeout: Optional[float] = None) -> str:
      msg = await self.receive(timeout)
      if msg.type != WSMsgType.TEXT:
          raise TypeError(
              "Received message {}:{!r} is not WSMsgType.TEXT".format(
                  msg.type, msg.data
              )
          )
      return cast(str, msg.data)
  ```
+ `receive_bytes`
  ```python
  async def receive_bytes(self, *, timeout: Optional[float] = None) -> bytes:
      msg = await self.receive(timeout)
      if msg.type != WSMsgType.BINARY:
          raise TypeError(f"Received message {msg.type}:{msg.data!r} is not bytes")
      return cast(bytes, msg.data)
  ```
+ `receive_json`
  ```python
  async def receive_json(
      self, *, loads: JSONDecoder = json.loads, timeout: Optional[float] = None
  ) -> Any:
      data = await self.receive_str(timeout=timeout)
      return loads(data)
  ```
`WebSocketResponse`也支持异步迭代器，用于获取消息，源码如下：
```python
def __aiter__(self) -> "WebSocketResponse":
    return self

async def __anext__(self) -> WSMessage:
    msg = await self.receive()
    if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
        raise StopAsyncIteration
    return msg
```


## WebSocketReader
`WebSocketReader`用于`websocket`协议帧的解析，承担负载解析`_payload_parser`角色。
### 初始化
`WebSocketReader`初始化源码如下：
```python
class WebSocketReader:
    def __init__(
        self, queue: DataQueue[WSMessage], max_msg_size: int, compress: bool = True
    ) -> None:
        # 用于流式读传输数据的缓存队列
        self.queue = queue
        # websocket 协议发送的消息体最大值
        self._max_msg_size = max_msg_size
        # 帧解析过程中抛出的异常
        self._exc: Optional[BaseException] = None
        # 存放帧数据，一个消息可能分多个帧传输
        self._partial = bytearray()
        # 帧解析的中间状态：
        # READ_HEADER/READ_PAYLOAD_LENGTH/READ_PAYLOAD_MASK/READ_PAYLOAD
        self._state = WSParserState.READ_HEADER

        self._opcode: Optional[int] = None
        # 当前帧的 FIN 值
        self._frame_fin = False
        # 当前帧的 opcode 值
        self._frame_opcode: Optional[int] = None
        # 当前帧有效数据
        self._frame_payload = bytearray()

        self._tail = b""
        self._has_mask = False
        # 当前帧掩码值
        self._frame_mask: Optional[bytes] = None
        # 未解析有效负载长度，当前帧有效负载长度都解析完，设置为 0
        self._payload_length = 0
        # < 125 或者 126 或者 127
        self._payload_length_flag = 0
        # 下面用于解压缩
        self._compressed: Optional[bool] = None
        self._decompressobj: Optional[ZLibDecompressor] = None
        # 压缩窗口大小
        self._compress = compress
```
其中`queue`属性是个`FlowControlDataQueue`对象，相关源码如下：
```python
class FlowControlDataQueue(DataQueue[_T]):
    """FlowControlDataQueue resumes and pauses an underlying stream.

    It is a destination for parsed data.
    """

    def __init__(
        self, protocol: BaseProtocol, limit: int, *, loop: asyncio.AbstractEventLoop
    ) -> None:
        super().__init__(loop=loop)
        # 协议对象，这里是 RequestHandler
        self._protocol = protocol
        # 缓存队列的上限
        self._limit = limit * 2
    
    def feed_data(self, data: _T, size: int = 0) -> None:
        super().feed_data(data, size)

        if self._size > self._limit and not self._protocol._reading_paused:
            # 缓存数据超过上限，暂定底层协议读
            self._protocol.pause_reading()

    async def read(self) -> _T:
        try:
            return await super().read()
        finally:
            if self._size < self._limit and self._protocol._reading_paused:
                # 缓存数据低于下限，恢复底层协议读
                self._protocol.resume_reading()
```
`FlowControlDataQueue`继承`DataQueue`，`FlowControlDataQueue`相对`DataQueue`的`feed_data`和`read`方法增加了读速率控制：
如果缓存中的数据大小超过上限，则暂停协议的读操作；如果缓存中的数据大小没有达到上限，
则恢复协程的读操作。

`DataQueue`源码如下：
```python
class DataQueue(Generic[_T]):
    """DataQueue is a general-purpose blocking queue with one reader."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        # 表示是否读结束
        self._eof = False
        # 用于同步读，如果缓存没数据，read 操作会阻塞直到缓存有数据
        self._waiter: Optional[asyncio.Future[None]] = None
        self._exception: Optional[BaseException] = None
        # 缓存的大小
        self._size = 0
        # 缓存数据
        self._buffer: Deque[Tuple[_T, int]] = collections.deque()

    def __len__(self) -> int:
        return len(self._buffer)

    def is_eof(self) -> bool:
        return self._eof

    def at_eof(self) -> bool:
        return self._eof and not self._buffer

    def exception(self) -> Optional[BaseException]:
        return self._exception

    def set_exception(
        self,
        exc: BaseException,
        exc_cause: BaseException = _EXC_SENTINEL,
    ) -> None:
        self._eof = True
        self._exception = exc

        waiter = self._waiter
        if waiter is not None:
            self._waiter = None
            set_exception(waiter, exc, exc_cause)

    def feed_data(self, data: _T, size: int = 0) -> None:
        # 更新缓存大小
        self._size += size
        # 将数据存到缓存中，用于后续的读操作，存放 (data, size) 元组
        self._buffer.append((data, size))
        # 通知数据可读
        waiter = self._waiter
        if waiter is not None:
            self._waiter = None
            set_result(waiter, None)

    def feed_eof(self) -> None:
        # 设置读结束标志
        self._eof = True
        # 通知数据可读
        waiter = self._waiter
        if waiter is not None:
            self._waiter = None
            set_result(waiter, None)

    async def read(self) -> _T:
        # 缓存没数据，且读没结束，则等待直到缓存有数据
        if not self._buffer and not self._eof:
            assert not self._waiter
            self._waiter = self._loop.create_future()
            try:
                await self._waiter
            except (asyncio.CancelledError, asyncio.TimeoutError):
                self._waiter = None
                raise
        # 如果缓存有数据，取一个 (data, size) 元组对象
        if self._buffer:
            data, size = self._buffer.popleft()
            # 更新缓存大小
            self._size -= size
            return data
        # 缓存没数据，且读已经结束，抛出异常
        else:
            if self._exception is not None:
                raise self._exception
            else:
                raise EofStream

    def __aiter__(self) -> AsyncStreamIterator[_T]:
        return AsyncStreamIterator(self.read)
```
`DataQueue`往缓存写数据涉及`feed_data`和`feed_eof`方法，`feed_eof`方法在连接丢失的时候会被调用。
从缓存取数据涉及`read`方法。详细可看代码注释。

### 数据解析
`WebSocketReader`解析传输的帧数据源码实现如下：
```python
def feed_eof(self) -> None:
    # 通知底层缓存对象读结束
    self.queue.feed_eof()

def feed_data(self, data: bytes) -> Tuple[bool, bytes]:
    if self._exc:
        # 上次帧解析已经抛出异常，直接返回
        return True, data

    try:
        return self._feed_data(data)
    except Exception as exc:
        # 设置帧解析异常，并将异常传递给底层的缓存 queue 对象
        self._exc = exc
        set_exception(self.queue, exc)
        return True, b""
```
`feed_data`返回结果中的`True`表示当前请求已经结束，应该关闭连接。`feed_eof`在连接关闭时会被调用。
`feed_data`将帧解析工作交给`_feed_data`方法，其相关源码如下：
```python
def _feed_data(self, data: bytes) -> Tuple[bool, bytes]:
    for fin, opcode, payload, compressed in self.parse_frame(data):
        # 如果数据传输使用压缩，设置解压缩对象
        if compressed and not self._decompressobj:
            self._decompressobj = ZLibDecompressor(suppress_deflate_header=True)
        # 收到的帧是关闭帧
        if opcode == WSMsgType.CLOSE:
            if len(payload) >= 2:
                # 读状态码
                close_code = UNPACK_CLOSE_CODE(payload[:2])[0]
                if close_code < 3000 and close_code not in ALLOWED_CLOSE_CODES:
                    raise WebSocketError(
                        WSCloseCode.PROTOCOL_ERROR,
                        f"Invalid close code: {close_code}",
                    )
                try:
                    # 读 close 信息说明
                    close_message = payload[2:].decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise WebSocketError(
                        WSCloseCode.INVALID_TEXT, "Invalid UTF-8 text message"
                    ) from exc
                msg = WSMessage(WSMsgType.CLOSE, close_code, close_message)
            elif payload:
                raise WebSocketError(
                    WSCloseCode.PROTOCOL_ERROR,
                    f"Invalid close frame: {fin} {opcode} {payload!r}",
                )
            else:
                msg = WSMessage(WSMsgType.CLOSE, 0, "")
            # 解析结果信息写到缓存中，用于后续的读
            self.queue.feed_data(msg, 0)
        # 收到的帧是 ping 帧
        elif opcode == WSMsgType.PING:
            self.queue.feed_data(
                WSMessage(WSMsgType.PING, payload, ""), len(payload)
            )
        # 收到的帧是 pong 帧
        elif opcode == WSMsgType.PONG:
            self.queue.feed_data(
                WSMessage(WSMsgType.PONG, payload, ""), len(payload)
            )

        elif (
            opcode not in (WSMsgType.TEXT, WSMsgType.BINARY)
            and self._opcode is None
        ):
            # self._opcode = None，表示是第一帧数据
            # 数据帧的第一帧的 opcode 值不能是 0 或者保留值
            raise WebSocketError(
                WSCloseCode.PROTOCOL_ERROR, f"Unexpected opcode={opcode!r}"
            )
        # 数据帧
        else:
            # load text/binary
            # 不是消息的最后一帧
            if not fin:
                # got partial frame payload
                if opcode != WSMsgType.CONTINUATION:
                    self._opcode = opcode
                self._partial.extend(payload)
                if self._max_msg_size and len(self._partial) >= self._max_msg_size:
                    raise WebSocketError(
                        WSCloseCode.MESSAGE_TOO_BIG,
                        "Message size {} exceeds limit {}".format(
                            len(self._partial), self._max_msg_size
                        ),
                    )
            # 消息的最后一帧
            else:
                # previous frame was non finished
                # we should get continuation opcode
                # 对于消息分多个帧传输，除了第一帧 opcode 不是 0
                # 其他帧的 opcode 必须是 0
                if self._partial:
                    if opcode != WSMsgType.CONTINUATION:
                        raise WebSocketError(
                            WSCloseCode.PROTOCOL_ERROR,
                            "The opcode in non-fin frame is expected "
                            "to be zero, got {!r}".format(opcode),
                        )

                if opcode == WSMsgType.CONTINUATION:
                    assert self._opcode is not None
                    # 更新为实际有意义的数据类型对应的值，对于多帧传出，
                    # 有意义的 opcode 值在第一帧中，因为非第一帧都是 0
                    opcode = self._opcode
                    self._opcode = None

                self._partial.extend(payload)
                if self._max_msg_size and len(self._partial) >= self._max_msg_size:
                    raise WebSocketError(
                        WSCloseCode.MESSAGE_TOO_BIG,
                        "Message size {} exceeds limit {}".format(
                            len(self._partial), self._max_msg_size
                        ),
                    )

                # Decompress process must to be done after all packets
                # received.
                # 如果数据是压缩传输，需要解压缩
                if compressed:
                    assert self._decompressobj is not None
                    self._partial.extend(_WS_DEFLATE_TRAILING)
                    payload_merged = self._decompressobj.decompress_sync(
                        self._partial, self._max_msg_size
                    )
                    if self._decompressobj.unconsumed_tail:
                        left = len(self._decompressobj.unconsumed_tail)
                        raise WebSocketError(
                            WSCloseCode.MESSAGE_TOO_BIG,
                            "Decompressed message size {} exceeds limit {}".format(
                                self._max_msg_size + left, self._max_msg_size
                            ),
                        )
                else:
                    payload_merged = bytes(self._partial)

                self._partial.clear()
                # 文本数据写到缓存中
                if opcode == WSMsgType.TEXT:
                    try:
                        text = payload_merged.decode("utf-8")
                        self.queue.feed_data(
                            WSMessage(WSMsgType.TEXT, text, ""), len(text)
                        )
                    except UnicodeDecodeError as exc:
                        raise WebSocketError(
                            WSCloseCode.INVALID_TEXT, "Invalid UTF-8 text message"
                        ) from exc
                # 二进制数据写到缓存
                else:
                    self.queue.feed_data(
                        WSMessage(WSMsgType.BINARY, payload_merged, ""),
                        len(payload_merged),
                    )

    return False, b""
```
`_feed_data`首先会调用`self.parse_frame`解析当前帧数据，根据`self.parse_frame`的解析结果，
判断当前帧是控制帧还是数据帧，进而将解析后的数据写到缓存中。帧解析`self.parse_frame`方法的源码如下：
```python
def parse_frame(
    self, buf: bytes
) -> List[Tuple[bool, Optional[int], bytearray, Optional[bool]]]:
    """Return the next frame from the socket."""
    # 存放帧解析结果
    frames = []
    # 将上次未解析的数据（不是一个完整的帧数据）添加前面，用于解析
    if self._tail:
        buf, self._tail = self._tail + buf, b""

    start_pos = 0
    # 当前socket接收读到的数据大小
    buf_length = len(buf)

    while True:
        # read header
        # WSParserState.READ_HEADER 是初始状态
        if self._state == WSParserState.READ_HEADER:
            # 根据原理部分介绍的帧数据结构，前两个字节(16)表示
            # FIN, RSV1-3, opcode, MASK, payload len 等信息
            if buf_length - start_pos >= 2:
                # 获取前 16 bit，也就是帧头信息，用于解析
                data = buf[start_pos : start_pos + 2]
                # 更新解析位置到第三个字节开始处，也就是第 16 位（0开始算）
                start_pos += 2
                first_byte, second_byte = data

                fin = (first_byte >> 7) & 1
                rsv1 = (first_byte >> 6) & 1
                rsv2 = (first_byte >> 5) & 1
                rsv3 = (first_byte >> 4) & 1
                opcode = first_byte & 0xF

                # frame-fin = %x0 ; more frames of this message follow
                #           / %x1 ; final frame of this message
                # frame-rsv1 = %x0 ;
                #    1 bit, MUST be 0 unless negotiated otherwise
                # frame-rsv2 = %x0 ;
                #    1 bit, MUST be 0 unless negotiated otherwise
                # frame-rsv3 = %x0 ;
                #    1 bit, MUST be 0 unless negotiated otherwise
                #
                # Remove rsv1 from this test for deflate development
                # 拓展只支持压缩，rsv1 为 1，则必须协商了数据传输压缩
                # rsv2 和 rsv3 必须为 0
                if rsv2 or rsv3 or (rsv1 and not self._compress):
                    raise WebSocketError(
                        WSCloseCode.PROTOCOL_ERROR,
                        "Received frame with non-zero reserved bits",
                    )
                # 控制帧 FIN 必须是 1，因为控制帧不会分多帧发送
                if opcode > 0x7 and fin == 0:
                    raise WebSocketError(
                        WSCloseCode.PROTOCOL_ERROR,
                        "Received fragmented control frame",
                    )
                # 读掩码标志位
                has_mask = (second_byte >> 7) & 1
                # 读负载数据长度
                length = second_byte & 0x7F

                # Control frames MUST have a payload
                # length of 125 bytes or less
                if opcode > 0x7 and length > 125:
                    raise WebSocketError(
                        WSCloseCode.PROTOCOL_ERROR,
                        "Control frame payload cannot be " "larger than 125 bytes",
                    )

                # Set compress status if last package is FIN
                # OR set compress status if this is first fragment
                # Raise error if not first fragment with rsv1 = 0x1
                if self._frame_fin or self._compressed is None:
                    # 如果是最后一帧（FIN=1）或者 是第一帧（self._compressed 
                    # 初始化值是 None）设置数据传输是否使用压缩
                    self._compressed = True if rsv1 else False
                elif rsv1:
                    raise WebSocketError(
                        WSCloseCode.PROTOCOL_ERROR,
                        "Received frame with non-zero reserved bits",
                    )

                self._frame_fin = bool(fin)
                self._frame_opcode = opcode
                self._has_mask = bool(has_mask)
                self._payload_length_flag = length
                # 帧解析流转下一状态
                self._state = WSParserState.READ_PAYLOAD_LENGTH
            else:
                # 帧头不全，什么都不做，直接返回，等待下次调用解析
                break

        # read payload length
        if self._state == WSParserState.READ_PAYLOAD_LENGTH:
            length = self._payload_length_flag
            # 126 表示接下来的 16 bit（2个字节）是有效数据负载长度
            if length == 126:
                if buf_length - start_pos >= 2:
                    data = buf[start_pos : start_pos + 2]
                    start_pos += 2
                    length = UNPACK_LEN2(data)[0]
                    # 更新有效负载大小
                    self._payload_length = length
                    # 帧解析流转下一状态
                    self._state = (
                        WSParserState.READ_PAYLOAD_MASK
                        if self._has_mask
                        else WSParserState.READ_PAYLOAD
                    )
                else:
                    # 不全，直接返回，等待下次调用解析
                    break
            # 127 表示接下来 64 bit （8个字节）是有效数据负载长度
            elif length > 126:
                if buf_length - start_pos >= 8:
                    data = buf[start_pos : start_pos + 8]
                    start_pos += 8
                    length = UNPACK_LEN3(data)[0]
                    # 更新有效负载大小
                    self._payload_length = length
                    # 帧解析流转下一状态
                    self._state = (
                        WSParserState.READ_PAYLOAD_MASK
                        if self._has_mask
                        else WSParserState.READ_PAYLOAD
                    )
                else:
                    # 不全，直接返回，等待下次调用解析
                    break
            else:
                self._payload_length = length
                self._state = (
                    WSParserState.READ_PAYLOAD_MASK
                    if self._has_mask
                    else WSParserState.READ_PAYLOAD
                )

        # read payload mask
        # 如果当前帧有掩码，则接下来 4 个字节表示掩码值
        if self._state == WSParserState.READ_PAYLOAD_MASK:
            if buf_length - start_pos >= 4:
                # 读取掩码值，一个字节对象
                self._frame_mask = buf[start_pos : start_pos + 4]
                start_pos += 4
                self._state = WSParserState.READ_PAYLOAD
            else:
                # 不全，直接返回，等待下次调用解析
                break
        # 读有效负载数据
        if self._state == WSParserState.READ_PAYLOAD:
            length = self._payload_length
            payload = self._frame_payload

            chunk_len = buf_length - start_pos
            # 负载数据没有接收完
            if length >= chunk_len:
                # 更新未解析的负载长度
                self._payload_length = length - chunk_len
                payload.extend(buf[start_pos:])
                start_pos = buf_length
            # 当前接收数据包含下一帧数据
            else:
                # 未解析负载长度位置设置 0，表示当前帧所有负载数据都已经解析
                self._payload_length = 0
                payload.extend(buf[start_pos : start_pos + length])
                start_pos = start_pos + length
            # 未解析负载长度位置 0，表示当前帧所有负载数据都已经解析
            if self._payload_length == 0:
                if self._has_mask:
                    assert self._frame_mask is not None
                    # 处理掩码情况，获取真实数据
                    _websocket_mask(self._frame_mask, payload)

                frames.append(
                    (self._frame_fin, self._frame_opcode, payload, self._compressed)
                )
                # 恢复初始状态，准备解析下一帧
                self._frame_payload = bytearray()
                self._state = WSParserState.READ_HEADER
            else:
                # 当前帧为解析完，等待下次调用继续解析
                break
    # 记录当前未解析数据，用于下次解析
    self._tail = buf[start_pos:]

    return frames
```
`self.parse_frame`解析帧数据，主要分为如下几步：
+ 解析帧头；
+ 解析有效负载大小；
+ 解析掩码；
+ 解析有效负载数据；

`self.parse_frame`解析结果返回一个列表`frames`，每一个元素的含义如下：
+ `frames[0]`：FIN 值，表示是否是消息的最后一帧；
+ `frames[1]`：opcode值，表示当前帧的数据类型；
+ `frames[2]`：payload，有效负载数据，字节对象；
+ `frames[3]`：表示数据传输是否使用压缩；

## WebSocketWriter
`WebSocketWriter`用于流式发送帧数据，本质上是调用底层`transport`的写方法`write`。
### 初始化
`WebSocketWriter`初始化源码实现如下：
```python
class WebSocketWriter:
    def __init__(
        self,
        protocol: BaseProtocol,
        transport: asyncio.Transport,
        *,
        use_mask: bool = False,
        limit: int = DEFAULT_LIMIT,
        random: random.Random = random.Random(),
        compress: int = 0,
        notakeover: bool = False,
    ) -> None:
        self.protocol = protocol
        self.transport = transport
        # 发送的帧是否使用掩码
        self.use_mask = use_mask
        self.randrange = random.randrange
        # 压缩窗口大小
        self.compress = compress
        # 数据传输压缩是否使用上下文
        self.notakeover = notakeover
        self._closing = False
        # 已发送数据大小上限，控制写的速率
        self._limit = limit
        # 记录已发送数据大小(其实数据写到底层 buffer 大小)
        self._output_size = 0
        self._compressobj: Any = None  # actually compressobj
```
### 数据发送
数据发送涉及四个方法：`ping`、`pong`，`close`和`send`，其内部都是调用`_send_frame`，
`_send_frame`的源码如下：
```python
async def _send_frame(
    self, message: bytes, opcode: int, compress: Optional[int] = None
) -> None:
    """Send a frame over the websocket with message as its payload."""
    if self._closing and not (opcode & WSMsgType.CLOSE):
        raise ConnectionResetError("Cannot write to closing transport")

    rsv = 0

    # Only compress larger packets (disabled)
    # Does small packet needs to be compressed?
    # if self.compress and opcode < 8 and len(message) > 124:
    # opcode < 8 表示数据帧
    if (compress or self.compress) and opcode < 8:
        if compress:
            # Do not set self._compress if compressing is for this frame
            compressobj = self._make_compress_obj(compress)
        else:  # self.compress
            if not self._compressobj:
                self._compressobj = self._make_compress_obj(self.compress)
            compressobj = self._compressobj

        message = await compressobj.compress(message)
        # Its critical that we do not return control to the event
        # loop until we have finished sending all the compressed
        # data. Otherwise we could end up mixing compressed frames
        # if there are multiple coroutines compressing data.
        message += compressobj.flush(
            zlib.Z_FULL_FLUSH if self.notakeover else zlib.Z_SYNC_FLUSH
        )
        if message.endswith(_WS_DEFLATE_TRAILING):
            message = message[:-4]
        rsv = rsv | 0x40
    # 要发送帧负载长度（如果有压缩，表示压缩后的长度）
    msg_length = len(message)

    use_mask = self.use_mask
    if use_mask:
        mask_bit = 0x80
    else:
        mask_bit = 0
    # 更新 payload length 0-125情况
    if msg_length < 126:
        header = PACK_LEN1(0x80 | rsv | opcode, msg_length | mask_bit)
    # 更新 payload length 126情况
    elif msg_length < (1 << 16):
        header = PACK_LEN2(0x80 | rsv | opcode, 126 | mask_bit, msg_length)
    # 更新 payload length 127情况
    else:
        header = PACK_LEN3(0x80 | rsv | opcode, 127 | mask_bit, msg_length)
    # 对负载进行掩码处理
    if use_mask:
        mask_int = self.randrange(0, 0xFFFFFFFF)
        mask = mask_int.to_bytes(4, "big")
        message = bytearray(message)
        _websocket_mask(mask, message)
        self._write(header + mask + message)
        # 更新发送帧的大小
        self._output_size += len(header) + len(mask) + msg_length
    # 对负载不进行掩码处理
    else:
        if msg_length > MSG_SIZE:
            self._write(header)
            self._write(message)
        else:
            self._write(header + message)
        # 更新发送帧的大小
        self._output_size += len(header) + msg_length

    # It is safe to return control to the event loop when using compression
    # after this point as we have already sent or buffered all the data.
    # 当写到底层发送 buffer 数据超过上限，需要等待会等待缓存数据发送，
    # 以控制写速率
    if self._output_size > self._limit:
        self._output_size = 0
        await self.protocol._drain_helper()

def _make_compress_obj(self, compress: int) -> ZLibCompressor:
    return ZLibCompressor(
        level=zlib.Z_BEST_SPEED,
        wbits=-compress,
        max_sync_chunk_size=WEBSOCKET_MAX_SYNC_CHUNK_SIZE,
    )

def _write(self, data: bytes) -> None:
    if self.transport.is_closing():
        raise ConnectionResetError("Cannot write to closing transport")
    self.transport.write(data)
```
`_send_frame`主要完成以下工作：
+ 发送帧构建
+ 调用底层`transport.write`进行帧发送；

> 通过`_send_frame`发送的帧的 FIN 值都是 1

对外提供的`ping`、`pong`，`close`和`send`源码如下：
+ `ping`
  ```python
  async def ping(self, message: Union[bytes, str] = b"") -> None:
      """Send ping message."""
      if isinstance(message, str):
          message = message.encode("utf-8")
      await self._send_frame(message, WSMsgType.PING)
  ```
+ `pong`
  ```python
  async def pong(self, message: Union[bytes, str] = b"") -> None:
      """Send pong message."""
      if isinstance(message, str):
          message = message.encode("utf-8")
      await self._send_frame(message, WSMsgType.PONG)
  ```
+ `close`
  ```python
  async def close(self, code: int = 1000, message: Union[bytes, str] = b"") -> None:
     """Close the websocket, sending the specified code and message."""
     if isinstance(message, str):
         message = message.encode("utf-8")
     try:
         await self._send_frame(
             PACK_CLOSE_CODE(code) + message, opcode=WSMsgType.CLOSE
         )
     finally:
         self._closing = True
  ```
+ `send`
  ```python
  async def send(
      self,
      message: Union[str, bytes],
      binary: bool = False,
      compress: Optional[int] = None,
  ) -> None:
      """Send a frame over the websocket with message as its payload."""
      if isinstance(message, str):
          message = message.encode("utf-8")
      if binary:
          await self._send_frame(message, WSMsgType.BINARY, compress)
      else:
          await self._send_frame(message, WSMsgType.TEXT, compress)
  ```

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

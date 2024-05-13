# 性能测试
## 压测工具
使用`wrk`压测工具，使用样例如下：
```bash
wrk -t100 -c10000 -d3s --latency --timeout=5 http://127.0.0.1:9006/
```
上述命令表示：使用 100 个线程运行大概 3s，保持 10000 个 http 连接，
每个连接超时时间是 5s。
运行结果样例如下：
```bash
Running 3s test @ http://127.0.0.1:9006/
  100 threads and 10000 connections
  Thread Stats   Avg      Stdev     Max   +/- Stdev
    Latency   255.35ms  115.35ms 883.33ms   84.81%
    Req/Sec   207.76    226.19     1.88k    86.65%
  Latency Distribution
     50%  266.37ms
     75%  327.59ms
     90%  344.96ms
     99%  681.03ms
  20240 requests in 3.10s, 22.72MB read
Requests/sec:   6530.39
Transfer/sec:      7.33MB
```
`wrk`的命令行参数含义如下：
```bash
-c, --connections: total number of HTTP connections to keep open with
                   each thread handling N = connections/threads

-d, --duration:    duration of the test, e.g. 2s, 2m, 2h

-t, --threads:     total number of threads to use

-s, --script:      LuaJIT script, see SCRIPTING

-H, --header:      HTTP header to add to request, e.g. "User-Agent: wrk"

    --latency:     print detailed latency statistics

    --timeout:     record a timeout if a response is not received within
                   this amount of time.
```

## 压测过程
压测下面几个场景：
+ `aiohttp + Application` 实现的服务；
+ `aiohttp` 不使用 `Application` 实现的服务；
+ `asyncio + transports&protocols`实现的服务，其中 http 解析使用 [httptools](https://github.com/MagicStack/httptools)；

每一个场景会分别测试使用`uvloop`和原生的`asyncio`。[uvloop](https://github.com/MagicStack/uvloop)

`aiohttp + Application`服务源码如下：
```python
import asyncio
import uvloop
from aiohttp import web

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

async def handle(request):
    payload_size = 1024
    resp = b'X' * payload_size
    return web.Response(body=resp)

def server():
    app = web.Application()
    app.router.add_route("GET", "/", handle)
    web.run_app(app, host="127.0.0.1", port=9006)

if __name__ == "__main__":
    server()
```
`aiohttp`不使用`Application`服务源码如下：
```python
import asyncio
import uvloop
from aiohttp import web

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

async def handle(request):
    payload_size = 1024
    resp = b'X' * payload_size
    return web.Response(body=resp)

async def server_without_app():
    server = web.Server(handler=handle)
    runner = web.ServerRunner(server, handle_signals=True)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 9008)
    await site.start()
    print("=======Serving on http://127.0.0.1:9008/=========")
    print("Print CTRL-C exit")
    while True:
        await asyncio.sleep(3600)

def run():
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(server_without_app())
    except web.GracefulExit:
        pass
    finally:
        loop.close()

if __name__ == "__main__":
    run()
```
`asyncio + transports&protocols`服务源码如下：
```python
import asyncio
import httptools
import socket
import signal
import uvloop

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

_RESP_CACHE = {}

class HttpRequest:
    def __init__(self, protocol, url, headers, version):
        self._protocol = protocol
        self._url = url
        self._headers = headers
        self._version = version

class HttpResponse:
    def __init__(self, protocol, request):
        self._protocol = protocol
        self._request = request
        self._headers_sent = False

    def write(self, data):
        self._protocol._transport.write(b''.join([
            'HTTP/{} 200 OK\r\n'.format(
                self._request._version).encode('latin-1'),
            b'Content-Type: text/plain\r\n',
            'Content-Length: {}\r\n'.format(len(data)).encode('latin-1'),
            b'\r\n',
            data
        ]))

class HttpProtocol(asyncio.Protocol):
    def __init__(self, *, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()
        self._loop = loop
        self._transport = None
        self._current_request = None
        self._current_parser = None
        self._current_url = None
        self._current_headers = None

    def on_url(self, url):
        self._current_url = url

    def on_header(self, name, value):
        self._current_headers.append((name, value))

    def on_headers_complete(self):
        self._current_request = HttpRequest(
            self, self._current_url, self._current_headers,
            self._current_parser.get_http_version())

        self._loop.call_soon(
            self.handle, self._current_request,
            HttpResponse(self, self._current_request))

    def connection_made(self, transport):
        self._transport = transport
        sock = transport.get_extra_info('socket')
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except (OSError, NameError):
            pass

    def connection_lost(self, exc):
        self._current_request = self._current_parser = None

    def data_received(self, data):
        if self._current_parser is None:
            assert self._current_request is None
            self._current_headers = []
            # 使用 httptools 解析
            self._current_parser = httptools.HttpRequestParser(self)

        self._current_parser.feed_data(data)

    def handle(self, request, response):
        parsed_url = httptools.parse_url(self._current_url)
        payload_size = parsed_url.path.decode('ascii')[1:]
        if not payload_size:
            payload_size = 1024
        else:
            payload_size = int(payload_size)
        resp = _RESP_CACHE.get(payload_size)
        if resp is None:
            resp = b'X' * payload_size
            _RESP_CACHE[payload_size] = resp
        response.write(resp)
        if not self._current_parser.should_keep_alive():
            self._transport.close()
        self._current_parser = None
        self._current_request = None

def shutdown():
    asyncio.get_event_loop().stop()

def main():
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGINT, shutdown)
    loop.add_signal_handler(signal.SIGTERM, shutdown)
    server = loop.create_server(lambda: HttpProtocol(loop=loop), host="127.0.0.1", port=9007)
    loop.run_until_complete(server)
    print("=======Serving on http://127.0.0.1:9007/=========")
    print("Print CTRL-C exit")
    try:
        loop.run_forever()
    finally:
        server.close()
        loop.close()

if __name__ == "__main__":
    main()
```

## 压测结果
|  |`aiohttp+app`|`aiohttp`不使用`app`|`asyncio+transports&protocols`使用`httptools`解析|
|--|-----------------------|----------------------------|-------------------------------------------------------|
|使用`uvloop`|`10265 qps`|`13269 qps`|`25234 qps`|
|使用`asyncio`|`6438 qps`|`7425 qps`|`21008 qps`|

**`uvloop`和`httptools`可以提高性能，越底层性能越高**。

根据`aiohttp`源码可知，其默认 http 请求解析使用 c 解析器，也就是使用 `httptools` 的解析器，
通过环境变量`AIOHTTP_NO_EXTENSIONS`控制，相关源码如下：
```python
NO_EXTENSIONS = bool(os.environ.get("AIOHTTP_NO_EXTENSIONS"))

try:
    if not NO_EXTENSIONS:
        from ._http_parser import (  # type: ignore[import-not-found,no-redef]
            HttpRequestParser,
            HttpResponseParser,
            RawRequestMessage,
            RawResponseMessage,
        )

        HttpRequestParserC = HttpRequestParser
        HttpResponseParserC = HttpResponseParser
        RawRequestMessageC = RawRequestMessage
        RawResponseMessageC = RawResponseMessage
except ImportError:  # pragma: no cover
    pass
```

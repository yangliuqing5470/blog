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

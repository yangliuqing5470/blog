import asyncio
import socket
import sys
import uvloop

class EchoServerProtocol(asyncio.Protocol):
    def connection_made(self, transport):
        self.transport = transport
        sock = transport.get_extra_info("socket")
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def connection_lost(self, exc):
        self.transport = None

    def data_received(self, data):
        self.transport.write(data)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "uvloop":
        print("use uvloop")
        loop = uvloop.new_event_loop()
    else:
        print("use asyncio loop")
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = loop.create_server(lambda: EchoServerProtocol(), "127.0.0.1", 9006)
    loop.run_until_complete(server)
    try:
        loop.run_forever()
    finally:
        loop.close()

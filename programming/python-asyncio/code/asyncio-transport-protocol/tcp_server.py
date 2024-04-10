import asyncio
import signal

server = None

def myshutdown():
    global server
    server._serving_forever_fut.set_result(None)

class EchoServerProtocol(asyncio.Protocol):
    def connection_made(self, transport):
        peername = transport.get_extra_info("peername")
        print("Connection from {0}".format(peername))
        self.transport = transport

    def data_received(self, data):
        message = data.decode()
        print("Data received: {0}".format(message))
        print("Send: {0}".format(message))
        self.transport.write(data)
        print("Close the client socket")
        self.transport.close()


async def main():
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGINT, myshutdown)
    loop.add_signal_handler(signal.SIGTERM, myshutdown)
    global server
    server = await loop.create_server(lambda: EchoServerProtocol(), "127.0.0.1", 8888, start_serving=False)
    async with server:
        await server.serve_forever()


asyncio.run(main())

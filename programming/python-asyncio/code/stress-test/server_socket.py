import sys
import socket
import asyncio
import uvloop


async def handle_client(client, loop):
    client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    while True:
        data = await loop.sock_recv(client, 102400)
        if not data:
            break
        await loop.sock_sendall(client, data)
    client.close()


async def run_server(loop):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 9005))
    server.listen(128)
    server.setblocking(False)

    while True:
        client, _ = await loop.sock_accept(server)
        loop.create_task(handle_client(client, loop))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "uvloop":
        print("use uvloop")
        loop = uvloop.new_event_loop()
    else:
        print("use asyncio loop")
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(run_server(loop))
    try:
        loop.run_forever()
    finally:
        loop.close()

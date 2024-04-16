import asyncio
import socket
import sys
import uvloop

async def handle_echo(reader, writer):
    sock = writer.get_extra_info("socket")
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    while True:
        data = await reader.readline()
        if not data:
            break
        writer.write(data)
        await writer.drain()
    writer.close()
    await writer.wait_closed()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "uvloop":
        print("use uvloop")
        loop = uvloop.new_event_loop()
    else:
        print("use asyncio loop")
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server =  asyncio.start_server(handle_echo, "127.0.0.1", 9007, limit=1024*1024)
    loop.run_until_complete(server)
    try:
        loop.run_forever()
    finally:
        loop.close()

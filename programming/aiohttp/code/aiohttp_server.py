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
    server()
    # run()

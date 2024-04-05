import asyncio
import time

async def counter(name: str):
    for i in range(0, 2):
        print("{0}: {1}".format(name, i))
        await asyncio.sleep(1)

async def main_task():
    start_time = time.time()
    tasks = []
    for n in range(4):
        tasks.append(asyncio.create_task(counter("task{0}".format(n))))
    for task in tasks:
        print(task)
        res = await task
        print("Task res: ", res)
    print("main_task cost {0}s".format(time.time() - start_time))


async def main_coro():
    start_time = time.time()
    for n in range(4):
        await counter("coro{0}".format(n))
    print("main_coro cost {0}s".format(time.time() - start_time))


print("Start run task...")
asyncio.run(main_task())
print("Start run coro...")
asyncio.run(main_coro())

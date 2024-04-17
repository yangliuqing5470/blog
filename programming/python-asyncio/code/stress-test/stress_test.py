import socket
import time
from concurrent import futures


def run_test(duration, timeout, host, port, msg, req_size):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout / 1000)
    sock.connect((host, port))
    requests_success = 0
    start = time.monotonic()
    while time.monotonic() - start < duration:
        sock.sendall(msg)
        nrecv = 0
        while nrecv < req_size:
            res = sock.recv(req_size)
            if not res:
                raise SystemExit()
            nrecv += len(res)
        requests_success += 1
    try:
        sock.close()
    except OSError:
        pass
    return requests_success

def run_once(concurrency, duration, timeout, host, port, msg, req_size):
    requests_success = 0
    with futures.ProcessPoolExecutor(max_workers=concurrency) as e:
        fs = []
        for _ in range(concurrency):
            fs.append(e.submit(run_test, duration, timeout, host, port, msg, req_size))
        res = futures.wait(fs)
        for fut in res.done:
            requests_success += fut.result()
    return requests_success


def main():
    variations = [
        {"title": "asyncio socket", "host": "127.0.0.1", "port": 9005, "msg_size": 1024},
        {"title": "asyncio socket", "host": "127.0.0.1", "port": 9005, "msg_size": 10240},
        {"title": "asyncio socket", "host": "127.0.0.1", "port": 9005, "msg_size": 102400},
        {"title": "asyncio transports&protocols", "host": "127.0.0.1", "port": 9006, "msg_size": 1024},
        {"title": "asyncio transports&protocols", "host": "127.0.0.1", "port": 9006, "msg_size": 10240},
        {"title": "asyncio transports&protocols", "host": "127.0.0.1", "port": 9006, "msg_size": 102400},
        {"title": "asyncio streams", "host": "127.0.0.1", "port": 9007, "msg_size": 1024},
        {"title": "asyncio streams", "host": "127.0.0.1", "port": 9007, "msg_size": 10240},
        {"title": "asyncio streams", "host": "127.0.0.1", "port": 9007, "msg_size": 102400},
    ]
    concurrency = 10
    duration = 10
    for variation in variations:
        mpr = 1
        msg_size = variation["msg_size"]
        msg = (b'x' * (msg_size - 1) + b'\n') * mpr
        req_size = msg_size * mpr
        timeout = 2 * 1000
        start = time.monotonic()
        host = variation["host"]
        port = variation["port"]
        requests_success = run_once(concurrency, duration, timeout, host, port, msg, req_size)
        qps = round(requests_success / duration, 2)
        res = "{0} with concurrency {1} and message size {2}KB have qps {3} --- cost {4}s".format(
            variation["title"], concurrency, round(variation["msg_size"] / 1024, 1), qps, time.monotonic() - start
        )
        print(res)


if __name__ == "__main__":
    main()

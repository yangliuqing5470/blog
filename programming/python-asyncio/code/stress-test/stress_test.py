import socket
import time
from concurrent import futures


def run_test(start, duration, timeout, host, port, msg, req_size):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout / 1000)
    sock.connect((host, port))
    requests_success = 0
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

def run_once(concurrency, start, duration, timeout, host, port, msg, req_size):
    requests_success = 0
    with futures.ProcessPoolExecutor(max_workers=concurrency) as e:
        fs = []
        for _ in range(concurrency):
            fs.append(e.submit(run_test, start, duration, timeout, host, port, msg, req_size))
        res = futures.wait(fs)
        for fut in res.done:
            requests_success += fut.result()
    return requests_success


def main():
    msg_size = 1024
    mpr = 1
    msg = (b'x' * (msg_size - 1) + b'\n') * mpr
    req_size = msg_size * mpr
    timeout = 2 * 1000
    concurrency = 10
    duration = 30
    start = time.monotonic()
    host = "127.0.0.1"
    port = 9005
    requests_success = run_once(concurrency, start, duration, timeout, host, port, msg, req_size)
    print("QPS: ", round(requests_success / duration, 2))


if __name__ == "__main__":
    main()

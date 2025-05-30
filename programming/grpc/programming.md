# Proto 文件编译
`gRPC`编程的第一步是将定义的`.proto`文件编译为对应的语言版本。例如有如下`.proto`文件目录结构：
```bash
.
├── buf.yaml
└── tutorial
    └── helloworld
        ├── v1
        │   ├── helloworld.proto
        ├── v2
        │   └── helloworld.proto
        └── v3
            └── helloworld.proto
```
`.proto`文件的内容样例如下：
```proto
syntax = "proto3";

package tutorial.helloworld.v1;

message SayHelloRequest {
  string name = 1;
}

message SayHelloResponse {
  string message = 1;
}

service GreeterService {
  rpc SayHello (SayHelloRequest) returns (SayHelloResponse) {}
}
```
对于`Python`语言，执行编译命令：
```bash
python3 -m grpc_tools.protoc --proto_path=. --python_out=. --pyi_out=. --grpc_python_out=. ./tutorial/helloworld/v1/helloworld.proto
```
+ **`--proto_path`参数**：表示`import`的搜索路径，也就是遇到`import "other.proto`语句，在指定的当前目录`.`下查找指定的`other.proto`文件。
+ **`--python_out`参数**：编译输出的`.proto`定义的**消息类**代码文件路径。
+ **`--pyi_out`参数**：`.pyi`文件路径，用于`Python`静态检查。
+ **`--grpc_python_out`参数**：生成的`gRPC`服务接口和客户端`Stub`接口代码文件路径。

如果`.proto`文件中有`package`声明，例如`package tutorial.helloworld.v1`，则编译生成产物存放在**指定路径下的`package`声明的子路径**。
也就是存放在`./tutorial/helloworld/v1`目录下。若没有`package`声明，则产物存放在指定路径`.`下。编译后文件目录结构如下：
```bash
.
├── buf.yaml
└── tutorial
    └── helloworld
        ├── v1
        │   ├── helloworld_pb2_grpc.py
        │   ├── helloworld_pb2.py
        │   ├── helloworld_pb2.pyi
        │   ├── helloworld.proto
        ├── v2
        │   ├── helloworld_pb2_grpc.py
        │   ├── helloworld_pb2.py
        │   ├── helloworld_pb2.pyi
        │   └── helloworld.proto
        └── v3
            ├── helloworld_pb2_grpc.py
            ├── helloworld_pb2.py
            ├── helloworld_pb2.pyi
            └── helloworld.proto
```
# 同步编程
## 单请求-单响应
使用的`.proto`样例是 **`proto` 文件编译**部分给出的样例。

**服务端**代码实现如下：
```python
import grpc
import helloworld_pb2
import helloworld_pb2_grpc
from concurrent import futures


class Greeter(helloworld_pb2_grpc.GreeterServiceServicer):
    def SayHello(self, request, context):
        return helloworld_pb2.SayHelloResponse(message="Hello, %s!" % request.name)


def server():
    port = "50051"
    server = grpc.server(thread_pool=futures.ThreadPoolExecutor(max_workers=10))
    helloworld_pb2_grpc.add_GreeterServiceServicer_to_server(Greeter(), server)
    server.add_insecure_port("0.0.0.0:" + port)
    server.start()
    print("Server started, listening on " + port)
    server.wait_for_termination()

if __name__ == "__main__":
    server()
```
**客户端**代码实现如下：
```python
import grpc
import helloworld_pb2
import helloworld_pb2_grpc


def run():
    print("Will try to greet world ...")
    with grpc.insecure_channel("localhost:50051") as channel:
        stub = helloworld_pb2_grpc.GreeterServiceStub(channel=channel)
        response = stub.SayHello(helloworld_pb2.SayHelloRequest(name="Jack"))
    print("Greeter client received: " + response.message)


if __name__ == "__main__":
    run()
```
上面样例实现，服务端一次只能处理一个客户端，不能同时处理多个客户端，效率低。

## 服务端流式
使用的`.proto`样例是 **`proto` 文件编译**部分给出的样例。将其中的`service`定义改为：
```proto
service GreeterService {
  rpc SayHello (SayHelloRequest) returns (stream SayHelloResponse) {}
}
```
**服务端**代码实现如下：
```python
import grpc
import helloworld_pb2
import helloworld_pb2_grpc
from concurrent import futures


class Greeter(helloworld_pb2_grpc.GreeterServiceServicer):
    def SayHello(self, request, context):
        for i in range(5):
            yield helloworld_pb2.SayHelloResponse(message=f"Hello number {i}, {request.name}!")


def server():
    port = "50051"
    server = grpc.server(thread_pool=futures.ThreadPoolExecutor(max_workers=10))
    helloworld_pb2_grpc.add_GreeterServiceServicer_to_server(Greeter(), server)
    server.add_insecure_port("0.0.0.0:" + port)
    server.start()
    print("Server started, listening on " + port)
    server.wait_for_termination()

if __name__ == "__main__":
    server()
```
**客户端**代码实现如下：
```python
import grpc
import helloworld_pb2
import helloworld_pb2_grpc


def run():
    print("Will try to greet world ...")
    with grpc.insecure_channel("localhost:50051") as channel:
        stub = helloworld_pb2_grpc.GreeterServiceStub(channel=channel)
        stream_response = stub.SayHello(helloworld_pb2.SayHelloRequest(name="Jack"))
        for response in stream_response:
            print("Greeter client received: " + response.message)


if __name__ == "__main__":
    run()
```
启动服务端后，客户端执行结果如下：
```bash
Will try to greet world ...
Greeter client received: Hello number 0, Jack!
Greeter client received: Hello number 1, Jack!
Greeter client received: Hello number 2, Jack!
Greeter client received: Hello number 3, Jack!
Greeter client received: Hello number 4, Jack!
```
上面样例实现，服务端一次只能处理一个客户端，不能同时处理多个客户端，效率低。**流式的实现其实使用迭代器能力**。

## 双端流式
使用的`.proto`样例是 **`proto` 文件编译**部分给出的样例。将其中的`service`定义改为：
```proto
service GreeterService {
  rpc SayHello (stream SayHelloRequest) returns (stream SayHelloResponse) {}
}
```
双端流式可以用于流量控制。协调发送方和接收方速度，避免消息丢失，提高消息传输可靠性。流量控制**底层原理**如下：
+ `HTTP/2`协议为每个`stream`和`connection`都维护了一个窗口大小（`window size`），默认`65535 `字节。
+ 每当客户端发送一段数据，就会消耗窗口大小。
+ 服务端只有在应用层读取数据后才会告诉`HTTP/2`层：我已经处理了这些数据，可以更新窗口。
+ 如果服务端长时间不读取数据，窗口就不会更新，客户端就会被阻塞（`back-pressure`）。

**服务端**代码实现如下：
```python
import datetime
import grpc
import helloworld_pb2
import helloworld_pb2_grpc
import time
from concurrent import futures


class Greeter(helloworld_pb2_grpc.GreeterServiceServicer):
    def SayHello(self, request_iterator, context):
        time.sleep(5)  # 延时消息接收，限制客户端发送请求速率
        str_received = 0
        for i, request in enumerate(request_iterator, start=1):
            str_received += len(request.name)
            if (i % 5) == 0:
                print(
                    f"{datetime.datetime.now().strftime("%T.%f")}   "
                    f"Request {i}:   Received {str_received} char in total"
                )
            time.sleep(1)  # 模拟服务端工作
            msg = "Hello"
            yield helloworld_pb2.SayHelloResponse(message=msg)
            if (i % 5) == 0:
                print(
                    f"{datetime.datetime.now().strftime("%T.%f")}   "
                    f"Request {i}:   Sent {len(msg)*i} char in total\n"
                )


def server():
    port = "50051"
    # 指定 grpc.http2.bdp_probe 参数为 0，禁止自动更改流控窗口大小
    server = grpc.server(thread_pool=futures.ThreadPoolExecutor(max_workers=10), options=[("grpc.http2.bdp_probe", 0)])
    helloworld_pb2_grpc.add_GreeterServiceServicer_to_server(Greeter(), server)
    server.add_insecure_port("0.0.0.0:" + port)
    server.start()
    print("Server started, listening on " + port)
    server.wait_for_termination()

if __name__ == "__main__":
    server()
```
**客户端**代码实现如下：
```python
import datetime
import grpc
import helloworld_pb2
import helloworld_pb2_grpc


def get_iter_data():
    max_iter = 25
    data_size = 4000
    test_request_data = "1" * data_size

    for i in range(1, (max_iter + 1)):
        if (i % 5) == 0:
            print(
                f"\n{datetime.datetime.now().strftime("%T.%f")}   "
                f"Request {i}: Sent {(data_size*i)} char in total"
            )

        yield helloworld_pb2.SayHelloRequest(name=test_request_data)


def run():
    print("Will try to greet world ...")
    # 指定 grpc.http2.bdp_probe 参数为 0，禁止自动更改流控窗口大小
    with grpc.insecure_channel("localhost:50051", options=[("grpc.http2.bdp_probe", 0)]) as channel:
        stub = helloworld_pb2_grpc.GreeterServiceStub(channel)
        stream_responses = stub.SayHello(get_iter_data())
        for i, _ in enumerate(stream_responses, start=1):
            if (i % 5) == 0:
                print(
                    f"{datetime.datetime.now().strftime("%T.%f")}   "
                    f"Received {i} responses\n"
                )


if __name__ == "__main__":
    run()
```
启动服务端后，客户端和客户端执行结果如下：
```bash
# 客户端结果
Will try to greet world ...
04:31:16.502227   Request 5: Sent 20000 char in total
04:31:16.502976   Request 10: Sent 40000 char in total
04:31:16.503534   Request 15: Sent 60000 char in total  # 客户端开始等待服务端消费数据（看时间前缀）
04:31:24.510568   Request 20: Sent 80000 char in total
04:31:26.513520   Received 5 responses
04:31:29.518058   Request 25: Sent 100000 char in total
04:31:31.520510   Received 10 responses
04:31:36.527642   Received 15 responses
04:31:41.534506   Received 20 responses
04:31:46.542387   Received 25 responses
# 服务端结果
Server started, listening on 50051
04:31:25.512067   Request 5:   Received 20000 char in total
04:31:26.513335   Request 5:   Sent 25 char in total
04:31:30.519271   Request 10:   Received 40000 char in total
04:31:31.520350   Request 10:   Sent 50 char in total
04:31:35.526192   Request 15:   Received 60000 char in total
04:31:36.527416   Request 15:   Sent 75 char in total
04:31:40.533519   Request 20:   Received 80000 char in total
04:31:41.534368   Request 20:   Sent 100 char in total
04:31:45.541544   Request 25:   Received 100000 char in total
04:31:46.542281   Request 25:   Sent 125 char in total
```
上面样例实现，服务端一次只能处理一个客户端，不能同时处理多个客户端，效率低。**流式的实现其实使用迭代器能力**。

# 异步编程
使用`asyncio`可以实现`gRPC`的高并发能力，服务端可以并发处理多个`RPC`请求，提高效率。下面样例使用的`.proto`文件和**同步编程**介绍的样例一致。
## 单请求-单响应
**服务端**代码如下：
```python
import asyncio
import grpc
import helloworld_pb2
import helloworld_pb2_grpc


class Greeter(helloworld_pb2_grpc.GreeterServiceServicer):
    async def SayHello(self, request, context):
        return helloworld_pb2.SayHelloResponse(message="Hello, %s!" % request.name)


async def serve():
    server = grpc.aio.server()  # 使用 asyncio 实现的服务对象
    helloworld_pb2_grpc.add_GreeterServiceServicer_to_server(Greeter(), server)
    listen_addr = "0.0.0.0:50051"
    server.add_insecure_port(listen_addr)
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
```
**客户端**代码如下：
```python
import asyncio
import grpc
import helloworld_pb2
import helloworld_pb2_grpc


async def run():
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = helloworld_pb2_grpc.GreeterServiceStub(channel)
        response = await stub.SayHello(helloworld_pb2.SayHelloRequest(name="jack"))
    print("Greeter client received: " + response.message)


if __name__ == "__main__":
    asyncio.run(run())
```
## 服务端流式
**服务端**代码如下：
```python
import asyncio
import grpc
import helloworld_pb2
import helloworld_pb2_grpc


class Greeter(helloworld_pb2_grpc.GreeterServiceServicer):
    async def SayHello(self, request, context):
        for i in range(3):
            yield helloworld_pb2.SayHelloResponse(message=f"Hello number {i}, {request.name}!")


async def serve():
    server = grpc.aio.server()  # 使用 asyncio 实现的服务对象
    helloworld_pb2_grpc.add_GreeterServiceServicer_to_server(Greeter(), server)
    listen_addr = "0.0.0.0:50051"
    server.add_insecure_port(listen_addr)
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
```
**客户端**代码如下：
```python
import asyncio
import grpc
import helloworld_pb2
import helloworld_pb2_grpc


async def run():
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = helloworld_pb2_grpc.GreeterServiceStub(channel)
        responses = stub.SayHello(helloworld_pb2.SayHelloRequest(name="jack"))
        async for response in responses:
            print("Greeter client received: " + response.message)


if __name__ == "__main__":
    asyncio.run(run())
```
启动服务端后，客户端执行结果如下：
```bash
Greeter client received: Hello number 0, jack!
Greeter client received: Hello number 1, jack!
Greeter client received: Hello number 2, jack!
```
# 安全认证
`gRPC`提供了多种安全认证方式。
+ **`SSL/TLS`认证**
+ **`Token`认证**
+ **`ALTS`认证**：`Google`内部使用的安全认证协议，类似`TLS`，但是自动管理证书。适合都在`Google`基础设施上运行的服务，这里不深入介绍。
+ **自定义认证**

认证的机制分为两种：
+ **`Channel credentials`**：绑定在`Channel`上，建立安全传输层（通常是`TLS`加密）。例如对服务器身份进行验证（如`CA`根证书），加密通信内容。
+ **`Call credentials`**：绑定在每一次`RPC`调用上，用于身份验证（例如`OAuth2 Token`）。由`metadata`（请求头）传输。

**同时实现加密传输和身份认证**，可以将两种凭据组合起来使用。

## SSL/TLS 认证

## Token 认证

## 自定义认证

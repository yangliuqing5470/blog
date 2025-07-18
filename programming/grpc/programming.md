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
使用**证书认证**的样例如下。证书认证有两种：
+ **服务端证书认证**：只有服务端提供证书认证，客户端验证服务端。
+ **双端证书认证**：服务端和客户端都提供证书认证，双端互相验证。

**服务端**代码如下：
```python
class SimpleGreeter(helloworld_pb2_grpc.GreeterServicer):
    def SayHello(self, request, unused_context):
        return helloworld_pb2.HelloReply(message="Hello, %s!" % request.name)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor())
    helloworld_pb2_grpc.add_GreeterServicer_to_server(SimpleGreeter(), server)
    # Loading credentials
    server_credentials = grpc.ssl_server_credentials(
        (
            (
                _credentials.SERVER_CERTIFICATE_KEY,
                _credentials.SERVER_CERTIFICATE,
            ),
        )
    )
    # Pass down credentials
    server.add_secure_port(_LISTEN_ADDRESS_TEMPLATE % _PORT, server_credentials)
    server.start()
    logging.info("Server is listening at port :%d", _PORT)
    server.wait_for_termination()
```
其中生成**服务端证书认证**对象的函数`grpc.ssl_server_credentials`函数签名如下：
```python
def ssl_server_credentials(
    private_key_certificate_chain_pairs,
    root_certificates=None,
    require_client_auth=False,
)
```
+ `private_key_certificate_chain_pairs`：可迭代对象，每个元素是`(private_key, cert_chain)`的字节串`tuple`。
  ```bash
  [
      (b"-----BEGIN PRIVATE KEY-----\n...", b"-----BEGIN CERTIFICATE-----\n...")
  ]
  ```
  其中`private_key`是服务端的私钥，`cert_chain`是服务端的证书或证书链。
+ `root_certificates`：用于**验证客户端**的根证书（`CA`证书）。启动**双端认证**需要这个参数。
+ `require_client_auth`：是否要求客户端提供证书进行**双向认证**，取值`True`表示客户端需要提供根证书。

**客户端**代码如下：
```python
def send_rpc(stub):
    request = helloworld_pb2.HelloRequest(name="you")
    try:
        response = stub.SayHello(request)
    except grpc.RpcError as rpc_error:
        _LOGGER.error("Received error: %s", rpc_error)
        return rpc_error
    else:
        _LOGGER.info("Received message: %s", response)
        return response


def main():
    # 证书对象
    channel_credential = grpc.ssl_channel_credentials(
        _credentials.ROOT_CERTIFICATE
    )
    with grpc.secure_channel(
        _SERVER_ADDR_TEMPLATE % _PORT, channel_credential  # 通道认证
    ) as channel:
        stub = helloworld_pb2_grpc.GreeterStub(channel)
        send_rpc(stub)
```
其中生成**通道认证**对象函数`grpc.ssl_channel_credentials`签名如下：
```python
def ssl_channel_credentials(
    root_certificates=None, private_key=None, certificate_chain=None
)
```
+ `root_certificates`：一个`bytes`序列，表示根证书。用于验证服务端身份。
+ `private_key`：一个`bytes`序列，客户端私钥。用于双端身份验证。
+ `certificate_chain`：一个`bytes`序列，客户端证书链，用于双端身份验证。

## Token 认证
基于`token`认证的一般流程如下：
+ 客户端侧生成`token`。
+ 客户端侧使用`token`构造请求发送给服务端，一般是`HTTP Authorization header`的一部分。
+ 大多数情况下，服务端侧使用拦截器`interceptor`验证`token`。

**服务端**侧代码如下：
```python
class SignatureValidationInterceptor(grpc.ServerInterceptor):
    def __init__(self):
        def abort(ignored_request, context):
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid signature")
        self._abort_handler = grpc.unary_unary_rpc_method_handler(abort)

    def intercept_service(self, continuation, handler_call_details):
        expected_metadata = ("authorization", "Bearer example_oauth2_token")
        if expected_metadata in handler_call_details.invocation_metadata:
            # Token 认证成功，执行对应的 handler
            return continuation(handler_call_details)
        else:
            return self._abort_handler

class SimpleGreeter(helloworld_pb2_grpc.GreeterServicer):
    def SayHello(self, request, unused_context):
        return helloworld_pb2.HelloReply(message="Hello, %s!" % request.name)


@contextlib.contextmanager
def run_server(port):
    # Bind interceptor to server
    server = grpc.server(
        futures.ThreadPoolExecutor(),
        interceptors=(SignatureValidationInterceptor(),),
    )
    helloworld_pb2_grpc.add_GreeterServicer_to_server(SimpleGreeter(), server)
    # Loading credentials
    server_credentials = grpc.ssl_server_credentials(
        (
            (
                _credentials.SERVER_CERTIFICATE_KEY,
                _credentials.SERVER_CERTIFICATE,
            ),
        )
    )
    # Pass down credentials
    port = server.add_secure_port(
        _LISTEN_ADDRESS_TEMPLATE % port, server_credentials
    )
    server.start()
    try:
        yield server, port
    finally:
        server.stop(0)


def main():
    with run_server("50051") as (server, port):
        server.wait_for_termination()

if __name__ == "__main__":
    main()
```
上述的服务端代码使用了**通道认证**和 **`token`认证**。在拦截器`SignatureValidationInterceptor`里面验证每个请求的`token`。

**客户端**侧代码如下：
```python
@contextlib.contextmanager
def create_client_channel(addr):
    # Call credential object will be invoked for every single RPC
    call_credentials = grpc.access_token_call_credentials(
        "example_oauth2_token"
    )
    # Channel credential will be valid for the entire channel
    channel_credential = grpc.ssl_channel_credentials(
        _credentials.ROOT_CERTIFICATE
    )
    # Combining channel credentials and call credentials together
    composite_credentials = grpc.composite_channel_credentials(
        channel_credential,
        call_credentials,
    )
    channel = grpc.secure_channel(addr, composite_credentials)
    yield channel

def send_rpc(channel):
    stub = helloworld_pb2_grpc.GreeterStub(channel)
    request = helloworld_pb2.HelloRequest(name="you")
    try:
        response = stub.SayHello(request)
    except grpc.RpcError as rpc_error:
        return rpc_error
    else:
        return response

def main():
    with create_client_channel("localhost:50051") as channel:
        send_rpc(channel)

if __name__ == "__main__":
    main()
```
客户端先生成`token`，然后组合`token`和证书认证作为`channel`的认证参数。在`channel`的底层实现中，会将`token`放在`header`中发送给服务端。

## 自定义认证
自定义认证的实现逻辑和基于`token`认证基本一致。服务端通过拦截器`interceptor`实现验证，客户端生成自定义认证通过请求发送。

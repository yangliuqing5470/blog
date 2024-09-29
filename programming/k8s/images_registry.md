# 镜像命名规则
镜像的名字反映一个镜像的来源，规则说明如下：
+ `docker pull ubuntu`表示从`Docker Hub`上拉取命名为`ubuntu`的镜像。完整命令是`docker pull docker.io/library/ubuntu`。
+ `docker pull myregistrydomain:port/foo/bar`表示和地址为`myregistrydomain:port`的镜像仓库连接，并寻找命名为`foo/bar`的镜像。

# 镜像仓库搭建
可以使用`docker`官方提供的`registry`镜像来搭建镜像仓库，运行如下命令：
```bash
$ sudo docker run -d -p 5000:5000 --restart always --name registry -v /home/ylq/registry:/var/lib/registry registry:2
```
编辑部署镜像仓库的容器宿主机的`/etc/hosts`文件，添加自建镜像仓库的域名：
```bash
# /etc/hosts 文件新增下面一行
10.211.55.9 my.registry.io
```
本地编译构建一个容器镜像实现返回`hostname`。构建镜像命令如下：
```bash
$ sudo docker build -f serve_hostname.dockerfile -t my.registry.io/serve_hostname:0.0.1 .
```
其中由于构建镜像的`serve_hostname.dockerfile`内容如下：
```dockerfile
FROM python:3.12.5-slim

WORKDIR /app

COPY app.py .

RUN pip3 install aiohttp[speedups] uvloop

EXPOSE 8080

CMD ["python3", "-u", "app.py"]
```
`app.py`文件的内容如下：
```python
import asyncio
import socket
import uvloop
from aiohttp import web


asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


def handle():
    return socket.gethostname()

def server():
    app = web.Application()
    app.router.add_route("GET", "/", handle)
    web.run_app(app, host="0.0.0.0", port=8080)

if __name__ == "__main__":
    server()
```
镜像编译完后结果如下：
```bash
$ sudo docker image ls
REPOSITORY                      TAG       IMAGE ID       CREATED          SIZE
my.registry.io/serve_hostname   0.0.1     3d3766280766   20 minutes ago   181MB
```
开始使用`docker push`命令将本地编译的镜像推到镜像仓库：
```bash
$ sudo docker push my.registry.io/serve_hostname:0.0.1
The push refers to repository [my.registry.io/serve_hostname]
Get "https://my.registry.io/v2/": dial tcp 10.211.55.9:443: connect: connection refused
```
结果`docker push`执行失败，因为`docker`默认使用`https`推送镜像。下面通过自签名证书解决这个问题。

## 生成自签名证书
```bash
# 在 /home/ylq/registry 目录下执行
$ mkdir -p certs

$ openssl req \
  -newkey rsa:4096 -nodes -sha256 -keyout certs/registry.key \
  -addext "subjectAltName = DNS:my.registry.io" \
  -x509 -days 365 -out certs/registry.crt
```
配置`CN`的时候填写`my.registry.io`域名。执行完后的文件机构如下：
```bash
$ tree certs/
certs/
├── registry.crt
└── registry.key
```

## 运行镜像服务
+ 运行如下命令，启动镜像服务
  ```bash
  # 在 /home/ylq/registry 目录下执行
  sudo docker run -d \
  --restart=always \
  --name registry \
  -v "$(pwd)"/certs:/certs \
  -v /home/ylq/registry:/var/lib/registry \
  -e REGISTRY_HTTP_ADDR=0.0.0.0:443 \
  -e REGISTRY_HTTP_TLS_CERTIFICATE=/certs/registry.crt \
  -e REGISTRY_HTTP_TLS_KEY=/certs/registry.key \
  -p 443:443 \
  registry:2
  ```
+ 添加自签发的证书
  ```bash
  $ sudo mkdir -p /etc/docker/certs.d/my.registry.io/
  $ sudo cp certs/registry.crt /etc/docker/certs.d/my.registry.io/
  ```
  由于自行签发的证书不被系统信任，所以我们需要将证书`registry.crt`移入`/etc/docker/certs.d/my.registry.io`文件夹中。
  否则客户端会报证书校验失败错误：
  ```bash
  tls: failed to verify certificate: x509: certificate signed by unknown authority
  ```

重新执行`docer push`命令：
```bash
$ sudo docker push my.registry.io/serve_hostname:0.0.1
The push refers to repository [my.registry.io/serve_hostname]
d45b7ba0df23: Pushed
9652c4954bd3: Pushed
09c2b039921e: Pushed
b28d7eb1de61: Pushed
a0a1e3b9f056: Pushed
7392a6b0f7cb: Pushed
34e6cc4b0ffc: Pushed
8e2ab394fabf: Pushed
0.0.1: digest: sha256:7948721ad37f219f1b637da7df40df4806c98f305b475cfdb3da3e9f638bcefe size: 1995
```
在另一台宿主机上拉取私有仓库的镜像（另一台宿主机也需要将证书`registry.crt`拷贝到`/etc/docker/certs.d/my.registry.io`目录下，
同时在`/etc/hosts`文件中添加`10.211.55.9 my.registry.io`以支持域名解析）：
```bash
$ sudo docker pull my.registry.io/serve_hostname:0.0.1
0.0.1: Pulling from serve_hostname
a2318d6c47ec: Pull complete
467daa3d4c8b: Pull complete
96d51d0de90c: Pull complete
e5e6c34f2b20: Pull complete
7ab50b4ae943: Pull complete
6dce14ab4463: Pull complete
e07899bb14eb: Pull complete
02cccb4d3950: Pull complete
Digest: sha256:7948721ad37f219f1b637da7df40df4806c98f305b475cfdb3da3e9f638bcefe
Status: Downloaded newer image for my.registry.io/serve_hostname:0.0.1
my.registry.io/serve_hostname:0.0.1
```
至此，完成基础的基于`https`访问的私有镜像仓库搭建。后续可以添加登录认证。

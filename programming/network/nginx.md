# 服务部署与配置
`nginx`服务采用`docker`容器部署。配置文件默认名为`nginx.conf`，存放路径是`/etc/nginx/nginx.conf`。部署命令样例如下：
```bash
sudo docker run -d --rm -p 80:80 --name my-nginx -v /home/ylq/workspace/nginx/nginx.conf:/etc/nginx/nginx.conf nginx:latest
```
配置文件`nginx.conf`由一系列的**指令**和**参数**组成。指令的样例如下：
```bash
# 一个简单的指令：指令名和参数之间以空格分割，结尾以;结尾
worker_processes 1;
# 一个块指令：在 {} 中可以包含其他的块指令和简单指令
http {...}
```
`nginx`中主要的**块指令**（以`{}`结束）如下：
+ `events`：包含通用的网络连接相关指令，例如`multi_accept`、`worker_connections`，`use`等指令。
+ `http`：包含处理`http/https`请求的各种配置指令，例如反向代理，缓存等。
+ `stream`：包含处理四层`TCP/UDP`流量的配置指令。
+ `server`：**定义在`http`或`stream`块中**，用于配置具体的虚拟主机。
+ `location`：**定义在`server`块中**，定义路径的匹配规则及其对应的处理方式。
+ `upstream`：**定义在`http`或`stream`块中**，用于配置后端服务器组，实现负载均衡、健康检查等。

下面给出`nginx.conf`配置文件样例：
```bash
user nobody; # a directive in the 'main' context

events {
    # configuration of connection processing
}

http {
    # Configuration specific to HTTP and affecting all virtual servers
    server {
        # configuration of HTTP virtual server 1
        location /one {
            # configuration for processing URIs starting with '/one'
        }
        location /two {
            # configuration for processing URIs starting with '/two'
        }
    }

    server {
        # configuration of HTTP virtual server 2
    }
}

stream {
    # Configuration specific to TCP/UDP and affecting all virtual servers
    server {
        # configuration of TCP virtual server 1
    }
}
```
可以通过如下命令检测配置文件`nginx.conf`的语法：
```bash
nginx -t -c <path>/nginx.conf

```
# Web 服务器

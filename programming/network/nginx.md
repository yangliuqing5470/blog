[nginx官方文档](https://nginx.org/en/docs/)
# 配置文件格式
`nginx`默认配置文件名是`nginx.conf`，存放的位置默认是`/etc/nginx`目录下。配置文件由一系列指令组成，格式如下：
```bash
# 每个指令以 ; 结尾
<directives> <parameters>;
# 样例
worker_processes 1;
```
指令分为**全局指令**，**模块配置指令**（在`{}`中）。根据不同的流量类型，有下面四种模块：
+ `events`：通用的连接处理，例如设置最大连接数`worker_connections 1024;`；
+ `http`：`http`相关配置；
+ `mail`：`mail`相关配置；
+ `stream`：`TCP/UDP`相关配置；

虚拟服务`server`块在上面四种流量类型模块中，`location`块在`server`块中，下面给出样例配置，说明了各个块的层级关系：
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
**子模块可以继承父模块的指令（例如`server`子模块可以继承父模块`http`中的指令），可以在子模块中重写指令，实现覆盖从父模块继承的指令**。
# 静态站点
[Serving Static Content](https://docs.nginx.com/nginx/admin-guide/web-server/serving-static-content/)

提供访问静态资源的`http`服务，`nginx`的配置样例如下：
```bash
# 设置 worker 进程个数，一般情况设置和 cpu 核心数相同
worker_processes 1;

events {
    # 单个 worker 进程的最大并发连接数
    worker_connections 1024;
    use epoll;
}

http {
    server {
        # 用于搜索请求文件的根目录，最终搜索路径是 root/<uri>
        # 例如：请求 uri 是 /images/，则最终搜索路径是 /usr/data/resources/images/
        root /usr/data/resources;
        listen 8080 backlog=128;
        location / {
            tcp_nodelay on;
            keepalive_timeout 65;
            # 如果请求是一个目录，自动返回目录列表
            autoindex on;
            sendfile on;
            sendfile_max_chunk 1m;
            tcp_nopush on;
        }
    }
}
```
如果请求的`URI`以`/`结尾，则`nginx`认为当前请求是个目录，`nginx`会在请求目录下找 index 文件（默认名是`index.html`），
可以使用`index`指令指定 index 文件名。例如，如果请求`URI`是`/images/path/`，则`nginx`会找文件`/usr/data/images/path/index.html`。
如果文件不存在，返回`403`错误。可以配置`autoindex`指令，返回目录列表。

指令`sendfile`、`tcp_nopush`和`tcp_nodelay`用于性能优化，这里不做详细解释，之后的原理分析会说。

# 反向代理

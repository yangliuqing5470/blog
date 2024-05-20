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
```bash
# 设置 worker 进程个数，一般情况设置和 cpu 核心数相同
worker_processes 1;

events {
    # 但个 worker 进程的最大并发连接数
    worker_connections 1024;
    use epoll;
}

http {
    server {
        root /usr/data/resources;
        listen 8080 backlog=128;
        location / {
            tcp_nodelay on;
            keepalive_timeout 65;
            autoindex on;
            sendfile on;
            sendfile_max_chunk 1m;
            tcp_nopush on;
        }
    }
}
```

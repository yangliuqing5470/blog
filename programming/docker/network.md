# iptables
`iptables`是 Linux 上的防火墙工具，用于配置和管理网络数据包的过滤规则。`iptables`分为**四表五链**（不涉及`security`表）：
+ `raw`表：可用于关闭`nat`表上启用的连接追踪机制。包含的链为：`PreRouting`，`Output`；
+ `managle`表：指定如何处理数据包，具备拆解报文、修改报文以及重新封装的功能，可用于修改 IP 头部信息，如：TTL。
包含的链为：`PreRouting`，`Forward`，`Input`，`Output`和`PostRouting`；
+ `nat`表：具备网络地址转换的功能，比如 SNAT、DNAT。包含链为：`PreRouting`，`Input`，`Output`，`PostRouting`；
+ `filter`表：负责过滤功能、防火墙，也就是由`filter`表来决定一个数据包是否继续发往它的目的地址或者被丢弃。
包含的链为：`Forward`，`Input`，`Output`；

五链说明如下：
+ `INPUT`链：处理输入数据包；
+ `OUTPUT`链：处理输出数据包；
+ `FORWARD`链：处理转发数据包；
+ `PREROUTING`链：用于目标地址转换（`DNAT`）；
+ `POSTOUTING`链：用于源地址转换（`SNAT`）；

四表执行的优先级是：`raw -> mangle -> nat -> filter`。网络数据经过`iptables`执行流程如下：
![iptables](./images/iptables.png)
每一个链处理结果动作包括接收（`ACCEPT`），丢弃（`DROP`），拒绝（`REJECT`），返回上层（`RETURN`）等。

`iptables`具体操作命令或者支持参数介绍，查看`man iptables`。

# docker网络
`docker`默认创建三种网络：`bridge`、`host`和`none`
```bash
$ sudo docker network ls
NETWORK ID     NAME      DRIVER    SCOPE
40d735af9656   bridge    bridge    local
772e0d536271   host      host      local
7b23eff277df   none      null      local
```
## none网络
`none`网络表示完全隔离的网络，容器内部只有`lo`网络设备，运行容器的时候指定`--network none`参数以让容器使用`none`网络。
```bash
$ sudo docker run -it --network=none busybox
/ # ifconfig 
lo        Link encap:Local Loopback  
          inet addr:127.0.0.1  Mask:255.0.0.0
          inet6 addr: ::1/128 Scope:Host
          UP LOOPBACK RUNNING  MTU:65536  Metric:1
          RX packets:0 errors:0 dropped:0 overruns:0 frame:0
          TX packets:0 errors:0 dropped:0 overruns:0 carrier:0
          collisions:0 txqueuelen:1000 
          RX bytes:0 (0.0 B)  TX bytes:0 (0.0 B)
```

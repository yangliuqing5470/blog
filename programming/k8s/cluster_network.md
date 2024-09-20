# 单机容器网络原理
每一个容器由于`network namespace`隔离，只能看见自己的*网络栈*。**网络栈**包含**网卡**、**回环设备**、**路由表**和`iptables`规则。

被隔离在不同`network namespace`下的容器如何相互通信？

为了理解上述问题，将容器看作主机，如果实现两台主机通信，最直接的办法是通过一根网线将两台主机连接起来。如果实现多台主机间互相通信，
将多台主机通过网线连接到一台交换机上。

**网桥（bridge）** 扮演着虚拟交换机的角色。网桥是一个工作在数据链路层的设备，根据`MAC`地址将数据包转发到网桥的不同的端口。
所以`docker`会默认在宿主机上创建一个`docker0`的网桥。连接相同网桥的容器可以互相通信。
```bash
$ ip addr show docker0
3: docker0: <NO-CARRIER,BROADCAST,MULTICAST,UP> mtu 1500 qdisc noqueue state DOWN group default
    link/ether 02:42:f8:3a:dd:6a brd ff:ff:ff:ff:ff:ff
    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0
       valid_lft forever preferred_lft forever
    inet6 fe80::42:f8ff:fe3a:dd6a/64 scope link
       valid_lft forever preferred_lft forever
```
将一个容器连接到一个网桥，例如`docker0`网桥，需要一个 **`Veth Pair`虚拟设备**。`Veth Pair`虚拟设备具有如下特点：
+ 被创建出来后，总是以两张虚拟网卡（`Veth Peer`）的形式成对出现。
+ 从其中一张网卡发出的数据包可以直接出现在对端的网卡上，即使这两张网卡在不同的`network namespace`中。

在宿主机上运行一个`busybox`容器：
```bash
$ sudo docker run --rm -itd --name busybox-1 busybox
```
查看容器的网络设备：
```bash
# 在宿主机上执行
$ sudo docker exec -it busybox-1 /bin/sh
# 在容器中执行
/ # ip addr
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host
       valid_lft forever preferred_lft forever
16: eth0@if17: <BROADCAST,MULTICAST,UP,LOWER_UP,M-DOWN> mtu 1500 qdisc noqueue
    link/ether 02:42:ac:11:00:02 brd ff:ff:ff:ff:ff:ff
    inet 172.17.0.2/16 brd 172.17.255.255 scope global eth0
       valid_lft forever preferred_lft forever
# 在容器中执行
/ # netstat -rn
Kernel IP routing table
Destination     Gateway         Genmask         Flags   MSS Window  irtt Iface
0.0.0.0         172.17.0.1      0.0.0.0         UG        0 0          0 eth0
172.17.0.0      0.0.0.0         255.255.0.0     U         0 0          0 eth0
```
容器`busybox-1`中有个`eth0@if17`的网卡，它是`Veth Pair`在容器中的一端。而`Veth Pair`的另一端在宿主机上，如下：
```bash
# 宿主机上执行
$ ip addr
...
3: docker0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default
    link/ether 02:42:f8:3a:dd:6a brd ff:ff:ff:ff:ff:ff
    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0
       valid_lft forever preferred_lft forever
    inet6 fe80::42:f8ff:fe3a:dd6a/64 scope link
       valid_lft forever preferred_lft forever
...
17: veth2bf860f@if16: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue master docker0 state UP group default
    link/ether 46:5d:12:96:d3:d5 brd ff:ff:ff:ff:ff:ff link-netnsid 2
    inet6 fe80::445d:12ff:fe96:d3d5/64 scope link
       valid_lft forever preferred_lft forever
# 宿主机上执行
$ brctl show
bridge name	bridge id		STP enabled	interfaces
...
docker0		8000.0242f83add6a	no		veth2bf860f
							    ...
```
其中宿主机上的`veth2bf860f@if6`虚拟网卡就是容器`busybox-1`中`eth0@if17`虚拟网卡的另一端。通过`brctl show`命令可知，
`veth2bf860f`虚拟网卡被插到`docker0`上。

此时在宿主机上在启动一个`busybox-2`容器：
```bash
$ sudo docker run --rm -itd --name busybox-2 busybox
```
通过`brctl show`可知，一个`vethd1317b7`虚拟网卡也被插到`docker0`上。
```bash
$ brctl show
bridge name	bridge id		STP enabled	interfaces
...
docker0		8000.0242f83add6a	no		veth2bf860f
							vethd1317b7
```
这时候在容器`busybox-1`里面可以`ping`通容器`busybox-2`地址，反之亦然。原理解释如下：
+ 在容器`busybox-1`里面访问`busybox-2`地址，例如`ping 172.17.0.3`。目的地址`172.17.0.3`会匹配`busybox-1`容器路由表的第二条规则，
此条路由规则的网关是`0.0.0.0`表示这是一条**直连规则**，也即直接通过`busybox-1`容器的网卡`eth0`走**二层网络**直发目的主机。
+ 通过**二层网络**到达`busybox-2`容器，需要目的地址`172.17.0.3`的`MAC`地址。所以`busybox-1`容器的网络协议栈会通过`eth0`网卡发送一个`ARP`广播，
以获取目的地址`172.17.0.3`的`MAC`地址。
+ 容器`busybox-1`中的`eth0`网卡是个`Veth Pair`设备的一端，一端在容器`busybox-1`的`network namespace`中，另一端在宿主机的`host namespace`中，
且被插在`docker0`网桥上，所以容器`busybox-1`发出的`APR`广播会到达`docker0`网桥，`docker0`网桥会扮演**二层交换机**角色，
把`ARP`广播转发到其他插在`docker0`网桥上的网卡。因此，容器`busybox-2`的网络协议栈收到此`APR`广播，将`172.17.0.3`对应的`MAC`地址回复给`busybox-1`容器。
+ 容器`busybox-1`拿到`172.17.0.3`的`MAC`地址后，可以开始通过容器的`eth0`网卡发送数据包。从容器`busybox-1`发出的数据包会直接到达`docker0`网桥，
`docker0`网桥扮演**二层交换机**角色，并根据目的`MAC`地址（`busybox-2`容器的`MAC`地址）在其`CAM`表（交换机通过`MAC`地址学习维护的端口和`MAC`地址对应表）查找对应端口为`vethd1317b7`，
然后将数据包发往该端口。
+ 端口`vethd1317b7`是容器`busybox-2`插在`docker0`网桥上的另一端网卡。数据包直接进入`busybox-2`容器网络接口`eth0`，进而进入`busybox-2`容器网络协议栈。

**总结**：**不同容器间通信通过`Veth Pair`虚拟设备+宿主机网桥方式实现**。

一张图说明容器间通信如下：
```bash
容器1 namespace       容器2 namespace
+-----------+         +--------------+
| busybox-1 |         |  busybox-2   |
|           |         |              |
|172.17.0.2 |         |  172.17.0.3  |
|   eth0    |         |      eth0    |
+-----------+         +--------------+
     |                       |
-----|-----------------------|--------------+  
+------------------------------------+      |
| veth2bf860f|          |vethd1317b7 |      |
|------------+          +------------|      |
|               docker0              |      |
|             172.17.0.1             |      | 宿主机 namespace
+------------------------------------+      | 
                                            |
            +------+                        | 
            |enp0s5|                        |
------------+------+------------------------+
```


# 跨主机容器网络原理
类似单机容器间通信方式（`Veth Pair`虚拟设备+宿主机网桥方式），对于跨主机容器间通信可以通过软件的方式创建一个整个集群公用的网桥，
然后把集群中所有的容器连到这个公共的网桥实现容器跨主机通信。

上面的思想用一张图总结如下：
```bash
+--------+-----------------+  +--------+----------------+
|        |enp0s5|          |  |        |enp0s5|         |
|        +------+          |  |        +------+         |
|                          |  |                         |
|-------------------------------------------------------|
|                       覆盖网络(overlay)               |
|-----------+-----------+        +----------+-----------|
|veth2bf860f|vethd1317b7|        |veth38e6d8|vethcd797b |
|-----------+-----------+--------+----------+-----------|
|    |           |         |  |       |          |      |
|-+----+-+   ++----+-+     |  |   +-+----++  +-+----+-+ |
| |eth0| |   ||eth0| |     |  |   | |eth0||  | |eth0| | |
| +----+ |   |+----+ |     |  |   | +----+|  | +----+ | |
|        |   |       |     |  |   |       |  |        | |
| 容器1  |   | 容器2 |     |  |   | 容器1 |  | 容器2  | |
+--------+---+-------+------------+-------+--+--------+-|
|                          |  |                         |
|        节点1             |  |          节点2          |
```

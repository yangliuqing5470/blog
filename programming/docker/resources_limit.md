# 引言
对`docker`运行的容器施加资源限制，例如限制使用的`cpu=2`，那么实际在容器中看到的`cpu`核数是什么？
实验使用`docker`宿主机系统是`ubuntu 22.04`，宿主机`cpu`相关的信息如下：
```python
# 逻辑核
$ cat /proc/cpuinfo| grep "processor"| wc -l
6
# 物理核
$ cat /proc/cpuinfo| grep "cpu cores"| uniq
cpu cores	: 6
```
运行的容器限制`cpu=2`，有两种限制，一直是`cpu`绑定 2 个核，一种是限制使用 `cpu=2`：
```bash
# 限制 cpu 使用 2 核
$ sudo docker run -it --cpus="2"  ubuntu:22.04
# cgroup 结果
$ cat /sys/fs/cgroup/system.slice/docker-7275c9e404b74a46be171af132b0208397c0f7e4dfd35ce1eb245d9db22f9722.scope/cpu.max
200000 100000
# 容器可使用的 cpu 编号范围
$ cat /sys/fs/cgroup/system.slice/docker-7275c9e404b74a46be171af132b0208397c0f7e4dfd35ce1eb245d9db22f9722.scope/cpuset.cpus.effective 
0-5
```
在容器查看读到的`cpu`个数如下：
```bash
root@7275c9e404b7:/# python3
Python 3.10.12 (main, Nov 20 2023, 15:14:05) [GCC 11.4.0] on linux
Type "help", "copyright", "credits" or "license" for more information.
>>> import os
>>> os.cpu_count()
6
>>>
```
接下来我们在看下限制容器绑定 2 个`cpu`的情况：
```bash
# 绑定 cpu 使用编号 2 和 3 两个核
$ sudo docker run -it --cpuset-cpus="2-3"  ubuntu:22.04
# 容器可以使用的 cpu 编号
$ cat /sys/fs/cgroup/system.slice/docker-6449e4546c5ce417bf40b8d9f7338bcbfeb343f805fe79fab2b20adec2376d9f.scope/cpuset.cpus.effective 
2-3
```
此时在容器中查看读到的`cpu`个数如下：
```bash
root@6449e4546c5c:/# python3
Python 3.10.12 (main, Nov 20 2023, 15:14:05) [GCC 11.4.0] on linux
Type "help", "copyright", "credits" or "license" for more information.
>>> import os
>>> os.cpu_count()
6
>>>
```
容器中查看两种限制情况下`cpu`信息：
```bash
root@6449e4546c5c:/# cat /proc/cpuinfo| grep "processor"| wc -l
6
root@6449e4546c5c:/# cat /proc/cpuinfo| grep "cpu cores"| uniq
cpu cores	: 6
```
结论：**容器中看到的`cpu`信息和宿主机一样，对容器施加`cpu`限制只是限制容器运行时可使用`cpu`资源大小**。

下面从底层原理详细了解下`docker`资源限制。

# Linux cgroup
[官方文档](https://docs.kernel.org/admin-guide/cgroup-v2.html)
## cgroup 介绍
`cgroup`由`v1`和`v2`两个版本，如果系统有`/sys/fs/cgroup/cgroup.controllers`则表示是`v2`版本，
否则是`v1`版本。下面介绍都是以`v2`为基础进行。
```bash
ls /sys/fs/cgroup/
cgroup.controllers      cgroup.pressure  cgroup.subtree_control  cpuset.cpus.effective  dev-hugepages.mount  io.cost.model  io.prio.class     memory.pressure  misc.capacity                  sys-fs-fuse-connections.mount  sys-kernel-tracing.mount
cgroup.max.depth        cgroup.procs     cgroup.threads          cpuset.mems.effective  dev-mqueue.mount     io.cost.qos    io.stat           memory.reclaim   misc.current                   sys-kernel-config.mount        system.slice
cgroup.max.descendants  cgroup.stat      cpu.pressure            cpu.stat               init.scope           io.pressure    memory.numa_stat  memory.stat      proc-sys-fs-binfmt_misc.mount  sys-kernel-debug.mount         user.slice
```
`cgroup`是一种以树形层级方式组织进程的机制。在每一个层级中分配系统资源，例如 CPU，
内存，IO等资源。树形层级说明如下（每一个 `group` 中有一组进程）：
```bash
        root cgroup
        /        \
    cgroup1       cgroup2
    /    \         |
cgroup3  cgroup4  cgroup5
```
`cgroup`由两部分组成：
+ **核心**：负责树形层级化地组织进程。
+ **控制器**：一般负责`cgroup`层级中特定类型资源的分配，例如 CPU、内存等资源。使用如下命令可以查看有哪些控制器。
  ```bash
  $ cat /sys/fs/cgroup/cgroup.controllers 
  cpuset cpu io memory hugetlb pids rdma misc
  ```
系统中的每一个进程只能属于一个`cgroup`。一个进程中的所有线程属于相同的`cgroup`。
创建子进程时，继承父进程的`cgroup`。一个进程可以迁移到其他的`cgroup`中，但迁移一个进程时，
被迁移进程的子进程不会迁移，还保留在之前的`cgroup`中。

可以选择性针对某个`cgroup`启动或禁用某些控制器，例如进行 CPU 或内存限制。如果某个`cgroup`启动了控制器，
则这个`cgroup`以及其`sub-hierarchy`的`cgroup`中的进程都会受到控制，且`sub-hierarchy`的`cgroup`不能覆盖上层控制器设置的限制。

## 基础操作
`cgroup v2`是一个单树形结构，系统只有一个挂载点。初始化时系统只有`root cgroup`，所有进程属于这个`root cgroup`。
```bash
# ubuntu 22.04 系统只有 cgroup2 挂载
$ mount | grep cgroup
cgroup2 on /sys/fs/cgroup type cgroup2 (rw,nosuid,nodev,noexec,relatime,nsdelegate,memory_recursiveprot)
# root cgroup 文件
$ ls /sys/fs/cgroup/
cgroup.controllers      cgroup.subtree_control  dev-hugepages.mount/  io.prio.class     misc.capacity                  sys-kernel-tracing.mount/
cgroup.max.depth        cgroup.threads          dev-mqueue.mount/     io.stat           misc.current                   system.slice/
cgroup.max.descendants  cpu.pressure            init.scope/           memory.numa_stat  proc-sys-fs-binfmt_misc.mount/  user.slice/
cgroup.pressure         cpuset.cpus.effective   io.cost.model        memory.pressure   sys-fs-fuse-connections.mount/
cgroup.procs            cpuset.mems.effective   io.cost.qos          memory.reclaim    sys-kernel-config.mount/
cgroup.stat             cpu.stat                io.pressure          memory.stat       sys-kernel-debug.mount/
```
可以通过在父`cgroup`下创建子目录来创建子`cgroup`。一个`cgroup`可以有多个子`cgroup`，形成一个树形结构。例如创建一个`mycgroup`的子`cgroup`：
```bash
# mycgroup 文件结构
/sys/fs/cgroup/mycgroup$ ls
cgroup.controllers      cgroup.stat             cpuset.cpus            cpu.weight       memory.events        memory.peak          memory.swap.peak
cgroup.events           cgroup.subtree_control  cpuset.cpus.effective  cpu.weight.nice  memory.events.local  memory.pressure      memory.zswap.current
cgroup.freeze           cgroup.threads          cpuset.cpus.partition  io.max           memory.high          memory.reclaim       memory.zswap.max
cgroup.kill             cgroup.type             cpuset.mems            io.pressure      memory.low           memory.stat          pids.current
cgroup.max.depth        cpu.idle                cpuset.mems.effective  io.prio.class    memory.max           memory.swap.current  pids.events
cgroup.max.descendants  cpu.max                 cpu.stat               io.stat          memory.min           memory.swap.events   pids.max
cgroup.pressure         cpu.max.burst           cpu.uclamp.max         io.weight        memory.numa_stat     memory.swap.high     pids.peak
cgroup.procs            cpu.pressure            cpu.uclamp.min         memory.current   memory.oom.group     memory.swap.max
```
每一个`cgroup`都有一个可读可写的`cgroup.procs`文件。
+ `cgroup.procs`文件包含了属于当前`cgroup`的所有进程 PIDs，一行一个，且 PIDs 是无序的；
+ 相同的 PID 可能会出现多次，例如进程先移出再移入该`cgroup`，或者读这个文件时候，PID 被重用了；
+ 可以通过将进程 PID 写到目标`cgroup`的`cgroup.procs`文件以实现将进程迁移到指定的`cgroup`；
  ```bash
  # 一次只能迁移一个进程，如果迁移多个进程，需要多次调下面的命令
  sudo sh -c 'echo 1421 > /sys/fs/cgroup/mycgroup/cgroup.procs'
  ```
+ 迁移进程的所有线程都会跟着一起迁移；
+ 创建子进程时，继承父进程的`cgroup`；
+ 进程退出后（`exit`）依然在所属的`cgroup`中，直到被回收；
+ 僵尸进程不会出现在`cgroup.procs`文件中，僵尸进程不支持迁移到其它组；

删除一个`cgroup`，只需要删除对应的目录即可（只有`cgroup`里没有活着的进程且没有子`cgroup`才可以被删除），例如删除`mycgroup`：
```bash
sudo rmdir /sys/fs/cgroup/mycgroup/
```
`/proc/$PID/cgroup`文件记录了进程的`cgroup`信息，例如：
```bash
# 先将进程 2307 写到 mycgroup 的 cgroup.procs 文件
$ cat /proc/2307/cgroup
0::/mycgroup

# 进程变为僵尸进行，且其所属的 cgroup 被删除，则查询信息会有 deleted 标志
0::/mycgroup (deleted)
```
`cgroup v2`的部分控制器支持线程粒度控制，这里不做介绍，参考官网文档。


每一个非`root cgroup`中都有一个`cgroup.events`文件，改文件内容如下：
```bash
$ cat /sys/fs/cgroup/mycgroup/cgroup.events
populated 0
frozen 0
```
其中`populated`字段表示是否当前`cgroup`及其子层级`cgroup`中包含活动进程，如果有活动进程，值为 1，否则为 0。
当`populated`值改变的时候，`poll`的`notify`事件被触发（内核通过`poll()`来监听`cgroup`所挂载目录下的全部文件读写）。可以用来监听当前`cgroup`及子层级`cgroup`中的进程都退出的时候，
触发清理工作。考虑有如下`cgroup`层级关系（括号中的数字表示对应`cgroup`包含活着进程数）：
```bash
            / C(1)
A(4) - B(0) 
            \ D(0)
```
此时 A、B、C 的`populated`字段值为 1，D 的`populated`字段值为 0。当 C 中的进程退出后，则 B 和 C 中的`populated`字段值会变为 0。
B 和 C 两个`cgroup`中文件`cgroup.events`修改事件会生成。

每一个`cgroup`都有一个`cgroup.controllers`文件，该文件记录当前`cgroup`启用的控制器（`root cgroup`下的该文件记录系统支持的所有控制器）。
```bash
$ cat /sys/fs/cgroup/mycgroup/cgroup.controllers
cpuset cpu io memory pids
```
新建子`cgroup`，子`cgroup`的`cgroup.controllers`继承父`cgroup`的`cgroup.subtree_control`的值，子`cgroup`的`cgroup.subtree_control`为空，
表示在该子`cgroup`下继续创建子`cgroup`时，默认不启动控制器。假设在`root cgroup`下创建`mycgroup`。

查看`mycgroup`的`cgroup.controllers`值和`root cgroup`下`cgroup.subtree_control`值相同：
```bash
# root cgroup 的 cgroup.subtree_control 值
$ cat cgroup.subtree_control 
cpuset cpu io memory pids
# 子 mycgroup 的 cgroup.controllers 值
$ cat mycgroup/cgroup.controllers 
cpuset cpu io memory pids
```
`mycgroup`下的`cgroup.subtree_control`值为空：
```bash
# 子 mycgroup 的 cgroup.subtree_control 值为空
$ cat mycgroup/cgroup.subtree_control 
```
此时`mycgroup`下的文件目录结构如下（包含`cgroup.controllers`启动的控制器相关文件）：
```bash
/sys/fs/cgroup/mycgroup$ ls
cgroup.controllers      cgroup.stat             cpuset.cpus            cpu.weight       memory.events        memory.peak          memory.swap.peak
cgroup.events           cgroup.subtree_control  cpuset.cpus.effective  cpu.weight.nice  memory.events.local  memory.pressure      memory.zswap.current
cgroup.freeze           cgroup.threads          cpuset.cpus.partition  io.max           memory.high          memory.reclaim       memory.zswap.max
cgroup.kill             cgroup.type             cpuset.mems            io.pressure      memory.low           memory.stat          pids.current
cgroup.max.depth        cpu.idle                cpuset.mems.effective  io.prio.class    memory.max           memory.swap.current  pids.events
cgroup.max.descendants  cpu.max                 cpu.stat               io.stat          memory.min           memory.swap.events   pids.max
cgroup.pressure         cpu.max.burst           cpu.uclamp.max         io.weight        memory.numa_stat     memory.swap.high     pids.peak
cgroup.procs            cpu.pressure            cpu.uclamp.min         memory.current   memory.oom.group     memory.swap.max
```
继续在`mycgroup`下创建子`children`，查看`children`的`cgroup.controllers`值和父`mycgroup`下`cgroup.subtree_control`一样：
```bash
# 孙子 children 的 cgroup.controllers 值为空
$ cat mycgroup/children/cgroup.controllers 
```
此时查看`children`的文件结构如下（没有任何控制器相关的文件）：
```bash
$ ls mycgroup/children/
cgroup.controllers  cgroup.freeze  cgroup.max.depth        cgroup.pressure  cgroup.stat             cgroup.threads  cpu.pressure  io.pressure
cgroup.events       cgroup.kill    cgroup.max.descendants  cgroup.procs     cgroup.subtree_control  cgroup.type     cpu.stat      memory.pressure
```
通过更新父`cgroup`中的`cgroup.subtree_control`，增加某些控制器，以开启子`cgroup`中的控制器：
```bash
$ sudo sh -c "echo '+memory' > /sys/fs/cgroup/mycgroup/cgroup.subtree_control"
```
此时子`children`会自动更新`memory`控制器相关文件，以及`cgroup.controllers`值：
```bash
$ cat children/cgroup.controllers 
memory

$ ls children/
cgroup.controllers  cgroup.max.descendants  cgroup.threads  memory.current       memory.max        memory.pressure      memory.swap.high
cgroup.events       cgroup.pressure         cgroup.type     memory.events        memory.min        memory.reclaim       memory.swap.max
cgroup.freeze       cgroup.procs            cpu.pressure    memory.events.local  memory.numa_stat  memory.stat          memory.swap.peak
cgroup.kill         cgroup.stat             cpu.stat        memory.high          memory.oom.group  memory.swap.current  memory.zswap.current
cgroup.max.depth    cgroup.subtree_control  io.pressure     memory.low           memory.peak       memory.swap.events   memory.zswap.max
```
如果要删除子`cgroup`中的某些控制器，也需要修改父`cgroup`的`cgroup.subtree_control`实现：
```bash
$ sudo sh -c "echo '-memory' > /sys/fs/cgroup/mycgroup/cgroup.subtree_control"
```
子`cgroup`中的相关文件会自动删除，更新`cgroup.controllers`值。

需要当前`cgroup`（非`root cgroup`）的`cgroup.procs`文件不为空，不能更新`cgroup.subtree_control`文件：
```bash
$ sudo sh -c "echo 3497 > /sys/fs/cgroup/mycgroup/cgroup.procs"
$ cat cgroup.procs 
3497
$ sudo sh -c "echo '+memory' > /sys/fs/cgroup/mycgroup/cgroup.subtree_control"
sh: 1: echo: echo: I/O error
```
此时需要将`cgroup.procs`中的进程移动到其他`cgroup`中，使得当前`cgroup`中的`cgroup.procs`为空。

资源是自顶向下（`top-down`）分配的，只有当一个`cgroup`从`parent`获得了某种资源，它才可以继续向下分发。也就是说，
子`cgroup`的`cgroup.subtree_control`中的值必须是父`cgroup`中`cgroup.subtree_control`中值的子集。

实际中不建议频繁在不同`cgroup`间迁移进程，因为成本高，应该在初始化时候将进程分配好`cgroup`。

## 核心接口文件
`cgroup`的核心接口文件以`cgroup.`开头，例如：
```bash
cgroup.controllers  cgroup.freeze  cgroup.max.depth        cgroup.pressure  cgroup.stat             cgroup.threads  cpu.pressure  io.pressure
cgroup.events       cgroup.kill    cgroup.max.descendants  cgroup.procs     cgroup.subtree_control  cgroup.type     cpu.stat      memory.pressure
```

# CPU 调度原理
**本小节说的`cpu`核都是逻辑核**。`Linux`内核为每个`cpu`核分配一个**运行队列**`struct rq`对象，运行队列中元素就是准备调度的进程。
为了满足不同场景需求，例如有些进程对实时性要求高的需要按优先级**实时调度**，有些进程对实时性要求不高但需要**公平调度**等，
内核在`struct rq`运行队列对象中实现了不同的调度器，进程按照不同的需求放到不同的调度器中。`struct rq`对象结构说明如下：
```bash
struct rq {
 # 实时任务调度器
 struct rt_rq rt;
 
 # CFS 完全公平调度器
 struct cfs_rq cfs;
 ...
}
```
+ **实时调度**：优先级是最主要考虑的因素。高优先级的进程可以抢占低优先级进程 CPU 资源来运行。
同一个优先级的进程按照先到先服务（FIFO）或者时间片轮转。`struct rt_rq rt`实时调度器的数据结构如下：
  ```bash
  数组队列           链表
  +-----+    
  |  0  | -> |    | -> |    | -> ...
  +-----+    
  | ... | -> |    | -> |    | -> ...
  +-----+    
  | 99  | -> |    | -> |    | -> ...
  +-----+    
  ```
  `struct rt_rq rt`是一个数组对象，数组下标表示优先级，每一个数组元素表示一个链表，链表中每一个元素都是相同优先级进程。
+ **完全公平调度 CFS**：强调让每个进程尽量公平地分配到 CPU 时间，而不是实时抢占。例如，假如有 N 个任务，
CPU 尽可能分配给每个进程 1/N 的处理时间。CFS 实现上引入了一个虚拟时间的概念。一旦进程运行虚拟时间就会增加。
尽量让虚拟时间最小的进程运行，谁小了就要多运行，谁大了就要少获得 CPU。最后尽量保证所有进程的虚拟时间相等，
动态地达到公平分配 CPU 的目的。由于进程运行后，其虚拟时间是不断变化，为了动态管理不断变化虚拟时间的进程，
CFS 使用**红黑树**数据结构管理。运行虚拟时间越小，越靠近树的左边。CFS 调度器每当挑选可运行进程时，直接从树的最左侧选择节点。
  + 当正在运行一个进程时候，如果其运行虚拟时间比其他进程大，为了避免频繁进程上下文切换，CFS 不会立刻切换到虚拟时间更小的进行运行，
  而是当前进程会至少运行内核参数`sched_min_granularity_ns`指定的最小运行时间。
  + CFS 支持进程权重设置，也就是指定进程的`nice`值。权重越大，进程分配的 CPU 时间越多。

进程创建初始化的时候，会设置进程的调度策略（例如设置为 CFS 调度），并初始化进程运行虚拟时间为 0。然后会选择一个合适的 CPU，
将创建好的进程添加到选择 CPU 对应的运行队列`struct rq`中。
+ **选择合适的 CPU**：在缓存性能和空闲核心两个点之间做权衡。同等条件下会尽量优先考虑缓存命中率，选择同 L1/L2 的物理核心，
其次会选择同一个物理 CPU 上的（共享 L3），最坏情况下去选择另外一个物理 CPU 上的核心。例如，都空闲情况下，优先选择进程上一次运行的 CPU，
其次是唤醒任务的 CPU，尽量考虑 `cpu cache`。其次考虑选择负载最小的没有缓存共享的 CPU。
  > 实际的物理核共享 L3 缓存。每一个物理核上由多个物理核心，每一个物理核心共享 L1/L2 缓存。每一个物理核心有 2 个逻辑核。

+ **将新进程添加到被选择 CPU 的运行队列`struct rq`中，也就是将新进程（设置 CFS 调度策略）插入到目标队列`struct rq`的红黑树中，等待被调度。**

内核有很多时机来触发调度，例如遇到阻塞 IO 会让出 CPU。定时中断，每一个 CPU 上都有一个时钟中断没，在中断函数中会触发调度等。

内核的负载均衡机制包装多核系统上，每一个核心运行的进程均衡。

CPU 调度的**带宽控制**：**控制一个用户组（`cgroup`）在给定周期时间内可以消耗 CPU 的时间，如果在给定的周期内消耗 CPU 时间超额，
就限制该用户组内任务调度，直到下一个周期**。
+ 带宽控制通过两个变量`quota`和`period`控制，其中`period`表示周期时间，`quota`表示在`period`周期时间内，一个`cgroup`可以使用的 CPU 时间。
当一个组的进程运行时间超过`quota`后，就会被限制运行，这个动作被称作`throttle`。直到下一个`period`周期开始，
这个组会被重新调度，这个过程称作`unthrottle`。
+ 多核系统中，每一个核都有一个独立的运行队列。一个`cgroup`对象中包含 CPU 核数量的调度实体以及对应的运行队列。
`quota`和`period`的值存储在`cfs_bandwidth`结构体中，该结构体嵌在`cgroup`对象中，`cfs_bandwidth`结构体还包含`runtime`成员记录剩余限额时间。
每当`cgroup`中的进程运行一段时间时，对应的`runtime`时间也在减少。
+ 系统会启动一个高精度定时器，周期时间是`period`，在定时器时间到达后重置剩余限额时间`runtime`为`quota`，开始下一个轮时间跟踪。
+ 在一个`preiod`周期内，`cgroup`中所有的进程运行的时间累加在一起，保证总的运行时间小于`quota`。
+ 每个`cgroup`会管理 CPU 个数的运行队列，每个运行队列中也有限额时间，该限额时间是从全局`cgroup`中的`quota`申请。
  > 例如，周期`period`值 `100ms`，限额`quota`值`50ms`，2 个 CPU 系统。CPU0 上运行队列首先从全局限额时间`quota`中申请`5ms`时间（此时`runtime`值为 45），
  然后运行进程。当`5ms`时间消耗完时，继续从全局时间限额`quota`中申请`5ms`（此时`runtime`值为 40）。CPU1 上的情况也同样如此，
  先从`quota`中申请一个时间片，然后供进程运行消耗。当全局`quota`剩余时间不足以满足 CPU0 或者 CPU1 申请时，
  就需要`throttle`操作运行队列。在定时器时间到达后，`unthrottle`所有已经`throttle`的运行队列。

`cgroup`对象中的`cfs_bandwidth`像是一个全局时间池，每个运行队列如果想让其管理的红黑树上的调度实体被调度，
必须首先向全局时间池中申请固定的时间片，然后供其进程消耗。当时间片消耗完，继续从全局时间池中申请时间片。
终有一刻，时间池中已经没有时间可供申请。此时`throttle`运行队列。

# docker 资源限制
`docker`实现资源限制底层依赖 Linux 的`cgroup`能力。运行一个`docker`后，会在宿主机系统`root cgroup`下创建子`cgroup`。
例如运行一个容器：
```bash
$ sudo docker run -d -it ubuntu:22.04 /bin/bash
99480e3c30ce7414eaa720c13d911a9ba30f2e5e2f9d47faab7981431e0573be
```
则给当前`docker`创建的子`cgroup`如下：
```bash
$ ls /sys/fs/cgroup/system.slice/docker-99480e3c30ce7414eaa720c13d911a9ba30f2e5e2f9d47faab7981431e0573be.scope/
cgroup.controllers      cgroup.pressure         cpu.idle               cpuset.cpus.partition  cpu.weight                hugetlb.1GB.numa_stat     hugetlb.2MB.max           io.prio.class        memory.high       memory.peak          memory.swap.high      misc.events   rdma.current
cgroup.events           cgroup.procs            cpu.max                cpuset.mems            cpu.weight.nice           hugetlb.1GB.rsvd.current  hugetlb.2MB.numa_stat     io.stat              memory.low        memory.pressure      memory.swap.max       misc.max      rdma.max
cgroup.freeze           cgroup.stat             cpu.max.burst          cpuset.mems.effective  hugetlb.1GB.current       hugetlb.1GB.rsvd.max      hugetlb.2MB.rsvd.current  io.weight            memory.max        memory.reclaim       memory.swap.peak      pids.current
cgroup.kill             cgroup.subtree_control  cpu.pressure           cpu.stat               hugetlb.1GB.events        hugetlb.2MB.current       hugetlb.2MB.rsvd.max      memory.current       memory.min        memory.stat          memory.zswap.current  pids.events
cgroup.max.depth        cgroup.threads          cpuset.cpus            cpu.uclamp.max         hugetlb.1GB.events.local  hugetlb.2MB.events        io.max                    memory.events        memory.numa_stat  memory.swap.current  memory.zswap.max      pids.max
cgroup.max.descendants  cgroup.type             cpuset.cpus.effective  cpu.uclamp.min         hugetlb.1GB.max           hugetlb.2MB.events.local  io.pressure               memory.events.local  memory.oom.group  memory.swap.events   misc.current          pids.peak
```
默认情况下，运行一个`docker`是没有资源限制的，可以使用宿主机内核调度允许的全部资源。
`docker`提供了一些运行时标志用于限制系统资源。
## CPU 限制
`Linux`正常运行的进程默认使用`CFS`调度器，下面介绍的都是针对`CFS`调度器运行时参数标志。
+ `--cpus=<value>`：指定容器可以使用多少可用的 CPU。例如，如果宿主机有 2 个 CPU，
设置`--cpus="1.5"`，则容器最多使用 1.5 个 CPU。这个参数等价于设置`--cpu-period="100000"`和`--cpu-quota="150000"`。
  ```bash
  $ sudo docker run -d -it --cpus=1.5  ubuntu:22.04 /bin/bash
  752e96b664d7e4867ec38fa0877fabaf1c133a8d630bec55d830257301455422

  $ cat docker-752e96b664d7e4867ec38fa0877fabaf1c133a8d630bec55d830257301455422.scope/cpu.max
  150000 100000
  ```
  可以看到指定`--cpu="1.5"`，实际会在`docker`的`cgroup`下`cpu.max`文件写`150000 100000`。
+ `--cpu-period=<value>`和`--cpu-quota=<value>`：设置`CFS`调度器的`period`和`quota`值，参考上小节`CPU`调度原理。
`--cpu-period`默认值是`100000`（`100ms`），一般不改变这个默认值。
+ `--cpuset-cpus`：将容器绑定到指定的 CPU 核上。如果宿主机有多个 CPU，CPU 以 0 开始，
有效的值可以类似是`0-3`（绑定使用前 4 个 CPU）或者类似`1,3`（绑定使用第二个到第四个 CPU）。
  ```bash
  $ sudo docker run -d -it --cpuset-cpus="1,3" ubuntu:22.04 /bin/bash
  1071b1c580b399773bb732c185dcba9fe63ea4df6649d3e4e24a1d2f388b2708

  $ cat docker-1071b1c580b399773bb732c185dcba9fe63ea4df6649d3e4e24a1d2f388b2708.scope/cpuset.cpus
  1,3

  $ cat docker-1071b1c580b399773bb732c185dcba9fe63ea4df6649d3e4e24a1d2f388b2708.scope/cpuset.cpus.effective 
  1,3
  ```
  指定`--cpuset-cpus="1，3"`，实际会在`docker`的`cgroup`下`cpuset.cpus`文件写入`1,3`。
  文件`cpuset.cpus.effective`表示实际生效的 CPU 核心。
+ `--cpu-shares`：指定容器使用宿主机 CPU 的相对值，默认值 1024。例如，有三个运行的容器，
`--cpu-shares`分别是 1024、512 和 512，则三个容器使用的 CPU 分别是 50%、25% 和 25%。
**只有当 CPU 负载高的时候，此值才会有效**。
  ```bash
  $ sudo docker run -d -it --cpu-shares=512 ubuntu:22.04 /bin/bash
  f6f49b90b7381868885b01104f3635b35db18be49c7c40138ddf4bd9e1c2090a

  $ cat docker-f6f49b90b7381868885b01104f3635b35db18be49c7c40138ddf4bd9e1c2090a.scope/cpu.weight
  20
  $ cat docker-f6f49b90b7381868885b01104f3635b35db18be49c7c40138ddf4bd9e1c2090a.scope/cpu.weight.nice 
  7
  ```
+ `--cpuset-mems`：指定`cgroup`中允许使用的内存节点（`NUMA`节点）。只想允许`cgroup`中的进程使用内存节点 0 和 1，
可以将`--cpuset-mems`参数设置为`0-1`。

## 内存限制
Linux 宿主机检查到`OOM`发生的时候，会杀掉进程释放内存，任何进程都可能被杀掉（[OOM 管理机制](https://www.kernel.org/doc/gorman/html/understand/understand016.html)）。
> `Docker daemon`进程的`OOM`优先级被调整，使得其被杀掉的概率比较低。
+ `-m or --memory=`：设置容器可以使用的最大内存大小，最小值是`6m`。
  ```bash
  $ sudo docker run -it -d --memory=100m ubuntu:22.04
  9ad8775d9187a7b064bab2ef02bc5e005ff0d63733a3eca348c3366cb20eb653

  $ cat docker-9ad8775d9187a7b064bab2ef02bc5e005ff0d63733a3eca348c3366cb20eb653.scope/memory.max 
  104857600
  ```
  `cgroup`下内存`memory`相关的部分接口文件说明如下：
  + `memory.current`：表示当前`cgroup`及子`cgroup`使用的内存总量。
  + `memory.peak`：记录当前`cgroup`及子`cgroup`从创建以来使用最大内存值。
  + `memory.min`：**硬限制**，指定为`cgroup`保留的最小内存量，即系统永远不应回收的内存。
  如果系统有内存压力需要回收内存，且没有可用的未受保护的可回收内存，则内核会调用`OOM`终止程序。
  + `memory.max`：**硬限制**，指定允许`cgroup`使用的最大内存限制。如果`cgroup`内的进程尝试使用的内存量超过所配置的限制值，
  且不能通过回收减少，内核将终止该进程并显示内存不足`OOM`错误。
  + `memory.low`：**软限制**，指定`cgroup`使用内存下限，如果当`cgroup`内存使用总量低于有效`low`值，
  尽力不回收内存，除非在未受保护`cgroup`中没有可回收的内存（也就是说，即使`cgroup`内存使用总量低于`memory.low`，
  也有可能被回收）。
  + `memory.high`：**软限制**，指定`cgroup`使用内存上限，如果`cgroup`使用内存超过`memory.high`值，不会触发`OOM`，
  内核会回收内存，使得`cgroup`使用内存低于`memory.high`值。
  + `memory.reclaim`：触发`cgroup`的内存回收，不影响网络相关的内存（`socket`内存）。
  此接口触发的内存回收（主动回收）并不意味着`cgroup`存在内存压力，内核可能回收内存低于或者高于指定的值。
  例如：
    ```bash
    echo "1G" > memory.reclaim
    ```
    触发内核回收`1G`的内存
  + `memory.events`：此文件值的更改一般会触发一个文件修改事件（`poll()监听`）。不同值枚举如下：
    + `low`：表示即使`cgroup`使用的内存低于低边界`memory.low`值，但由于内存压力较高而被回收的次数。
    这通常表明低边界`memory.low`设置太大
    + `high`：表示`cgroup`使用的内存超过`memory.high`值导致`cgroup`中的进程被受到限制而触发直接内存回收的次数
    + `max`：表示`cgroup`使用的内存超过`memory.max`的次数，如果直接的内存回收没有使`cgroup`使用的内存小于`memory.max`值，
    则会导致`OOM`
    + `oom`：`cgroup`内存使用达到限制且分配即将失败的次数
    + `oom_kill`：`cgroup`中因为`OOM`而被杀掉进程的数目
    + `oom_group_kill`：一个`group`发生`OOM`的次数

  + `memory.oom.group`：表示是否`cgroup`及子`cgroup`作为`OOM`操作的一个整体，
  也就是`cgroup`及子`cgroup`中的所有任务（进程）被一起`kill`或者都不被`kill`。
  可以用于避免部分任务被`kill`，保证工作的完整性。有`OOM`保护的任务（`oom_score_adj`设置`-1000`），
  不会被`kill`

  `memory.min`、`memory.low`、`memory.high`和`memory.max`值和系统内存回收有关，说明如下：
  ```bash
                      尽量不回收，                                               必须回收
                      如果没有可回收                        尽量回收，            低于 memory.max，
                      的未保护内存，                        确保内存使用          否则触发
  不会回收             也会回收           无操作            低于 memory.high      OOM
  -------> memory.min ------> memory.low ------> memory.high ------> memory.max ------>
  ```
+ `--memory-reservation`：设置`cgroup`中的`memory.low`值，软限制。
  ```bash
  $ sudo docker run -it -d --memory-reservation=100m ubuntu:22.04
  788bb76b3161ecd6d16a2b3ec6aa05ea14a5be1921a5845b3ea7bf1c43e1e61e

  $ cat docker-788bb76b3161ecd6d16a2b3ec6aa05ea14a5be1921a5845b3ea7bf1c43e1e61e.scope/memory.low 
  104857600
  ```
+ `--kernel-memory`：设置容器可以使用最大的`kernel-memory`，最小值是`6m`。
上面`-m or --memory=`限制的内存是总的内存，也即包括`kernel-memory`内存在内。
+ `--memory-swap`：设置容器被允许使用的`swap`内存大小（可以理解为拿多少磁盘当内存）。
此限制需要配合`--memory`一起使用。
  + 如果`--memory-swap`设置正值，则`--memory`和`--memory-swap`都需要设置，其中`--memory-swap`表示可以使用的物理内存和`swap`内存总数。
  例如，`--memory="300m"`，`--memory-swap="1g"`表示容器可以使用 300m 物理内存，700m `swap`内存。
    ```bash
    $ sudo docker run -it -d --memory=100m --memory-swap=200m ubuntu:22.04
    926966944f62caec423d1a4a744c66d3f4bb065cb12b1b5bcbfbf1cfdcf51547

    $ cat docker-926966944f62caec423d1a4a744c66d3f4bb065cb12b1b5bcbfbf1cfdcf51547.scope/memory.max 
    104857600
    $ cat docker-926966944f62caec423d1a4a744c66d3f4bb065cb12b1b5bcbfbf1cfdcf51547.scope/memory.swap.max 
    104857600
    ```
  + 如果`--memory-swap=0`，被忽略，保持默认设置。
  + 如果`--memory-swap`设置的值和`--memory`一样，则容器不会使用`swap`内存。
  + 如果不设置`--memory-swap`，但设置了`--memory`，则容器可以使用的`swap`内存和`--memory`值一样多，
  前提是宿主机有交换内存配置。例如，设置`--memory="300m"`，不设置`--memory-swap`值，
  容器可以使用总 600m 内存，包括 300m 物理内存，300m 的`swap`内存。
    ```bash
    # 宿主机启用了 swap 内存
    $ sudo docker run -it -d --memory=100m ubuntu:22.04
    8cae7e50e30ad24fefef603b5c3795f2a68a71cb172051101e2abfccb2f8a6e8
    $ cat docker-8cae7e50e30ad24fefef603b5c3795f2a68a71cb172051101e2abfccb2f8a6e8.scope/memory.max 
    104857600
    $ cat docker-8cae7e50e30ad24fefef603b5c3795f2a68a71cb172051101e2abfccb2f8a6e8.scope/memory.swap.max 
    104857600
    ```
  + 如果`--memory-swap=-1`，则容器可以使用宿主机允许的最大`swap`内存。
  + **在容器中使用`free`工具，结果是宿主机可用的`swap`，不是容器的**。
+ `--memory-swappiness`：取值`[0, 100]`之前，一个百分比。取值 0 表示关闭使用`swap`，
取值`100`表示可以使用`swap`的时候尽量使用`swap`。
+ `--oom-kill-disable`：默认情况下，如果容器中遇到了`OOM`，内核会杀掉容器中的进程。通过设置该参数，
可以关闭容器中的`OOM killer`，也就是不杀掉容器中的进程，此时容器内部申请内存的进程将`hang`，
直到他们可以申请到内存（容器内其他进程释放了内存）。

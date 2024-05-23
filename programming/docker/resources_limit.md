# Linux cgroup
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
        root group
        /        \
    group1       group2
    /    \         |
group3  group4   group5
```
`cgroup`由两部分组成：
+ **核心**：负责层级化地组织进程。
+ **控制器**：一般负责`cgroup`层级中特定类型资源的分配，例如 CPU、内存等资源。使用如下命令可以查看有哪些控制器。
  ```bash
  $ cat /sys/fs/cgroup/cgroup.controllers 
  cpuset cpu io memory hugetlb pids rdma misc
  ```
系统中的每一个进程只能属于一个`cgroup`。一个进程中的所有线程属于相同的`cgroup`。
创建子进程时，继承父进程的`cgroup`。一个进程可以迁移到其他的`cgroup`中，但迁移一个进程时，
被迁移进程的子进程不会迁移，还保留在之前的`cgroup`中。

可以选择性针对某个`cgroup`启动或禁用某些控制器，例如进行 CPU 或内存限制。如果某个`cgroup`启动了控制器，
则这个`cgroup`以及`sub-hierarchy`的`cgroup`中的进程都会受到控制，且`sub-hierarchy`的`cgroup`不能覆盖上层控制器设置的限制。

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

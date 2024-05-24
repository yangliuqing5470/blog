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

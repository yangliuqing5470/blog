> 基于`redis`源码分支`7.4.2`

# 概述
`redis`服务端是**事件驱动**模式，基于`IO`多路复用，采样`Reactor`编程模式实现。`redis`服务端框架设计主要实现以下几部分功能：
+ **核心架构模块**
  + **网络层（`IO`多路复用）**
    + **事件驱动模型**：基于`AE`框架（`Adaptive Event Loop`），针对不同操作系统封装事件模型。具体来说，`Linux`使用`epoll`，`BSD`使用`kqueue`，`Windows`使用`select`。
    + **事件类型**：**文件事件**处理客户端的连接、请求读取和响应写入。**时间事件**处理定时任务，如键过期检查、后台`RDB`快照等。
    + **事件模型工作流程**：初始化事件循环（`aeCreateEventLoop`）并绑定服务端监听端口。注册客户端连接事件（`connAcceptHandler`）。
    通过`aeProcessEvents`轮询处理事件。
  + **命令处理层**
    + **单线程模型**：主线程顺序处理命令，避免锁竞争，依赖高效数据结构和内存操作实现高吞吐。
    + **请求解析**：根据自定义的数据解析协议，将客户端请求数据解析为对应命令及参数。
    + **命令执行**：将解析的命令通过`redisCommandTable`表查找具体的命令执行函数并执行，执行结果作为响应回复客户端。
  + **数据存储层**
    + **`key-value`数据库**：不管是`key`还是`value`，在`redis`中都是`redisObject`对象。`redisObject`对象的定义如下：
      ```c
      typedef struct redisObject {
          unsigned type:4;
          unsigned encoding:4;
          unsigned lru:LRU_BITS; /* LRU time (relative to global lru_clock) or
                                  * LFU data (least significant 8 bits frequency
                                  * and most significant 16 bits access time). */
          int refcount;
          void *ptr;
      } robj;
      ```
      基于`type`（对象类型。如字符串，链表，集合等）和`encoding`（底层使用的数据结构。如哈希表，数组，跳跃表等）动态优化存储。
    + **数据存储底层数据结构**：动态字符串`SDS`、链表、跳跃表，字典，集合、字典树等。
+ **高可用与拓展模块**
  + **持久化**
    + **RDB持久化**：定时生成内存快照，子进程异步写入磁盘。
    + **AOF持久化**：记录写命令日志，支持三种刷盘策略（`Always/Everysec/No`）。
  + **集群模式**
    + **主从复制**：**异步复制**，主节点将写命令传播至从节点。**增量同步**，断线重连后仅同步差异数据。
    + **哨兵模式**：监控主节点健康状态，自动故障转移。多哨兵协商机制，避免网络分区误判。
    + **分片集群模式**：数据分片（`16384 Slot`），通过`CRC`哈希分配键到不同节点。同时支持节点动态扩缩容。
+ **性能优化机制**
  + **内存管理**
    + 内存淘汰策略（`LRU/LFU/TTL`）。
    + 大`Key`拆分（如`Hash`分片）和热点`Key`多级缓存。
  + **线程模型拓展**
    + 从`6.0`版本开始，支持多线程处理网络`IO`，但命令还是由主线程负责执行。
    + 后台线程处理惰性删除、AOF 刷盘等任务。
  + **管道化与批处理**
    + 减少网络往返延迟。

其中`redis`服务端核心功能架构原理如下（不涉及集群模式和持久化能力）：

![redis核心功能架构原理](./images/redis框架.png)

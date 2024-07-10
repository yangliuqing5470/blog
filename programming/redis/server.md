> 基于`redis`源码分支`5.0`
# 服务启动流程
`redis`服务是**事件驱动**模式，基于`IO`多路复用，采样`Reactor`编程模式实现。下面从服务启动的流程来了解`redis`设计思想。
## 数据结构定义
### 对象结构
`redis`是`key-value`型数据库，不管是`key`还是`value`，在`redis`中都是`redisObject`对象。`redisObject`对象定义如下：
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
+ `type`：表示对象的类型，取值如下：
  ```c
  /* The actual Redis Object */
  #define OBJ_STRING 0    /* String object. */
  #define OBJ_LIST 1      /* List object. */
  #define OBJ_SET 2       /* Set object. */
  #define OBJ_ZSET 3      /* Sorted set object. */
  #define OBJ_HASH 4      /* Hash object. */
  #define OBJ_MODULE 5    /* Module object. */
  #define OBJ_STREAM 6    /* Stream object. */
  ```
+ `encoding`：当前对象底层存储采用的数据结构；对于某种类型对象，在不同的情况下，`redis`使用不同的数据结构，下表给出了`encoding`和`type`之间的关系：
  |encoding取值|数据结构|存储对象类型|
  |------------|--------|------------|
  |`OBJ_ENCODING_RAW`|简单动态字符串(`sds`)|字符串|
  |`OBJ_ENCODING_INT`|整数|字符串|
  |`OBJ_ENCODING_HT`|字典(`dict`)|集合、字典、有序集合|
  |`OBJ_ENCODING_ZIPMAP`|未使用|未使用|
  |`OBJ_ENCODING_LINKEDLIST`|废弃|废弃|
  |`OBJ_ENCODING_ZIPLIST`|压缩列表(`ziplist`)|有序集合、字典|
  |`OBJ_ENCODING_INTSET`|整数集合(`intset`)|集合|
  |`OBJ_ENCODING_SKIPLIST`|跳跃表(`skiplist`)|有序集合|
  |`OBJ_ENCODING_EMBSTR`|简单动态字符串(`sds`)|字符串|
  |`OBJ_ENCODING_QUICKLIST`|快速链表(`quicklist`)|列表|
  |`OBJ_ENCODING_STREAM`|`stream`|`stream`|

  在对象的生命周期内，对象的编码不是固定的。例如集合对象，当集合中元素可用整数表示时，底层数据结构使用整数集合，
  当执行`sadd`命令，会先判断添加的元素能否解析为整数，不能则底层数据结构转为字典：
  ```c
  /* Add the specified value into a set.
   *
   * If the value was already member of the set, nothing is done and 0 is
   * returned, otherwise the new element is added and 1 is returned. */
  int setTypeAdd(robj *subject, sds value) {
      long long llval;
      if (subject->encoding == OBJ_ENCODING_HT) {
          dict *ht = subject->ptr;
          dictEntry *de = dictAddRaw(ht,value,NULL);
          if (de) {
              dictSetKey(ht,de,sdsdup(value));
              dictSetVal(ht,de,NULL);
              return 1;
          }
      } else if (subject->encoding == OBJ_ENCODING_INTSET) {
          if (isSdsRepresentableAsLongLong(value,&llval) == C_OK) {
              uint8_t success = 0;
              subject->ptr = intsetAdd(subject->ptr,llval,&success);
              if (success) {
                  /* Convert to regular set when the intset contains
                   * too many entries. */
                  if (intsetLen(subject->ptr) > server.set_max_intset_entries)
                      setTypeConvert(subject,OBJ_ENCODING_HT);
                  return 1;
              }
          } else {
              /* Failed to get integer from object, convert to regular set. */
              // 编码转换
              setTypeConvert(subject,OBJ_ENCODING_HT);
  
              /* The set *was* an intset and this value is not integer
               * encodable, so dictAdd should always work. */
              serverAssert(dictAdd(subject->ptr,sdsdup(value),NULL) == DICT_OK);
              return 1;
          }
      } else {
          serverPanic("Unknown set encoding");
      }
      return 0;
  }
  ```
  有些对象同时也会使用不同的数据结构存储。例如有序集合对象定义如下：
  ```c
  typedef struct zset {
    dict *dict;
    zskiplist *zsl;
  } zset;
  ```
  同时使用字典和跳跃表存储，字典成员查询时间复杂度为`O(1)`，跳跃表范围查找时间复杂度为`O(logN)`，所以有序集合对象利用了字典和跳跃表的组合优势。
  实际的数据只存储一份，字典和跳跃表存储的都是数据指针，也就是多增加指针开销。
+ `lru`：占`24`位，用于实现缓存淘汰策略。在配置文件`maxmemory-policy`字段配置内存达到限制时的缓存淘汰策略，常见的策略是`LRU`和`LFU`。
`LRU`的思想是如果数据最近被访问，则将来被访问的概率大，此时`lru`存储的是对象的访问时间。`LFU`的思想是如果数据过去被多次访问，
则数据将来被访问几率更高，此时`lru`存储的是对象上次访问时间与访问次数。例如在执行`GET`命令会执行如下逻辑更新`lru`：
  ```c
  if (server.maxmemory_policy & MAXMEMORY_FLAG_LFU) {
      updateLFU(val);
  } else {
      // 更新 lru 为当前时间
      val->lru = LRU_CLOCK();
  }

  /* Update LFU when an object is accessed.
   * Firstly, decrement the counter if the decrement time is reached.
   * Then logarithmically increment the counter, and update the access time. */
  void updateLFU(robj *val) {
      unsigned long counter = LFUDecrAndReturn(val);
      counter = LFULogIncr(counter);
      val->lru = (LFUGetTimeInMinutes()<<8) | counter;
  }
  ```
  如果是`LFU`测试，则`lru`低`8`位更新为频率值，高`16`位为对象上次访问时间，以分支为单位。需要注意的是，是通过`LFUDecrAndReturn`函数获取对象访问频率，
  并在此基础上累积，原因是因为越老的数据一般被访问次数越大，越新的数据被访问次数越少，即使老的数据很久没被访问，这是不公平的。所以，
  `LFUDecrAndReturn`函数实现了访问次数随时间衰减的过程；
+ `refcount`：当前对象的引用次数，用于对象的共享；共享对象时，`refcount`值加`1`；删除对象时，`refcount`值减`1`；当`refcount`值为`0`时，
会释放对象；
+ `ptr`：指向对象底层存储的数据结构，当存储的数据长度小于等于`20`且可以表示为一个`long`类型的整数时，数据则直接存储在`ptr`字段；
正常情况下，为了存储一个字符串对象，需要两次内存分配，一次是`redisObject`对象分配，一次是`sds`分配。因此对于字符串较短，且是整数时，
为了减少内存分配，提出`OBJ_ENCODING_EMBSTR`编码，只分配一次`redisObject`对象内存，将数据存储在`ptr`，这样`redisObject`和`sds`连续存储，
会利用计算机的高速缓存；

### 客户端

`redis`是典型的`client-server`架构，使用`client`结构体存储连接客户端的信息，这里只给出和服务启动及客户端命令处理相关的字段：
```c
typedef struct client {
    uint64_t id;            /* Client incremental unique ID. */
    int fd;                 /* Client socket. */
    redisDb *db;            /* Pointer to currently SELECTed DB. */
    robj *name;             /* As set by CLIENT SETNAME. */
    sds querybuf;           /* Buffer we use to accumulate client queries. */
    size_t qb_pos;          /* The position we have read in querybuf. */
    ...
    int argc;               /* Num of arguments of current command. */
    robj **argv;            /* Arguments of current command. */
    struct redisCommand *cmd, *lastcmd;  /* Last command executed. */
    ...
    list *reply;            /* List of reply objects to send to the client. */
    unsigned long long reply_bytes; /* Tot bytes of objects in reply list. */
    size_t sentlen;         /* Amount of bytes already sent in the current buffer or object being sent. */
    ...
    time_t lastinteraction; /* Time of the last interaction, used for timeout */
    ...
    int bufpos;
    char buf[PROTO_REPLY_CHUNK_BYTES];
}
```
+ `id`：客户端的唯一标识；
+ `fd`：客户端`socket`文件描述符；
+ `db`：客户端选择的数据库对象`redisDb`；`redisDb`定义如下：
  ```c
  typedef struct redisDb {
      dict *dict;                 /* The keyspace for this DB */
      dict *expires;              /* Timeout of keys with a timeout set */
      dict *blocking_keys;        /* Keys with clients waiting for data (BLPOP)*/
      dict *ready_keys;           /* Blocked keys that received a PUSH */
      dict *watched_keys;         /* WATCHED keys for MULTI/EXEC CAS */
      int id;                     /* Database ID */
      long long avg_ttl;          /* Average TTL, just for stats */
      list *defrag_later;         /* List of key names to attempt to defrag one by one, gradually. */
  } redisDb;
  ```
  + `id`：数据库的编号，默认`redis`有`16`个数据库，取值`0-15`；
  + `dict`：存储数据库的所有键值对；
  + `expires`：存储数据库所有键的过期时间（设置过期时间的键），`key`是对应键对象的指针，`value`是过期时间值；
  + `avg_ttl`：所有键剩余存活时间的平均值，用于统计；
  + `defrag_later`：等待碎片整理的键列表；
  + `blocking_keys`：使用命令`BLPOP`阻塞获取列表元素时，如果列表为空，则会阻塞客户端。这时候会将列表键记录在`blocking_keys`字典中；
  + `ready_keys`：当使用`PUSH`向列表添加元素，会从`blocking_keys`字典查找列该表键，如果找到，说明有客户端正阻塞等待，此列表键会添加到`ready_keys`字典，
  用于后续响应正在阻塞的客户端；
  + `watched_keys`：`redis`支持事务，`multi`命令用于开启事务，`exec`命令用于执行事务。如何保证在开启事务到执行事务期间，关注的数据不被修改？
  `redis`使用乐观锁实现，可以使用`watch`命令监控关心的数据键。`watched_keys`字典存储被`watch`命令监控的所有键，其中字典`key`是监控的数据键，
  字典的`value`是对应的客户端对象。当`redis`服务端收到写命令，会从`watched_keys`字典查找要写的键，如果找到，说明有客户端正在监控此键，
  并标记查找到对应的客户端为`dirty`。`redis`收到客户端发的`exec`命令时，如果客户端有`dirty`标志，则拒绝执行此事务；
+ `name`：客户端名称，通过`CLIENT SETNAME`设置；
+ `querybuf`：输入缓存区，`recv`函数接收的客户端命令请求会暂存在此缓存区；
+ `qb_pos`：标记在`querybuf`已读的位置；
+ `lastinteraction`：客户端上次与服务器交互的时间，以此实现客户端的超时处理；
+ `argc`：当前请求命令参数个数；
+ `argv`：对应当前请求命令参数；
+ `cmd`：待执行的客户端命令；解析命令请求后，会根据命令名称查找该命令对应的命令对象，存储在`cmd`字段；
+ `reply`：响应列表，存放准备发送给客户端的响应数据；响应数据（也就是链表节点）的类型为`clientReplyBlock`：
  ```c
  /* This structure is used in order to represent the output buffer of a client,
   * which is actually a linked list of blocks like that, that is: client->reply. */
  typedef struct clientReplyBlock {
      size_t size, used;
      char buf[];
  } clientReplyBlock;
  ```
  其中`size`表示缓存区数组`buf`空间总大小，`used`表示已使用空间大小；
+ `reply_bytes`：`reply`链表中所有节点占用空间大小，单位字节；
+ `sentlen`：已发送给客户端的字节数；
+ `buf`：输出缓存区数组，存放发送给客户端的数据；和`reply`相比，会优先将响应数据存放在`buf`缓存中。存放`buf`失败，
会在尝试存放在`reply`链表中；
+ `bufpos`：表示`buf`中字节的最大位置，在`[sentlen, bufpos)`之间的数据都是需要发送给客户端的；

### 服务端
`redis`使用`redisServer`结构体存储服务端的所有信息。这里只给出部分字段说明：
```c
struct redisServer {
    /* General */
    ...
    char *configfile;           /* Absolute config file path, or NULL */
    ...
    redisDb *db;
    int dbnum;                  /* Total number of configured DBs */
    dict *commands;             /* Command table */
    ...
    aeEventLoop *el;
    ...
    /* Networking */
    int port;                   /* TCP listening port */
    char *bindaddr[CONFIG_BINDADDR_MAX]; /* Addresses we should bind to */
    int bindaddr_count;         /* Number of addresses in server.bindaddr[] */
    ...
    int ipfd[CONFIG_BINDADDR_MAX]; /* TCP socket file descriptors */
    int ipfd_count;             /* Used slots in ipfd[] */
    ...
    list *clients;              /* List of active clients */
    ...
    int maxidletime;                /* Client timeout in seconds */
}
```
+ `configfile`：服务端配置文件绝对路径；
+ `db`：数据库数组，每个元素是`redisDB`；
+ `dbnum`：数据库数目，可以通过配置`databases`设置，默认值是`16`；
+ `commands`：`redis`服务端支持的所有命令都存在这个字典，其中`key`为命令名字，`value`为对应的`redisCommand`对象；
+ `el`：事件驱动对象，类型为`aeEventLoop`；
+ `port`：服务端监听的端口号，可通过配置参数`port`配置，默认值`6379`；
+ `bindaddr`：字符串数组，存放绑定的所有`IP`地址；`CONFIG_BINDADDR_MAX=16`说明最多可以绑定`16`个`IP`地址；
+ `bindaddr_count`：`bindaddr`数组元素个数；
+ `ipfd`：存放针对`bindaddr`里面所有`IP`地址创建的`tcp socket`文件描述符；
+ `ipfd_count`：`ipfd`数组元素个数；
+ `clients`：链表，存放当前连接的所有激活的客户端；
+ `maxidletime`：客户端超时时间，可通过配置参数`timeout`设置。结合`client`对象的`lastinteraction`字段，当客户端没有与服务器交互的时间超过`maxidletime`时，
会认为客户端超时并释放该客户端连接；

### 命令
`redis`服务端支持的所有命令都存储在全局变量`redisCommandTable`中，每个命令类型为`redisCommand`结构：
```c
struct redisCommand redisCommandTable[] = {
    {"module",moduleCommand,-2,"as",0,NULL,0,0,0,0,0},
    {"get",getCommand,2,"rF",0,NULL,1,1,1,0,0},
    {"set",setCommand,-3,"wm",0,NULL,1,1,1,0,0},
    ...
}
```
`redisCommand`结构定义如下：
```c
typedef void redisCommandProc(client *c);
typedef int *redisGetKeysProc(struct redisCommand *cmd, robj **argv, int argc, int *numkeys);
struct redisCommand {
    char *name;
    redisCommandProc *proc;
    int arity;
    char *sflags; /* Flags as string representation, one char per flag. */
    int flags;    /* The actual flags, obtained from the 'sflags' field. */
    /* Use a function to determine keys arguments in a command line.
     * Used for Redis Cluster redirect. */
    redisGetKeysProc *getkeys_proc;
    /* What keys should be loaded in background when calling this command? */
    int firstkey; /* The first argument that's a key (0 = no keys) */
    int lastkey;  /* The last argument that's a key */
    int keystep;  /* The step between first and last key */
    long long microseconds, calls;
};
```
+ `name`：表示命令的名字，例如`set`；
+ `proc`：对应命令处理函数；
+ `arity`：命令参数个数，用于校验命令请求格式是否正确。如果`arity < 0`，则命令的参数个数不能超过`(-1) * arity`；
如果`arity > 0`，则命令的参数个数必须等于`arity`；命令的本身也是一个参数；
  ```c
  if ((cmddef.arity > 0 && argc != cmddef.arity) ||
      (cmddef.arity < 0 && argc < (cmddef.arity * -1))) {
      fprintf(stderr, "[ERR] Wrong number of arguments for "
                      "specified --cluster sub command\n");
      return NULL;
  }
  ```
+ `sflags`：命令标志，例如表示读命令还是写命令；字符串表示，为了可读性；
+ `flags`：命令标志的二进制格式，在服务启动阶段通过解析`sflags`得到；命令标志的取值和含义说明如下：
  ```c
  #define CMD_WRITE (1<<0)            /* "w" flag */
  #define CMD_READONLY (1<<1)         /* "r" flag */
  #define CMD_DENYOOM (1<<2)          /* "m" flag */
  #define CMD_MODULE (1<<3)           /* Command exported by module. */
  #define CMD_ADMIN (1<<4)            /* "a" flag */
  #define CMD_PUBSUB (1<<5)           /* "p" flag */
  #define CMD_NOSCRIPT (1<<6)         /* "s" flag */
  #define CMD_RANDOM (1<<7)           /* "R" flag */
  #define CMD_SORT_FOR_SCRIPT (1<<8)  /* "S" flag */
  #define CMD_LOADING (1<<9)          /* "l" flag */
  #define CMD_STALE (1<<10)           /* "t" flag */
  #define CMD_SKIP_MONITOR (1<<11)    /* "M" flag */
  #define CMD_ASKING (1<<12)          /* "k" flag */
  #define CMD_FAST (1<<13)            /* "F" flag */
  #define CMD_MODULE_GETKEYS (1<<14)  /* Use the modules getkeys interface. */
  #define CMD_MODULE_NO_CLUSTER (1<<15) /* Deny on Redis Cluster. */
  ```
+ `microseconds`：从服务启动至今命令总的执行时间；通过`microseconds/calls`得到命令平均处理时间，用于统计；
+ `calls`：从服务启动至今命令执行的次数，用于统计；

`redis`服务收到客户端命令时，需要在`redisCommandTable`表查找命令，时间复杂度`O(n)`。为了提高查询效率，在服务启动阶段，
会将`redisCommandTable`转为字典存储在`redisServer->commands`中，其中`key`为命令名字，`value`为对应的`redisCommand`对象；
```c
/* Populates the Redis Command Table starting from the hard coded list
 * we have on top of redis.c file. */
void populateCommandTable(void) {
    int j;
    int numcommands = sizeof(redisCommandTable)/sizeof(struct redisCommand);

    for (j = 0; j < numcommands; j++) {
        struct redisCommand *c = redisCommandTable+j;
        char *f = c->sflags;
        int retval1, retval2;

        while(*f != '\0') {
            switch(*f) {
            case 'w': c->flags |= CMD_WRITE; break;
            case 'r': c->flags |= CMD_READONLY; break;
            case 'm': c->flags |= CMD_DENYOOM; break;
            case 'a': c->flags |= CMD_ADMIN; break;
            case 'p': c->flags |= CMD_PUBSUB; break;
            case 's': c->flags |= CMD_NOSCRIPT; break;
            case 'R': c->flags |= CMD_RANDOM; break;
            case 'S': c->flags |= CMD_SORT_FOR_SCRIPT; break;
            case 'l': c->flags |= CMD_LOADING; break;
            case 't': c->flags |= CMD_STALE; break;
            case 'M': c->flags |= CMD_SKIP_MONITOR; break;
            case 'k': c->flags |= CMD_ASKING; break;
            case 'F': c->flags |= CMD_FAST; break;
            default: serverPanic("Unsupported command flag"); break;
            }
            f++;
        }

        retval1 = dictAdd(server.commands, sdsnew(c->name), c);
        /* Populate an additional dictionary that will be unaffected
         * by rename-command statements in redis.conf. */
        retval2 = dictAdd(server.orig_commands, sdsnew(c->name), c);
        serverAssert(retval1 == DICT_OK && retval2 == DICT_OK);
    }
}
```
为了进一步提高命令查找效率，对于常用命令，`redis`在服务启动阶段会将对应命令对象缓存在`redisServer`对象中，进而不需要从`commands`字典查找：
```c
/* Fast pointers to often looked up command */
struct redisCommand *delCommand, *multiCommand, *lpushCommand,
                    *lpopCommand, *rpopCommand, *zpopminCommand,
                    *zpopmaxCommand, *sremCommand, *execCommand,
                    *expireCommand, *pexpireCommand, *xclaimCommand,
                    *xgroupCommand;
```

### 事件
`redis`的核心是事件循环，`redis`抽象的事件循环对象`aeEventLoop`定义如下：
```c
typedef struct aeEventLoop {
    int maxfd;   /* highest file descriptor currently registered */
    int setsize; /* max number of file descriptors tracked */
    long long timeEventNextId;
    time_t lastTime;     /* Used to detect system clock skew */
    aeFileEvent *events; /* Registered events */
    aeFiredEvent *fired; /* Fired events */
    aeTimeEvent *timeEventHead;
    int stop;
    void *apidata; /* This is used for polling API specific data */
    aeBeforeSleepProc *beforesleep;
    aeBeforeSleepProc *aftersleep;
} aeEventLoop;
```
+ `setsize`：最多同时处理客户端数；
+ `stop`：表示事件循环是否结束；
+ `events`：文件事件数组（`socker`可读可写事件），存储已注册的文件事件；
+ `fired`：存储被触发的文件事件；
+ `timeEventHead`：存放时间事件链表头节点；`redis`有多个时间事件，用链表存储；
+ `apidata`：`redis`底层可能使用不同的`IO`多路复用模型（`epoll`、`select`等），`apidata`是对不同`IO`复用多路模型统一封装；
+ `beforesleep`：没有事件发生的时候，`redis`会阻塞，在阻塞之前会调用`beforesleep`函数；
+ `aftersleep`：有事件发生，`redis`进程会被唤醒，唤醒之后会调用`aftersleep`函数；

`redis`事件主要有两种：**文件事件（`socket`读写事件）**和**时间事件**。其中文件事件`aeFileEvent`的定义如下：
```c
typedef struct aeFileEvent {
    int mask; /* one of AE_(READABLE|WRITABLE|BARRIER) */
    aeFileProc *rfileProc;
    aeFileProc *wfileProc;
    void *clientData;
} aeFileEvent;
```
+ `mask`：文件事件类型，取值`AE_READABLE`（可读）、`AE_WRITABLE`（可写）和`AE_BARRIER`；
+ `rfileProc`：函数指针，指向读事件处理函数；
+ `wfileProc`：函数指针，指向写事件处理函数；
+ `clientData`：对应的客户端对象；

时间事件`aeTimeEvent`定义如下：
```c
typedef struct aeTimeEvent {
    long long id; /* time event identifier. */
    long when_sec; /* seconds */
    long when_ms; /* milliseconds */
    aeTimeProc *timeProc;
    aeEventFinalizerProc *finalizerProc;
    void *clientData;
    struct aeTimeEvent *prev;
    struct aeTimeEvent *next;
} aeTimeEvent;
```
+ `id`：时间事件的唯一`ID`，通过`aeEventLoop->timeEventNextId`实现；
+ `when_sec`：时间事件触发的秒数；
+ `when_ms`：时间事件触发的微妙数；
+ `timeProc`：函数指针，指向时间事件处理函数；
+ `finalizerProc`：函数指针，删除时间事件节点前调用此函数；
+ `clientData`：对应的客户端对象；
+ `prev`：指向前一个时间事件节点；
+ `next`：指向下一个时间事件节点；

## 服务启动
`redis`服务启动流程介绍不涉及集群模式（哨兵模式和集群模式）及持久化（`AOF`和`RDB`），后续有相关章节单独介绍。

### 初始化配置
服务配置初始化主要是初始化设置`redisServer`对象的相关字段，主要由函数`initServerConfig`实现：
```c
void initServerConfig(void) {
    ...
    // serverCron 函数（定时事件函数）执行频率，默认 CONFIG_DEFAULT_HZ=10
    server.hz = server.config_hz = CONFIG_DEFAULT_HZ;
    // 监听端口号，默认 CONFIG_DEFAULT_SERVER_PORT=6379
    server.port = CONFIG_DEFAULT_SERVER_PORT;
    // listen 函数的 backlog 参数值，默认 CONFIG_DEFAULT_TCP_BACKLOG=511
    server.tcp_backlog = CONFIG_DEFAULT_TCP_BACKLOG;
    // 数据库数目，默认 CONFIG_DEFAULT_DBNUM=16
    server.dbnum = CONFIG_DEFAULT_DBNUM;
    // 客户端超时时间，默认 CONFIG_DEFAULT_CLIENT_TIMEOUT=0，表示没有超时时间
    server.maxidletime = CONFIG_DEFAULT_CLIENT_TIMEOUT;
    // 最大同时连接的客户端数目，默认 CONFIG_DEFAULT_MAX_CLIENTS=10000
    server.maxclients = CONFIG_DEFAULT_MAX_CLIENTS;
    ...
    // 将 redisCommandTable 数组中所有命令转存在 server->commands 字典，提高命令查找效率，
    // 上面的命令小节有介绍
    populateCommandTable();
    // 初始化删除命令，使得后续此命令可直接读取，不需要查询 server->commands 字典
    server.delCommand = lookupCommandByCString("del");
    ...
}
```
初始化常用命令，提高命令查询效率，避免从字典查找，例如初始化删除命令函数`lookupCommandByCString`实现如下：
```c
struct redisCommand *lookupCommandByCString(char *s) {
    struct redisCommand *cmd;
    sds name = sdsnew(s);

    cmd = dictFetchValue(server.commands, name);
    sdsfree(name);
    return cmd;
}
```

### 加载解析配置文件
加载解析配置文件的函数是`loadServerConfig`，实现如下：
```c
void loadServerConfig(char *filename, char *options) {
    // 创建空的 sds 字符串对象，存放解析后的配置文件内容
    sds config = sdsempty();
    // 一个缓存数组，存放配置文件一行内容，配置文件一行字符数不超过 CONFIG_MAX_LINE=1024 个
    char buf[CONFIG_MAX_LINE+1];

    /* Load the file content */
    if (filename) {
        FILE *fp;

        if (filename[0] == '-' && filename[1] == '\0') {
            fp = stdin;
        } else {
            if ((fp = fopen(filename,"r")) == NULL) {
                serverLog(LL_WARNING,
                    "Fatal error, can't open config file '%s'", filename);
                exit(1);
            }
        }
        // fgets 从流 fp 读取一行，存放在 buf 指定的字符数组，当读取 (CONFIG_MAX_LINE+1)-1 个字符，
        // 或者遇到换行符，或者到达文件末尾则停止
        while(fgets(buf,CONFIG_MAX_LINE+1,fp) != NULL)
            config = sdscat(config,buf);
        if (fp != stdin) fclose(fp);
    }
    /* Append the additional options */
    // 如果启动服务命令行后有输入配置参数，换行追加到 config 后
    if (options) {
        config = sdscat(config,"\n");
        config = sdscat(config,options);
    }
    // 解析配置
    loadServerConfigFromString(config);
    sdsfree(config);
}
```
+ `filename`：配置文件路径；
+ `options`：命令行输入的配置参数，例如使用如下命令启动服务：
  ```bash
  /home/user/redis/redis-server /home/user/redis/redis.conf -p 4000
  ```
加载完配置文件后，会调用`loadServerConfigFromString`函数进行解析：
```c
void loadServerConfigFromString(char *config) {
    char *err = NULL;
    int linenum = 0, totlines, i;
    int slaveof_linenum = 0;
    sds *lines;
    // 将加载的配置按 "\n" 分割为多行，totlines 是总行数
    lines = sdssplitlen(config,strlen(config),"\n",1,&totlines);

    for (i = 0; i < totlines; i++) {
        sds *argv;
        int argc;

        linenum = i+1;
        lines[i] = sdstrim(lines[i]," \t\r\n");

        /* Skip comments and blank lines */
        // 跳过注释行和空行
        if (lines[i][0] == '#' || lines[i][0] == '\0') continue;

        /* Split into arguments */
        argv = sdssplitargs(lines[i],&argc);
        if (argv == NULL) {
            err = "Unbalanced quotes in configuration line";
            goto loaderr;
        }

        /* Skip this line if the resulting command vector is empty. */
        if (argc == 0) {
            sdsfreesplitres(argv,argc);
            continue;
        }
        sdstolower(argv[0]);

        /* Execute config directives */
        if (!strcasecmp(argv[0],"timeout") && argc == 2) {
            server.maxidletime = atoi(argv[1]);
            if (server.maxidletime < 0) {
                err = "Invalid timeout value"; goto loaderr;
            }
        }
        // 其他配置
        ...
    }
    ...
}
```
`loadServerConfigFromString`主要读取配置文件中的各个参数，并更新`redisServer`对象。

### 初始化服务
服务初始化由`initServer`函数实现，`initServer`样例说明如下：
```c
void initServer(void) {
    int j;

    signal(SIGHUP, SIG_IGN);
    signal(SIGPIPE, SIG_IGN);
    // 注册信号处理函数
    setupSignalHandlers();

    if (server.syslog_enabled) {
        openlog(server.syslog_ident, LOG_PID | LOG_NDELAY | LOG_NOWAIT,
            server.syslog_facility);
    }

    // serverCron 函数（定时事件函数）执行频率，默认 10
    server.hz = server.config_hz;
    server.pid = getpid();
    server.current_client = NULL;
    // 创建一个链表，存放所有连接的客户端对象
    server.clients = listCreate();
    // 创建一个 rax 数，存放每个客户端的 ID
    server.clients_index = raxNew();
    ...
    createSharedObjects();
    adjustOpenFilesLimit();
    ...
    // 初始化数据库
    server.db = zmalloc(sizeof(redisDb)*server.dbnum);
    ...
    /* Create the Redis databases, and initialize other internal state. */
    for (j = 0; j < server.dbnum; j++) {
        server.db[j].dict = dictCreate(&dbDictType,NULL);
        server.db[j].expires = dictCreate(&keyptrDictType,NULL);
        server.db[j].blocking_keys = dictCreate(&keylistDictType,NULL);
        server.db[j].ready_keys = dictCreate(&objectKeyPointerValueDictType,NULL);
        server.db[j].watched_keys = dictCreate(&keylistDictType,NULL);
        server.db[j].id = j;
        server.db[j].avg_ttl = 0;
        server.db[j].defrag_later = listCreate();
    }
    ...
}
```
根据上面数据结构定义小节可知，`redis`的对象`redisObject`有一个`refcount`字段表示对象的引用次数，可以用于对象的共享。
服务初始化阶段会调用函数`createSharedObjects`创建一些共享对象，`createSharedObjects`函数主要是对`sharedObjectsStruct`结构体进行初始化设置。
```c
struct sharedObjectsStruct {
    robj *crlf, *ok, *err, *emptybulk, *czero, *cone, *cnegone, *pong, *space,
    *colon, *nullbulk, *nullmultibulk, *queued,
    *emptymultibulk, *wrongtypeerr, *nokeyerr, *syntaxerr, *sameobjecterr,
    *outofrangeerr, *noscripterr, *loadingerr, *slowscripterr, *bgsaveerr,
    *masterdownerr, *roslaveerr, *execaborterr, *noautherr, *noreplicaserr,
    *busykeyerr, *oomerr, *plus, *messagebulk, *pmessagebulk, *subscribebulk,
    *unsubscribebulk, *psubscribebulk, *punsubscribebulk, *del, *unlink,
    *rpop, *lpop, *lpush, *rpoplpush, *zpopmin, *zpopmax, *emptyscan,
    *select[PROTO_SHARED_SELECT_CMDS],
    *integers[OBJ_SHARED_INTEGERS],
    *mbulkhdr[OBJ_SHARED_BULKHDR_LEN], /* "*<value>\r\n" */
    *bulkhdr[OBJ_SHARED_BULKHDR_LEN];  /* "$<value>\r\n" */
    sds minstring, maxstring;
};
```

### 创建事件循环

### 创建socket并启动监听

### 创建文件事件和时间时间

### 开启事件循环

## 命令处理流程

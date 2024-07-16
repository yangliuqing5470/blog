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
  如果是`LFU`策略，则`lru`低`8`位更新为频率值，高`16`位为对象上次访问时间，以分钟单位。需要注意的是，是通过`LFUDecrAndReturn`函数获取对象访问频率，
  并在此基础上累积，原因是因为越老的数据一般被访问次数越大，越新的数据被访问次数越少，即使老的数据很久没被访问，这是不公平的。所以，
  `LFUDecrAndReturn`函数实现了访问次数随时间衰减的过程；
+ `refcount`：当前对象的引用次数，用于对象的共享；共享对象时，`refcount`值加`1`；删除对象时，`refcount`值减`1`；当`refcount`值为`0`时，
会释放对象；
+ `ptr`：指向对象底层存储的数据结构，当存储的数据长度小于等于`20`且可以表示为一个`long`类型的整数时或者字符串长度小于等于`44`时，数据则直接存储在`ptr`字段；
正常情况下，为了存储一个字符串对象，需要两次内存分配，一次是`redisObject`对象分配，一次是`sds`分配。因此对于字符串较短，
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
根据上面数据结构定义小节可知，`redis`对象`redisObject`有一个`refcount`字段表示对象的引用次数，可以用于对象的共享。
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
其中`integers`整数数组存放`0-10000`的整数，且其中每一个整数对象`refcount`值设置为`INT_MAX`，确保不会被释放：
```c
// OBJ_SHARED_INTEGERS = 10000
for (j = 0; j < OBJ_SHARED_INTEGERS; j++) {
    shared.integers[j] =
        makeObjectShared(createObject(OBJ_STRING,(void*)(long)j));
    shared.integers[j]->encoding = OBJ_ENCODING_INT;
}

// 更新 refcount 值为 INT_MAX
robj *makeObjectShared(robj *o) {
    serverAssert(o->refcount == 1);
    o->refcount = OBJ_SHARED_REFCOUNT;
    return o;
}

#define OBJ_SHARED_REFCOUNT INT_MAX
```
在`initServer`函数中默认会初始化`server.dbnum=16`个数据库，以初始化数据库`dict`属性为例，其字典的`type`属性是`dbDictType`对象，
定义了字典键的哈希函数，键比较函数及键和值的销毁函数：
```c
dictType dbDictType = {
    dictSdsHash,                /* hash function */
    NULL,                       /* key dup */
    NULL,                       /* val dup */
    dictSdsKeyCompare,          /* key compare */
    dictSdsDestructor,          /* key destructor */
    dictObjectDestructor   /* val destructor */
};
```

### 创建事件循环
在`initServer`函数中，也会完成时间循环的创建：
```c
// CONFIG_FDSET_INCR = 128
server.el = aeCreateEventLoop(server.maxclients+CONFIG_FDSET_INCR);
```
函数`aeCreateEventLoop`的实现如下：
```c
aeEventLoop *aeCreateEventLoop(int setsize) {
    aeEventLoop *eventLoop;
    int i;

    if ((eventLoop = zmalloc(sizeof(*eventLoop))) == NULL) goto err;
    // 分配存放文件事件对象的数组大小
    eventLoop->events = zmalloc(sizeof(aeFileEvent)*setsize);
    // 分配存放被触发的文件事件对象的数组大小
    eventLoop->fired = zmalloc(sizeof(aeFiredEvent)*setsize);
    if (eventLoop->events == NULL || eventLoop->fired == NULL) goto err;
    eventLoop->setsize = setsize;
    eventLoop->lastTime = time(NULL);
    // 时间事件链表头节点初始化
    eventLoop->timeEventHead = NULL;
    eventLoop->timeEventNextId = 0;
    eventLoop->stop = 0;
    eventLoop->maxfd = -1;
    eventLoop->beforesleep = NULL;
    eventLoop->aftersleep = NULL;
    // 初始化 apidata 对象，表示不同的 IO 多路复用对象封装
    if (aeApiCreate(eventLoop) == -1) goto err;
    /* Events with mask == AE_NONE are not set. So let's initialize the
     * vector with it. */
    for (i = 0; i < setsize; i++)
        eventLoop->events[i].mask = AE_NONE;
    return eventLoop;

err:
    if (eventLoop) {
        zfree(eventLoop->events);
        zfree(eventLoop->fired);
        zfree(eventLoop);
    }
    return NULL;
}
```
`aeCreateEventLoop`主要完成对事件循环对象`aeEventLoop`的成员初始化，其中`setsize`参数表示用户配置的最大同时连接的客户端数目。
函数`aeApiCreate`内部会调用`epoll_create`创建`epoll`对象（对于`linux`系统），并更新事件循环对象的`eventloop->apidata`属性：
```c
typedef struct aeApiState {
    int epfd;
    struct epoll_event *events;
} aeApiState;

static int aeApiCreate(aeEventLoop *eventLoop) {
    aeApiState *state = zmalloc(sizeof(aeApiState));

    if (!state) return -1;
    state->events = zmalloc(sizeof(struct epoll_event)*eventLoop->setsize);
    if (!state->events) {
        zfree(state);
        return -1;
    }
    state->epfd = epoll_create(1024); /* 1024 is just a hint for the kernel */
    if (state->epfd == -1) {
        zfree(state->events);
        zfree(state);
        return -1;
    }
    eventLoop->apidata = state;
    return 0;
}
```

### 创建socket并启动监听
在`initServer`内部，也会完成对服务器地址的监听（`ip + port`），完成和客户端基于`socket`通信的准备工作：
```c
/* Open the TCP listening socket for the user commands. */
if (server.port != 0 &&
    listenToPort(server.port,server.ipfd,&server.ipfd_count) == C_ERR)
    exit(1);
```
+ `server.ipfd`：一个数组，存放监听绑定的`socket`文件描述符；
+ `server.ipfd_count`：`server.ipfd`数组最后一个元素的下标，初始值是`0`；

`listenToPort`函数主要实现如下（只给出了`IPV4`相关实现）：
```c
/* Bind IPv4 address. */
fds[*count] = anetTcpServer(server.neterr,port,server.bindaddr[j],
    server.tcp_backlog);
// 将 socket 设置为非阻塞
anetNonBlock(NULL,fds[*count]);
(*count)++;
```
`listenToPort`内部首先调用`anetTcpServer`函数创建监听`socket`并完成绑定监听，然后调用`anetNonBlock`将监听`socket`设置为非阻塞。
函数`anetTcpServer`实现如下：
```c
int anetTcpServer(char *err, int port, char *bindaddr, int backlog)
{
    return _anetTcpServer(err, port, bindaddr, AF_INET, backlog);
}

static int _anetTcpServer(char *err, int port, char *bindaddr, int af, int backlog)
{
    int s = -1, rv;
    char _port[6];  /* strlen("65535") */
    struct addrinfo hints, *servinfo, *p;

    snprintf(_port,6,"%d",port);
    memset(&hints,0,sizeof(hints));
    hints.ai_family = af;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_flags = AI_PASSIVE;    /* No effect if bindaddr != NULL */

    if ((rv = getaddrinfo(bindaddr,_port,&hints,&servinfo)) != 0) {
        anetSetError(err, "%s", gai_strerror(rv));
        return ANET_ERR;
    }
    for (p = servinfo; p != NULL; p = p->ai_next) {
        // 创建监听 socket
        if ((s = socket(p->ai_family,p->ai_socktype,p->ai_protocol)) == -1)
            continue;

        if (af == AF_INET6 && anetV6Only(err,s) == ANET_ERR) goto error;
        // 设置地址重用
        if (anetSetReuseAddr(err,s) == ANET_ERR) goto error;
        // 绑定和监听端口
        if (anetListen(err,s,p->ai_addr,p->ai_addrlen,backlog) == ANET_ERR) s = ANET_ERR;
        goto end;
    }
    if (p == NULL) {
        anetSetError(err, "unable to bind socket, errno: %d", errno);
        goto error;
    }

error:
    if (s != -1) close(s);
    s = ANET_ERR;
end:
    freeaddrinfo(servinfo);
    return s;
}
```
`anetTcpServer`服务内部会完成如下工作：
+ 创建监听`socket`；
+ 将`socket`设置地址重用；
+ 调用`bind`和`listen`完成绑定和监听；

对于`unix domain socket`，其初始化操作如下，这里不做详细介绍：
```c
/* Open the listening Unix domain socket. */
if (server.unixsocket != NULL) {
    unlink(server.unixsocket); /* don't care if this fails */
    server.sofd = anetUnixServer(server.neterr,server.unixsocket,
        server.unixsocketperm, server.tcp_backlog);
    if (server.sofd == ANET_ERR) {
        serverLog(LL_WARNING, "Opening Unix socket: %s", server.neterr);
        exit(1);
    }
    anetNonBlock(NULL,server.sofd);
}
```

### 创建文件事件和时间事件
完成对监听`socket`的创建、绑定及监听后，`initServer`会继续创建文件事件（`socket`读写事件）：
```c
/* Create an event handler for accepting new connections in TCP and Unix
 * domain sockets. */
for (j = 0; j < server.ipfd_count; j++) {
    if (aeCreateFileEvent(server.el, server.ipfd[j], AE_READABLE,
        acceptTcpHandler,NULL) == AE_ERR)
        {
            serverPanic(
                "Unrecoverable error creating server.ipfd file event.");
        }
}
```
创建文件事件`aeCreateEventLoop`函数实现如下：
```c
int aeCreateFileEvent(aeEventLoop *eventLoop, int fd, int mask,
        aeFileProc *proc, void *clientData)
{
    // 确保 socker 文件描述符不能超过用户配置的最大值
    if (fd >= eventLoop->setsize) {
        errno = ERANGE;
        return AE_ERR;
    }
    // 文件描述符对应的文件事件初始对象
    aeFileEvent *fe = &eventLoop->events[fd];
    // 调用 epoll_ctl 完成对事件的注册
    if (aeApiAddEvent(eventLoop, fd, mask) == -1)
        return AE_ERR;
    // 更新 aeFileEvent 对象其他属性，例如设置事件处理函数，事件类型等
    fe->mask |= mask;
    if (mask & AE_READABLE) fe->rfileProc = proc;
    if (mask & AE_WRITABLE) fe->wfileProc = proc;
    fe->clientData = clientData;
    if (fd > eventLoop->maxfd)
        eventLoop->maxfd = fd;
    return AE_OK;
}
```
事件处理函数`acceptTcpHandler`主要完成`accept`操作和客户端对象的创建。客户端对象的创建函数`createClient`实现样例如下：
```c
client *createClient(int fd) {
    client *c = zmalloc(sizeof(client));

    /* passing -1 as fd it is possible to create a non connected client.
     * This is useful since all the commands needs to be executed
     * in the context of a client. When commands are executed in other
     * contexts (for instance a Lua script) we need a non connected client. */
    if (fd != -1) {
        // 将和客户端通信的 socket 设置非阻塞
        anetNonBlock(NULL,fd);
        // 设置 TCP_NODELAY 标志
        anetEnableTcpNoDelay(NULL,fd);
        if (server.tcpkeepalive)
            // 设置 SO_KEEPALIVE 属性
            anetKeepAlive(NULL,fd,server.tcpkeepalive);
        // 注册和客户端通信的 socket 读事件，事件处理函数是 readQueryFromClient
        if (aeCreateFileEvent(server.el,fd,AE_READABLE,
            readQueryFromClient, c) == AE_ERR)
        {
            close(fd);
            zfree(c);
            return NULL;
        }
    }
    // 默认选择 0 号数据库
    selectDb(c,0);
    uint64_t client_id;
    atomicGetIncr(server.next_client_id,client_id,1);
    // 更新客户端其他属性，例如客户端 id等
    c->id = client_id;
    c->fd = fd;
    ...
}
```
`TCP`是基于字节流的可靠传输层协议，为了提升网络利用率，一般默认都会开启`Nagle`。当应用层调用`write`函数发送数据时，
`TCP`并不一定立刻将数据发送出去，根据`Nagle`算法，须满足一定条件。`Nagle`是这样规定的：
+ 如果数据包长度大于一定门限时，则立即发送；
+ 如果数据包中含有`FIN`（表示断开`TCP`链接）字段，则立即发送；
+ 如果当前设置了`TCP_NODELAY`选项，则立即发送；
+ 如果以上所有条件都不满足，则默认需要等待`200`毫秒超时后才会发送；

`redis`服务器向客户端返回命令回复时，希望`TCP`能立即将该回复发送给客户端，因此需要设置`TCP_NODELAY`。如果不设置，从客户端分析，命令请求的响应时间会大大加长。

`TCP`是可靠的传输层协议，每次都需要经历“三次握手”与“四次挥手”，为了提升效率，可以设置`SO_KEEPALIVE`，即`TCP`长连接，
这样`TCP`传输层会定时发送心跳包确认该连接的可靠性。应用层也不再需要频繁地创建与释放`TCP`连接了。

和客户端通信的`socket`读事件处理函数是`readQueryFromClient`，在下一小节开启事件循环会详细介绍。


接下来我们看下在`initServer`内部创建时间事件的相关实现：
```c
/* Create the timer callback, this is our way to process many background
 * operations incrementally, like clients timeout, eviction of unaccessed
 * expired keys and so forth. */
// 创建一个 1ms 后触发的时间事件
if (aeCreateTimeEvent(server.el, 1, serverCron, NULL, NULL) == AE_ERR) {
    serverPanic("Can't create event loop timers.");
    exit(1);
}
```
创建时间事件`aeCreateTimeEvent`函数的实现如下：
```c
long long aeCreateTimeEvent(aeEventLoop *eventLoop, long long milliseconds,
        aeTimeProc *proc, void *clientData,
        aeEventFinalizerProc *finalizerProc)
{
    // 时间事件节点 id
    long long id = eventLoop->timeEventNextId++;
    aeTimeEvent *te;

    te = zmalloc(sizeof(*te));
    if (te == NULL) return AE_ERR;
    te->id = id;
    // 更新 aeTimeEvent 对象的各个属性
    aeAddMillisecondsToNow(milliseconds,&te->when_sec,&te->when_ms);
    te->timeProc = proc;
    te->finalizerProc = finalizerProc;
    te->clientData = clientData;
    te->prev = NULL;
    // 将节点放在链表头
    te->next = eventLoop->timeEventHead;
    if (te->next)
        te->next->prev = te;
    // 更新事件循环时间事件链表头
    eventLoop->timeEventHead = te;
    return id;
}
```
时间事件用链表存储，每个时间事件都是链表中一个节点，新创建的时间事件节点都放在链表头。时间事件处理函数是`serverCron`，
`serverCron`函数实现了`redis`服务所有定时任务的周期执行。`serverCron`函数部分样例代码如下：
```c
int serverCron(struct aeEventLoop *eventLoop, long long id, void *clientData) {
    ...
    run_with_period(100) {
        // 100ms 周期执行
        ...
    }
    run_with_period(5000) {
        // 5s 周期执行
        ...
    }
    /* We need to do a few operations on clients asynchronously. */
    // 清除超时客户端连接
    clientsCron();

    /* Handle background operations on Redis databases. */
    // 处理数据库，例如清理过期键等
    databasesCron();
    ...
    server.cronloops++;
    return 1000/server.hz;
}
```
`server.cronloops`记录函数`serverCron`执行次数，`server.hz`表示`serverCron`函数执行频率（一秒执行多少次）。
`serverCron`函数返回值`1000/server.hz`表示当前`serverCron`执行周期（在`processTimeEvents`函数调用时间事件处理函数会用次返回值更新时间事件执行周期）。
`run_with_period`宏定义了定时任务按照指定时间周期（`_ms_`）执行，宏定义如下：
```c
/* Using the following macro you can run code inside serverCron() with the
 * specified period, specified in milliseconds.
 * The actual resolution depends on server.hz. */
#define run_with_period(_ms_) if ((_ms_ <= 1000/server.hz) || !(server.cronloops%((_ms_)/(1000/server.hz))))
```
`serverCron`函数执行时间不能太长，否则可能会影响客户端命令响应。下面以过期键删除为例子，说明`serverCron`函数执行时间不能太长。
过期键删除通过`activeExpireCycle`函数实现，其由`databasesCron`函数调用。`activeExpireCycle`实现部分样例代码如下：
```c
void activeExpireCycle(int type) {
    ...
    // CRON_DBS_PER_CALL=16，此函数每次执行最多遍历数据库个数 dbs_per_call
    int dbs_per_call = CRON_DBS_PER_CALL;
    ...
    /* We can use at max ACTIVE_EXPIRE_CYCLE_SLOW_TIME_PERC percentage of CPU time
     * per iteration. Since this function gets called with a frequency of
     * server.hz times per second, the following is the max amount of
     * microseconds we can spend in this function. */
    timelimit = 1000000*ACTIVE_EXPIRE_CYCLE_SLOW_TIME_PERC/server.hz/100;
    timelimit_exit = 0;
    ...
    // 遍历查找每一个数据库
    for (j = 0; j < dbs_per_call && timelimit_exit == 0; j++) {
        int expired;
        redisDb *db = server.db+(current_db % server.dbnum);
        ...
        /* Continue to expire if at the end of the cycle more than 25%
         * of the keys were expired. */
        // 处理一个数据库中的过期键
        do {
            ...
            iteration++;
            ...
            /* The main collection cycle. Sample random keys among keys
             * with an expire set, checking for expired ones. */
            // 处理的过期键个数
            expired = 0;
            ttl_sum = 0;
            ttl_samples = 0;
            // ACTIVE_EXPIRE_CYCLE_LOOKUPS_PER_LOOP = 20，表示一个数据库中过期键一次处理的最大数
            if (num > ACTIVE_EXPIRE_CYCLE_LOOKUPS_PER_LOOP)
                num = ACTIVE_EXPIRE_CYCLE_LOOKUPS_PER_LOOP;
            // 一次最多处理 num 个过期键
            while (num--) {
                dictEntry *de;
                long long ttl;

                if ((de = dictGetRandomKey(db->expires)) == NULL) break;
                ttl = dictGetSignedIntegerVal(de)-now;
                if (activeExpireCycleTryExpire(db,de,now)) expired++;
                ...
            }
            ...
            // 一个数据库每迭代处理 16 次，检查是否超时
            if ((iteration & 0xf) == 0) { /* check once every 16 iterations. */
                elapsed = ustime()-start;
                if (elapsed > timelimit) {
                    timelimit_exit = 1;
                    server.stat_expired_time_cap_reached_count++;
                    break;
                }
            }
        } while (expired > ACTIVE_EXPIRE_CYCLE_LOOKUPS_PER_LOOP/4);
    }
    ...
}
```
函数`activeExpireCycle`最多遍历`dbs_per_call`个数据库，并限制每个数据库每次执行删除最多过期键数目为`20`（如果一个数据库过期键太多，在`do-while`中分多次执行）。
同时为了避免每个数据库执行时间太长（`do-while`循环执行太久），会每个`do-while`执行`16`次迭代就检查函数`activeExpireCycle`耗费时间是否超时，如果超过就退出此函数。
超时时间`timelimit`计算如下：
```c
// ACTIVE_EXPIRE_CYCLE_SLOW_TIME_PERC = 25
// 1000000 表示 1s
timelimit = 1000000*ACTIVE_EXPIRE_CYCLE_SLOW_TIME_PERC/server.hz/100;
```
`timelimit`结果表示`activeExpireCycle`函数执行时间占`CPU`时间`25%`，也就是每秒里面函数`activeExpireCycle`执行时间最多`1000000/25/100`微妙，
每秒钟函数`activeExpireCycle`执行`server.hz`次，所以每次`activeExpireCycle`执行时间就是`timelimit`值。

如果因为超时退出，下次调用`activeExpireCycle`会接着从上次位置继续执行，直到把所有数据库过期键删除。

### 开启事件循环
在`initServer`最后会启动事件循环。通过调用`aeMain`函数实现：
```c
void aeMain(aeEventLoop *eventLoop) {
    eventLoop->stop = 0;
    while (!eventLoop->stop) {
        if (eventLoop->beforesleep != NULL)
            eventLoop->beforesleep(eventLoop);
        // 事件处理函数
        aeProcessEvents(eventLoop, AE_ALL_EVENTS|AE_CALL_AFTER_SLEEP);
    }
}
```
事件循环主要做两件事：
+ 处理事件之前执行`eventLoop->beforesleep`函数；
+ 执行处理事件函数；

先看下处理事件函数`aeProcessEvents`实现，`aeProcessEvents`函数定义如下：
```c
/* Process every pending time event, then every pending file event
 * (that may be registered by time event callbacks just processed).
 * Without special flags the function sleeps until some file event
 * fires, or when the next time event occurs (if any).
 *
 * If flags is 0, the function does nothing and returns.
 * if flags has AE_ALL_EVENTS set, all the kind of events are processed.
 * if flags has AE_FILE_EVENTS set, file events are processed.
 * if flags has AE_TIME_EVENTS set, time events are processed.
 * if flags has AE_DONT_WAIT set the function returns ASAP until all
 * if flags has AE_CALL_AFTER_SLEEP set, the aftersleep callback is called.
 * the events that's possible to process without to wait are processed.
 *
 * The function returns the number of events processed. */
int aeProcessEvents(aeEventLoop *eventLoop, int flags);
```
`aeProcessEvents`函数主要完成以下功能：
+ 如果`flags`既不包括时间事件，也不包括文件事件，则直接返回：
  ```c
  /* Nothing to do? return ASAP */
  if (!(flags & AE_TIME_EVENTS) && !(flags & AE_FILE_EVENTS)) return 0;
  ```
+ 如果注册了文件事件，为了在调用`epoll_wait`阻塞期间可以执行到期的定时任务，函数在调用`aeApiPoll`之前会先遍历时间事件列表，
查找最早发生的时间事件，以此计算得到`aeApiPoll`函数的超时时间，具体实现如下：
  ```c
  // eventLoop->maxfd != -1 说明已经注册过文件事件
  if (eventLoop->maxfd != -1 ||
      ((flags & AE_TIME_EVENTS) && !(flags & AE_DONT_WAIT))) {
      int j;
      aeTimeEvent *shortest = NULL;
      struct timeval tv, *tvp;

      if (flags & AE_TIME_EVENTS && !(flags & AE_DONT_WAIT))
          // 查找最早发生的时间事件
          shortest = aeSearchNearestTimer(eventLoop);
      if (shortest) {
          long now_sec, now_ms;

          aeGetTime(&now_sec, &now_ms);
          tvp = &tv;

          long long ms =
              (shortest->when_sec - now_sec)*1000 +
              shortest->when_ms - now_ms;
          // 设置 aeApiPoll 函数的超时时间
          if (ms > 0) {
              // 当前没有到期的时间事件
              tvp->tv_sec = ms/1000;
              tvp->tv_usec = (ms % 1000)*1000;
          } else {
              // 当前有到期的时间事件
              tvp->tv_sec = 0;
              tvp->tv_usec = 0;
          }
      } else {
          // 没有时间事件，也就是时间事件的链表为空
          if (flags & AE_DONT_WAIT) {
              tv.tv_sec = tv.tv_usec = 0;
              tvp = &tv;
          } else {
              /* Otherwise we can block */
              tvp = NULL; /* wait forever */
          }
      }
      // 内部会调用 epoll_wait 获取发生的事件，将发生的事件存放在 eventLoop->fires 字典
      numevents = aeApiPoll(eventLoop, tvp);

      /* After sleep callback. */
      // 有事件触发，调用注册的 aftersleep 函数
      if (eventLoop->aftersleep != NULL && flags & AE_CALL_AFTER_SLEEP)
          eventLoop->aftersleep(eventLoop);
      // 处理发生的文件事件
      for (j = 0; j < numevents; j++) {
          // 已注册的文件事件
          aeFileEvent *fe = &eventLoop->events[eventLoop->fired[j].fd];
          // 触发的文件事件类型
          int mask = eventLoop->fired[j].mask;
          // 触发的文件事件描述符
          int fd = eventLoop->fired[j].fd;
          int fired = 0; /* Number of events fired for current fd. */
          // 正常情况下是先处理读事件，然后处理写事件；如果设置 AE_BARRIER 类型，
          // 则先处理写事件，然后处理读事件（AE_BARRIER 含义详细介绍在下面命令处理章节说明）
          int invert = fe->mask & AE_BARRIER;
          // 处理读事件
          if (!invert && fe->mask & mask & AE_READABLE) {
              fe->rfileProc(eventLoop,fd,fe->clientData,mask);
              fired++;
          }
          // 处理写事件
          if (fe->mask & mask & AE_WRITABLE) {
              if (!fired || fe->wfileProc != fe->rfileProc) {
                  fe->wfileProc(eventLoop,fd,fe->clientData,mask);
                  fired++;
              }
          }
          // 设置了 invert，这里开始处理读事件，因为写事件前面处理了
          if (invert && fe->mask & mask & AE_READABLE) {
              if (!fired || fe->wfileProc != fe->rfileProc) {
                  fe->rfileProc(eventLoop,fd,fe->clientData,mask);
                  fired++;
              }
          }
          // 已经处理的事件个数
          processed++;
      }
  }
  ```
  其中查找最早发生的时间事件函数`aeSearchNearestTimer`实现如下，通过遍历时间事件链表，查找到期事件最小的节点：
  ```c
  static aeTimeEvent *aeSearchNearestTimer(aeEventLoop *eventLoop)
  {
      aeTimeEvent *te = eventLoop->timeEventHead;
      aeTimeEvent *nearest = NULL;
  
      while(te) {
          if (!nearest || te->when_sec < nearest->when_sec ||
                  (te->when_sec == nearest->when_sec &&
                   te->when_ms < nearest->when_ms))
              nearest = te;
          te = te->next;
      }
      return nearest;
  }
  ```
  等待事件发生的函数`aeApiPoll`实现如下：
  ```c
  static int aeApiPoll(aeEventLoop *eventLoop, struct timeval *tvp) {
      // 获取封装的 io 多路复用对象，对于 linux 系统就是 epoll
      aeApiState *state = eventLoop->apidata;
      int retval, numevents = 0;
  
      retval = epoll_wait(state->epfd,state->events,eventLoop->setsize,
              tvp ? (tvp->tv_sec*1000 + tvp->tv_usec/1000) : -1);
      // 将发生的事件存放在 eventLoop->fired 字典
      if (retval > 0) {
          int j;
  
          numevents = retval;
          for (j = 0; j < numevents; j++) {
              int mask = 0;
              struct epoll_event *e = state->events+j;
  
              if (e->events & EPOLLIN) mask |= AE_READABLE;
              if (e->events & EPOLLOUT) mask |= AE_WRITABLE;
              if (e->events & EPOLLERR) mask |= AE_WRITABLE;
              if (e->events & EPOLLHUP) mask |= AE_WRITABLE;
              eventLoop->fired[j].fd = e->data.fd;
              eventLoop->fired[j].mask = mask;
          }
      }
      // 返回发生事件个数
      return numevents;
  }
  ```
+ 如果`flags`包含了时间事件标志，调用`processTimeEvents`函数处理时间事件，函数`processTimeEvents`实现如下：
  ```c
  static int processTimeEvents(aeEventLoop *eventLoop) {
      int processed = 0;
      aeTimeEvent *te;
      long long maxId;
      time_t now = time(NULL);
      // 如果系统时间被修改过，更新所有时间事件节点到期时间为0，这样所有的时间事件都会认为到期，在下面都会执行一次
      if (now < eventLoop->lastTime) {
          te = eventLoop->timeEventHead;
          while(te) {
              te->when_sec = 0;
              te = te->next;
          }
      }
      eventLoop->lastTime = now;
  
      te = eventLoop->timeEventHead;
      maxId = eventLoop->timeEventNextId-1;
      while(te) {
          long now_sec, now_ms;
          long long id;
  
          /* Remove events scheduled for deletion. */
          // 在链表中删除当前时间事件节点
          if (te->id == AE_DELETED_EVENT_ID) {
              aeTimeEvent *next = te->next;
              if (te->prev)
                  te->prev->next = te->next;
              else
                  eventLoop->timeEventHead = te->next;
              if (te->next)
                  te->next->prev = te->prev;
              if (te->finalizerProc)
                  // 调用 finalizerProc 函数
                  te->finalizerProc(eventLoop, te->clientData);
              zfree(te);
              te = next;
              continue;
          }
          // 确保在函数执行期间创建的时间事件不会执行
          if (te->id > maxId) {
              te = te->next;
              continue;
          }
          aeGetTime(&now_sec, &now_ms);
          if (now_sec > te->when_sec ||
              (now_sec == te->when_sec && now_ms >= te->when_ms))
          {
              int retval;
  
              id = te->id;
              // 当前的时间事件到期，执行 timeProc 函数，retval 返回是函数 timeProc 处理周期
              retval = te->timeProc(eventLoop, id, te->clientData);
              processed++;
              if (retval != AE_NOMORE) {
                  // 更新当前时间事件下次到期时间
                  aeAddMillisecondsToNow(retval,&te->when_sec,&te->when_ms);
              } else {
                  te->id = AE_DELETED_EVENT_ID;
              }
          }
          te = te->next;
      }
      return processed;
  }
  ```
  `processTimeEvents`函数主要完成以下工作：
  + 针对时间异常，例如系统时间被修改小于次函数上次执行时间，则将链表中所有时间事件到期时间设置为`0`，这样所有的时间事件都会认为到期被执行；
  + 如果时间事件节点需要删除，从链表删除，并执行对应的`finalizerProc`函数；
  + 确保在此函数执行期间注册的时间事件不会执行，直接跳过；
  + 遍历链表，查找到期时间事件，执行注册的`timeProc`函数，并更新此时间事件下次到期时间；

最后看下`eventLoop->beforesleep`函数。在每次事件循环中，`eventLoop->beforesleep`函数在处理事件函数`aeProcessEvents`执行前被调用。
`eventLoop->beforesleep`函数主要做一些不耗时操作，例如集群相关操作，快速过期键删除，给客户端回复数据等。下面以快速过期键删除为例进行简单说明：
```c
void beforeSleep(struct aeEventLoop *eventLoop) {
    ...
    if (server.active_expire_enabled && server.masterhost == NULL)
        activeExpireCycle(ACTIVE_EXPIRE_CYCLE_FAST);
    ...
}
```
`server.masterhost`字段存储当前`redis`服务器的`master`服务器的域名，如果为`NULL`说明当前服务器不是某个`redis`服务器的`slaver`。
`redis`过期键删除有两种策略：
+ 在访问数据库键时，会先检查键是否过期，如果过期则删除；
+ 周期性删除，在`eventLoop->beforesleep`和`serverCron`函数都会执行；

快速过期键删除也是调用`activeExpireCycle`函数，参数传`ACTIVE_EXPIRE_CYCLE_FAST`，下面是部分样例代码实现：
```c
void activeExpireCycle(int type) {
    /* This function has some global state in order to continue the work
     * incrementally across calls. */
    static unsigned int current_db = 0; /* Last DB tested. */
    static int timelimit_exit = 0;      /* Time limit hit in previous call? */
    static long long last_fast_cycle = 0; /* When last fast cycle ran. */
    ...
    if (type == ACTIVE_EXPIRE_CYCLE_FAST) {
        /* Don't start a fast cycle if the previous cycle did not exit
         * for time limit. Also don't repeat a fast cycle for the same period
         * as the fast cycle total duration itself. */
        if (!timelimit_exit) return;
        // ACTIVE_EXPIRE_CYCLE_FAST_DURATION = 1000
        if (start < last_fast_cycle + ACTIVE_EXPIRE_CYCLE_FAST_DURATION*2) return;
        last_fast_cycle = start;
    }
    ...
    if (type == ACTIVE_EXPIRE_CYCLE_FAST)
        timelimit = ACTIVE_EXPIRE_CYCLE_FAST_DURATION; /* in microseconds. */
    ...
}
```
快速过期键删除有以下限制：
+ 如果上次执行函数`activeExpireCycle`没有遇到超时退出，直接返回；因为`timelimit_exit`变量是静态变量，会保留上次结果；
  ```c
  if (!timelimit_exit) return;
  ```
+ 上次执行快速过期键删除的时间距离当前时间小于`2000`微秒时直接返回；也是利用`last_fast_cycle`变量是静态变量；
  ```c
  // ACTIVE_EXPIRE_CYCLE_FAST_DURATION = 1000
  if (start < last_fast_cycle + ACTIVE_EXPIRE_CYCLE_FAST_DURATION*2) return;
  last_fast_cycle = start;
  ```
+ 设置函数`activeExpireCycle`执行的时间限制为`1000`微妙；
  ```c
  if (type == ACTIVE_EXPIRE_CYCLE_FAST)
      timelimit = ACTIVE_EXPIRE_CYCLE_FAST_DURATION; /* in microseconds. */
  ```

## 命令处理流程
### 命令解析与处理
`redis`使用自定义的命令请求协议。例如客户端输入如下命令：
```bash
SET redis-key value1
```
客户端会转为下面格式发送给服务端：
```bash
*3\r\n$3\r\nSET\r\n$9\r\nredis-key\r\n$6\r\nvalue1\r\n
```
其中`\r\n`用于区分命令请求各个参数；`*3`表示该命令请求有三个参数；`$3`、`$9`和`$6`表示该参数字符串长度。

服务端收到客户端命令请求后，会调用`readQueryFromClient`事件处理函数将接收的命令请求存放在客户端对象的`querybuf`输入缓存中。
然后调用`processInputBuffer`函数解析命令。最终解析的命令及参数会存放在客户端对象`client->argc`和`client->argv`参数中。

服务端解析完客户端请求命令后，会调用`processCommand`函数处理命令。`processCommand`首先进行请求命令的各种校验，例如：
+ 如果是`quit`命令，直接返回并关闭客户端对象；
  ```c
  if (!strcasecmp(c->argv[0]->ptr,"quit")) {
      addReply(c,shared.ok);
      c->flags |= CLIENT_CLOSE_AFTER_REPLY;
      return C_ERR;
  }
  ```
+ 查找命令，如果请求的命令不存在，则响应错误并返回；
  ```c
  c->cmd = c->lastcmd = lookupCommand(c->argv[0]->ptr);
  if (!c->cmd) {
      flagTransaction(c);
      sds args = sdsempty();
      int i;
      for (i=1; i < c->argc && sdslen(args) < 128; i++)
          args = sdscatprintf(args, "`%.*s`, ", 128-(int)sdslen(args), (char*)c->argv[i]->ptr);
      addReplyErrorFormat(c,"unknown command `%s`, with args beginning with: %s",
          (char*)c->argv[0]->ptr, args);
      sdsfree(args);
      return C_OK;
  }
  ```
  其中查找命令`lookupCommand`主要就是查找`server.commands`字典，实现如下：
  ```c
  struct redisCommand *lookupCommand(sds name) {
      return dictFetchValue(server.commands, name);
  }
  ```
+ 校验命令的请求参数，校验失败响应错误并返回；
  ```c
  else if ((c->cmd->arity > 0 && c->cmd->arity != c->argc) ||
             (c->argc < -c->cmd->arity)) {
      flagTransaction(c);
      addReplyErrorFormat(c,"wrong number of arguments for '%s' command",
          c->cmd->name);
      return C_OK;
  }
  ```
  其中`c->cmd->arity`表示命令参数个数，用于校验命令请求格式是否正确。如果`arity < 0`，则命令的参数个数不能超过`(-1) * arity`；
  如果`arity > 0`，则命令的参数个数必须等于`arity`；命令的本身也是一个参数。
+ 身份校验，如果配置文件用`requirepass`指定了密码且客户端没有通过`AUTH`命令认证，则响应错误并返回；
  ```c
  /* Check if the user is authenticated */
  if (server.requirepass && !c->authenticated && c->cmd->proc != authCommand)
  {
      flagTransaction(c);
      addReply(c,shared.noautherr);
      return C_OK;
  }
  ```
+ 还包括内存`OOM`（配置了最大内存），集群相关，持久化相关，主从复制相关，发布订阅相关，事务等相关校验；

当校验都通过后，会开始执行命令：
```c
call(c,CMD_CALL_FULL);
c->woff = server.master_repl_offset;
if (listLength(server.ready_keys))
    handleClientsBlockedOnKeys();
```
执行命令的核心是`call`函数，其中执行命令相关操作如下：
```c
/* Call the command. */
dirty = server.dirty;
updateCachedTime(0);
start = server.ustime;
// 调用命令处理函数
c->cmd->proc(c);
duration = ustime()-start;
dirty = server.dirty-dirty;
if (dirty < 0) dirty = 0;
```
执行命令`call`函数除了调用具有的命令处理函数，还会涉及更新统计信息，更新慢查询日志，命令传播，`AOF`请求持久化等操作。

### 命令请求回复
`redis`响应命令回复类型有如下几种，客户端可以根据返回结果第一个字符判断响应类型：
+ 状态回复，第一个字符是`+`；
  ```c
  addReply(c,shared.ok);
  shared.ok = createObject(OBJ_STRING,sdsnew("+OK\r\n"));
  ```
+ 错误回复，第一个字符是`-`；例如当请求命令不存在，执行如下调用：
  ```c
  addReplyErrorFormat(c,"unknown command `%s`, with args beginning with: %s", (char*)c->argv[0]->ptr, args);
  // 在 addReplyErrorFormat 内部会拼接回复字符串
  if (!len || s[0] != '-') addReplyString(c,"-ERR ",5);
  addReplyString(c,s,len);
  addReplyString(c,"\r\n",2);
  ```
+ 整数回复，第一个字符是`:`；例如执行`incr`命令后，成功会调用如下回复函数：
  ```c
  // shared.colon = createObject(OBJ_STRING,sdsnew(":"));
  addReply(c,shared.colon);
  // new 是更新后的 value 对象
  addReply(c,new);
  // createObject(OBJ_STRING,sdsnew("\r\n"));
  addReply(c,shared.crlf);
  ```
+ 批量回复，第一个字符是`$`；例如执行`GET`命令后，成功会调用如下函数：
  ```c
  /* Add a Redis Object as a bulk reply */
  void addReplyBulk(client *c, robj *obj) {
      // 计算返回对象 obj 的长度，拼接为字符串`${len}\r\n`
      addReplyBulkLen(c,obj);
      // obj 是查询的 value 值
      addReply(c,obj);
      // createObject(OBJ_STRING,sdsnew("\r\n"));
      addReply(c,shared.crlf);
  }
  ```
+ 多批量回复，第一个字符是`*`；例如执行`LRANGE`命令，返回多个值，例如`*2\r\n$6\r\nvalue1\r\n$6\r\nvalue2\r\n`，
其中`*2`表示有两个返回值，`$6`表示当前返回值字符串长度；

命令执行结果的回复，都是通过调用`addReply`类似函数完成，`addReply`函数并不是直接调用`socket`相关`API`将结果回复给客户端，
而是将回复结果存放在客户端对象`client`的输出缓存`client->buf`或者输出列表`client->reply`中。`addReply`函数实现如下：
```c
void addReply(client *c, robj *obj) {
    if (prepareClientToWrite(c) != C_OK) return;

    if (sdsEncodedObject(obj)) {
        if (_addReplyToBuffer(c,obj->ptr,sdslen(obj->ptr)) != C_OK)
            _addReplyStringToList(c,obj->ptr,sdslen(obj->ptr));
    } else if (obj->encoding == OBJ_ENCODING_INT) {
        /* For integer encoded strings we just convert it into a string
         * using our optimized function, and attach the resulting string
         * to the output buffer. */
        char buf[32];
        size_t len = ll2string(buf,sizeof(buf),(long)obj->ptr);
        if (_addReplyToBuffer(c,buf,len) != C_OK)
            _addReplyStringToList(c,buf,len);
    } else {
        serverPanic("Wrong obj->encoding in addReply()");
    }
}
```
+ 首先，`addReply`函数会调用`prepareClientToWrite`函数，根据需要将此客户端对象添加到服务对象`server.clients_pending_write`链表中，
以用于事件循环中`beforesleep`函数遍历`server.clients_pending_write`链表中每一个客户端，发送输出缓存区或输出链表数据；实现如下：
  ```c
  int prepareClientToWrite(client *c) {
      // 各种条件检查校验
      ...
      if (!clientHasPendingReplies(c)) clientInstallWriteHandler(c);

      /* Authorize the caller to queue in the output buffer of this client. */
      return C_OK;
  }
  ```
  `clientHasPendingReplies`函数会判断当前客户端对象输出缓存或输出链表是否有需要回复的数据，如果没有则调用`clientInstallWriteHandler`函数，
  将此客户端对象添加到`server.clients_pending_write`链表中，相关实现如下：
  ```c
  int clientHasPendingReplies(client *c) {
      return c->bufpos || listLength(c->reply);
  }

  void clientInstallWriteHandler(client *c) {
      if (!(c->flags & CLIENT_PENDING_WRITE) &&
          (c->replstate == REPL_STATE_NONE ||
           (c->replstate == SLAVE_STATE_ONLINE && !c->repl_put_online_on_ack)))
      {
          c->flags |= CLIENT_PENDING_WRITE;
          listAddNodeHead(server.clients_pending_write,c);
      }
  }
  ```
+ 然后`addReply`会先调用`_addReplyToBuffer`函数尝试将要回复的数据添加到输出缓存`buf`中，如果添加失败，会调用`_addReplyStringToList`函数继续添加到输出链表`reply`中；

要回复的数据添加到对应客户端对象的输出缓存`buf`或者输出链表`reply`中，那什么时候会执行实际的发送呢？答案就是在前面讲解开启事件循环小节介绍的`event->beforesleep`函数。
`event->beforesleep`函数内会调用`handleClientsWithPendingWrites`函数，`handleClientsWithPendingWrites`函数会遍历`server.clients_pending_write`链表中每一个客户端，
将输出缓存`buf`或输出链表`reply`数据发送给对应客户端；
```c
int handleClientsWithPendingWrites(void) {
    listIter li;
    listNode *ln;
    int processed = listLength(server.clients_pending_write);

    listRewind(server.clients_pending_write,&li);
    // 开始遍历每一个客户端
    while((ln = listNext(&li))) {
        client *c = listNodeValue(ln);
        c->flags &= ~CLIENT_PENDING_WRITE;
        listDelNode(server.clients_pending_write,ln);

        /* If a client is protected, don't do anything,
         * that may trigger write error or recreate handler. */
        if (c->flags & CLIENT_PROTECTED) continue;

        /* Try to write buffers to the client socket. */
        if (writeToClient(c->fd,c,0) == C_ERR) continue;
        // 如果当前客户端数据每发送完
        if (clientHasPendingReplies(c)) {
            int ae_flags = AE_WRITABLE;
            if (server.aof_state == AOF_ON &&
                server.aof_fsync == AOF_FSYNC_ALWAYS)
            {
                ae_flags |= AE_BARRIER;
            }
            // 注册可写文件事件，事件触发函数是 sendReplyToClient
            if (aeCreateFileEvent(server.el, c->fd, ae_flags,
                sendReplyToClient, c) == AE_ERR)
            {
                    freeClientAsync(c);
            }
        }
    }
    return processed;
}
```

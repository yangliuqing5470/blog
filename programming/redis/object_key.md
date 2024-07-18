> 基于`redis`源码分支`5.0`

`redis`对象`redisObject`和数据库`redisDb`的定义及介绍参考[redis服务启动](./server.md)的数据结构定义小节。
# redis键对象
## 查看键属性
**命令`object`** 用于查看`redis`对象的属性，命令格式如下：
```bash
object subcommand <key>
```
其中`subcommand`的取值有如下：
+ `help`：`object`命令使用说明；
  ```c
  void objectCommand(client *c) {
      robj *o;
  
      if (c->argc == 2 && !strcasecmp(c->argv[1]->ptr,"help")) {
          const char *help[] = {
  "ENCODING <key> -- Return the kind of internal representation used in order to store the value associated with a key.",
  "FREQ <key> -- Return the access frequency index of the key. The returned integer is proportional to the logarithm of the recent access frequency of the key.",
  "IDLETIME <key> -- Return the idle time of the key, that is the approximated number of seconds elapsed since the last access to the key.",
  "REFCOUNT <key> -- Return the number of references of the value associated with the specified key.",
  NULL
          };
          addReplyHelp(c, help);
      }
      ...
  }
  ```
+ `refcount`：获取键关联的值的引用计数，也就是`redisObject`对象的`refcount`属性值；
  ```c
  void objectCommand(client *c) {
      robj *o;
      ...
      else if (!strcasecmp(c->argv[1]->ptr,"refcount") && c->argc == 3) {
          // o 表示键关联的值对象
          if ((o = objectCommandLookupOrReply(c,c->argv[2],shared.nullbulk)) == NULL) return;
          addReplyLongLong(c,o->refcount);
      }
      ...
  }

  robj *objectCommandLookup(client *c, robj *key) {
      dictEntry *de;
  
      if ((de = dictFind(c->db->dict,key->ptr)) == NULL) return NULL;
      return (robj*) dictGetVal(de);
  }
  // 查找键 key 关联的值对象
  robj *objectCommandLookupOrReply(client *c, robj *key, robj *reply) {
      robj *o = objectCommandLookup(c,key);
  
      if (!o) addReply(c, reply);
      return o;
  }
  ```
+ `encoding`：获取键关联的值底层存储使用的编码，也就是`redisObject`对象的`encoding`字符串表达；
  ```c
  void objectCommand(client *c) {
      robj *o;
      ...
      else if (!strcasecmp(c->argv[1]->ptr,"encoding") && c->argc == 3) {
          if ((o = objectCommandLookupOrReply(c,c->argv[2],shared.nullbulk)) == NULL) return;
          // strEncoding 是整数到字符串表达的映射
          addReplyBulkCString(c,strEncoding(o->encoding));
      }
      ...
  }
  ```
+ `idletime`：返回键关联的值的空闲时间，即自上次访问键以来经过的近似秒数（受共享对象影响），只针对`maxmemory-policy`不是`LFU`时，此子命令可用；
  ```c
  void objectCommand(client *c) {
      robj *o;
      ...
      else if (!strcasecmp(c->argv[1]->ptr,"idletime") && c->argc == 3) {
          if ((o = objectCommandLookupOrReply(c,c->argv[2],shared.nullbulk)) == NULL) return;
          if (server.maxmemory_policy & MAXMEMORY_FLAG_LFU) {
              addReplyError(c,"An LFU maxmemory policy is selected, idle time not tracked. Please note that when switching between policies at runtime LRU and LFU data will take some time to adjust.");
              return;
          }
          // 除以 1000 将毫秒转为秒
          addReplyLongLong(c,estimateObjectIdleTime(o)/1000);
      }
      ...
  }
  // 获取上次访问到现在经过的时间，毫秒
  unsigned long long estimateObjectIdleTime(robj *o) {
      // 获取当前时间
      unsigned long long lruclock = LRU_CLOCK();
      if (lruclock >= o->lru) {
          return (lruclock - o->lru) * LRU_CLOCK_RESOLUTION;
      } else {
          return (lruclock + (LRU_CLOCK_MAX - o->lru)) *
                      LRU_CLOCK_RESOLUTION;
      }
  }
  ```
+ `freq`：获取键关联的值的访问频率（受共享对象影响），只针对`maxmemory-policy`设置为`LFU`时，此子命令可用；
  ```c
  void objectCommand(client *c) {
      robj *o;
      ...
      else if (!strcasecmp(c->argv[1]->ptr,"freq") && c->argc == 3) {
          if ((o = objectCommandLookupOrReply(c,c->argv[2],shared.nullbulk)) == NULL) return;
          if (!(server.maxmemory_policy & MAXMEMORY_FLAG_LFU)) {
              addReplyError(c,"An LFU maxmemory policy is not selected, access frequency not tracked. Please note that when switching between policies at runtime LRU and LFU data will take some time to adjust.");
              return;
          }
          // LFUDecrAndReturn 获取访问频率，考虑衰减算法（LFU 实现后续计划单独找一节介绍）
          addReplyLongLong(c,LFUDecrAndReturn(o));
      }
      ...
  }
  ```

使用样例如下：
```bash
// 插入一个 key my-key
my-redis:6379> SET my-key "hello world"
OK
// 查看 encoding 属性
my-redis:6379> OBJECT ENCODING my-key
"embstr"
// 查看 refcount 属性
my-redis:6379> OBJECT REFCOUNT my-key
(integer) 1
// 查看 idletime 属性
my-redis:6379> OBJECT idletime my-key
(integer) 50
```

**命令`type`** 用于查看键关联的值的类型，使用方式如下：
```bash
type <key>
```
使用样例如下：
```bash
my-redis:6379> TYPE my-key
string
```

**命令`ttl`** 返回键剩余的生存时间，单位秒。**命令`pttl`** 返回键剩余生存时间，单位毫秒。使用方式如下：
```bash
TTL <key>

PTTL <key>
```
使用样例如下：
```bash
my-redis:6379> TTL my-key
(integer) -1

my-redis:6379> PTTL my-key
(integer) -1
```
查询键剩余生存时间相关源码实现如下：
```c
/* TTL key */
void ttlCommand(client *c) {
    ttlGenericCommand(c, 0);
}

/* PTTL key */
void pttlCommand(client *c) {
    ttlGenericCommand(c, 1);
}
```
`ttl`或者`pttl`底层都是调用`ttlGenericCommand`函数，其实现如下：
```c
/* Implements TTL and PTTL */
void ttlGenericCommand(client *c, int output_ms) {
    long long expire, ttl = -1;

    /* If the key does not exist at all, return -2 */
    if (lookupKeyReadWithFlags(c->db,c->argv[1],LOOKUP_NOTOUCH) == NULL) {
        addReplyLongLong(c,-2);
        return;
    }
    /* The key exists. Return -1 if it has no expire, or the actual
     * TTL value otherwise. */
    expire = getExpire(c->db,c->argv[1]);
    if (expire != -1) {
        ttl = expire-mstime();
        if (ttl < 0) ttl = 0;
    }
    if (ttl == -1) {
        addReplyLongLong(c,-1);
    } else {
        // 加 500 表示四舍五入
        addReplyLongLong(c,output_ms ? ttl : ((ttl+500)/1000));
    }
}
```
函数返回结果有如下分类：
+ `-2`：表示查询的键不存在；
+ `-1`：查询的键没有设置过期时间，也就是在数据库`redisDb->expires`字典没有要查询的键；
+ `>=0`：表示键的剩余生存时间，根据参数判断单位是秒还是毫秒；

## 更新键
**命令`expire`** 用于设置键的过期时间，使用命令如下：
```bash
EXPIRE <key> <seconds>
```
类似的命令还有`expireat`、`pexpire`和`pexpireat`，区别是参数的单位（秒或者毫秒）或时间（相对时间还是绝对时间）。
键设置过期时间相关源码如下：
```c
/* EXPIRE key seconds */
void expireCommand(client *c) {
    expireGenericCommand(c,mstime(),UNIT_SECONDS);
}

/* EXPIREAT key time */
void expireatCommand(client *c) {
    expireGenericCommand(c,0,UNIT_SECONDS);
}

/* PEXPIRE key milliseconds */
void pexpireCommand(client *c) {
    expireGenericCommand(c,mstime(),UNIT_MILLISECONDS);
}

/* PEXPIREAT key ms_time */
void pexpireatCommand(client *c) {
    expireGenericCommand(c,0,UNIT_MILLISECONDS);
}
```
键过期的底层调用都是`expireGenericCommand`函数，其实现如下：
```c
void expireGenericCommand(client *c, long long basetime, int unit) {
    robj *key = c->argv[1], *param = c->argv[2];
    long long when; /* unix time in milliseconds when the key will expire. */
    // 获取参数 param 指定的过期时间值存在 when，转为 long long 类型
    if (getLongLongFromObjectOrReply(c, param, &when, NULL) != C_OK)
        return;
    // 更新过期时间点 when，统一转为毫秒
    if (unit == UNIT_SECONDS) when *= 1000;
    when += basetime;

    // key 不存在，返回 0
    if (lookupKeyWrite(c->db,key) == NULL) {
        addReply(c,shared.czero);
        return;
    }
    // 当前的服务实例没有在 loading（也就是没有从磁盘加载数据）且 设置的过期时间小于当前时间 且 是主库，
    // 执行键删除操作 （server.masterhost 表示当前实例连接的主节点，如果为空说明当前实例是主库）
    if (when <= mstime() && !server.loading && !server.masterhost) {
        robj *aux;
        // 根据配置执行异步删除还是同步删除，异步删除指的是值对象放到队列链表中，在后台线程删除
        int deleted = server.lazyfree_lazy_expire ? dbAsyncDelete(c->db,key) :
                                                    dbSyncDelete(c->db,key);
        serverAssertWithInfo(c,key,deleted);
        // 用于统计，记录数据库修改的次数（脏数据指被修改但没有持久化到磁盘）
        server.dirty++;

        /* Replicate/AOF this as an explicit DEL or UNLINK. */
        aux = server.lazyfree_lazy_expire ? shared.unlink : shared.del;
        rewriteClientCommandVector(c,2,aux,key);
        signalModifiedKey(c->db,key);
        notifyKeyspaceEvent(NOTIFY_GENERIC,"del",key,c->db->id);
        addReply(c, shared.cone);
        return;
    } else {
        // 在过期字典 expires 插入键 key，值是 when
        setExpire(c,c->db,key,when);
        // 回复 1
        addReply(c,shared.cone);
        // 通知键被修改
        signalModifiedKey(c->db,key);
        // 通知键空间事件，所有相关的订阅都会收到通知
        notifyKeyspaceEvent(NOTIFY_GENERIC,"expire",key,c->db->id);
        server.dirty++;
        return;
    }
}
```
函数执行成功会回复`0`，键不存在回复`1`。每次执行`expire`命令，都会覆盖键的过期时间。

**命令`persist`** 用于移除键的过期时间，可以将带过期时间的临时键变为永久存储的键，使用命令如下：
```bash
PERSIST <key>
```
命令源码实现如下：
```c
/* PERSIST key */
void persistCommand(client *c) {
    // 在 dict 字典查询键是否存在
    if (lookupKeyWrite(c->db,c->argv[1])) {
        // 从 expires 字典删除对应的键
        if (removeExpire(c->db,c->argv[1])) {
            // 回复 1
            addReply(c,shared.cone);
            server.dirty++;
        } else {
            // 回复 0
            addReply(c,shared.czero);
        }
    } else {
        addReply(c,shared.czero);
    }
}
```
`persist`命令通过将键从数据库的`expires`过期字典移除实现，如果移除成功回复`1`，如果键不存在回复`0`。

**命令`rename`和`renamenx`** 用于将键重命名，命令使用格式如下：
```bash
RENAME/RENAMENX <key> <newkey>
```
命令执行结果有如下几种情况：
+ 如果`<key>`不存在，则回复错误`ERR no such key`；
+ 如果`<key>`和`<newkey>`相同，则`rename`命令回复`ok`，`renamenx`命令回复`0`；
+ 如果`<newkey>`存在，`renamenx`命令直接回复`0`结束，`rename`命令先删除`<newkey>`对应的键值对，走`<newkey>`不存在逻辑；
+ 如果`<newkey>`不存在，两个命令都是直接添加`<newkey>`对应的键值对，其中值是`<key>`键对应的值；如果之前的`<key>`有过期时间，
新的`<newkey>`键也会设置`<key>`对应的过期时间；最后删除`<key>`对应的键值对，触发键修改和键空间通知：
  ```c
  // 键修改
  signalModifiedKey(c->db,c->argv[1]);
  signalModifiedKey(c->db,c->argv[2]);
  // 键空间通知
  notifyKeyspaceEvent(NOTIFY_GENERIC,"rename_from",
      c->argv[1],c->db->id);
  notifyKeyspaceEvent(NOTIFY_GENERIC,"rename_to",
      c->argv[2],c->db->id);
  ```
  `renamenx`命令回复`1`，`rename`命令回复`ok`；

**命令`touch`** 用于更新键对应值对象`redisObject`的`lru`字段，避免被`LRU`或者`LFU`淘汰，其命令格式如下：
```bash
TOUCH key1 [key2 key3 ... keyN]
```
`touch`命令的源码实现如下：
```c
/* TOUCH key1 [key2 key3 ... keyN] */
void touchCommand(client *c) {
    int touched = 0;
    for (int j = 1; j < c->argc; j++)
        if (lookupKeyRead(c->db,c->argv[j]) != NULL) touched++;
    addReplyLongLong(c,touched);
}
```
返回值是成功更新键的个数。`touchCommand`命令函数内部主要是对每一个待更新的键都执行`lookupKeyRead`调用，
`lookupKeyRead`内部核心逻辑是调用`lookupKey`函数：
```c
robj *lookupKey(redisDb *db, robj *key, int flags) {
    dictEntry *de = dictFind(db->dict,key->ptr);
    if (de) {
        robj *val = dictGetVal(de);

        /* Update the access time for the ageing algorithm.
         * Don't do it if we have a saving child, as this will trigger
         * a copy on write madness. */
        // 没有 rdb 和 aof 进程运行并且 flag 不是 LOOKUP_NOTOUCH
        if (server.rdb_child_pid == -1 &&
            server.aof_child_pid == -1 &&
            !(flags & LOOKUP_NOTOUCH))
        {
            if (server.maxmemory_policy & MAXMEMORY_FLAG_LFU) {
                // LFU 策略
                updateLFU(val);
            } else {
                // LRU 策略
                val->lru = LRU_CLOCK();
            }
        }
        return val;
    } else {
        return NULL;
    }
}
```

## 查找键
**命令`exists`** 用于检查指定的键是否存在，返回键存在的个数，其命令个数如下：
```bash
EXISTS key1 key2 ... key_N
```
`exists`命令源码实现如下：
```c
/* EXISTS key1 key2 ... key_N.
 * Return value is the number of keys existing. */
void existsCommand(client *c) {
    long long count = 0;
    int j;

    for (j = 1; j < c->argc; j++) {
        if (lookupKeyRead(c->db,c->argv[j])) count++;
    }
    addReplyLongLong(c,count);
}
```
源码逻辑和命令`touch`源码执行逻辑基本一致，都是通过调用`lookupKeyRead`实现。

**命令`keys`** 用于查找符合给定模式的所有键，并一次返回，其命令格式如下：
```bash
KEYS <pattern>
```
如果匹配的键较多，则可能阻塞服务端，一般不要在线上使用。命令`keys`相关源码实现如下：
```c
void keysCommand(client *c) {
    dictIterator *di;
    dictEntry *de;
    sds pattern = c->argv[1]->ptr;
    int plen = sdslen(pattern), allkeys;
    unsigned long numkeys = 0;
    void *replylen = addDeferredMultiBulkLength(c);

    di = dictGetSafeIterator(c->db->dict);
    allkeys = (pattern[0] == '*' && plen == 1);
    // 遍历整个数据库，比较每一个键是否满足指定模式匹配
    while((de = dictNext(di)) != NULL) {
        sds key = dictGetKey(de);
        robj *keyobj;
        // 进行正则匹配
        if (allkeys || stringmatchlen(pattern,plen,key,sdslen(key),0)) {
            keyobj = createStringObject(key,sdslen(key));
            if (!keyIsExpired(c->db,keyobj)) {
                // 往客户端输出缓存添加一行回调内容
                addReplyBulk(c,keyobj);
                numkeys++;
            }
            decrRefCount(keyobj);
        }
    }
    dictReleaseIterator(di);
    setDeferredMultiBulkLength(c,replylen,numkeys);
}
```

**命令`scan`** 用于遍历当前数据库中所有的键，是增量式命令，不会阻塞服务。命令使用格式如下：
```bash
SCAN cursor [MATCH pattern] [COUNT count]
```
类似的命令还有`hscan`（迭代哈希键中的键值对）、`sscan`（迭代集合键中的元素）和`zscan`（迭代有序集合中的元素，包括元素成员和元素分值）。
+ `cursor`：命令每次被调用之后，都会向用户返回一个新的游标，用户在下次迭代时需要使用这个新游标作为命令的游标参数，以此来延续之前的迭代过程。
游标参数被设置为`0`时，服务器将开始一次新的迭代，而当服务器向用户返回值为`0`的游标时，表示迭代已结束；
+ `MATCH`：匹配模式，用于正则匹配；
+ `COUNT`：指定每次调用返回元素个数最大值，只针对哈希编码或者跳跃表编码实现的对象有效，其他编码会忽略这个值；

`scan`命令，包括`hscan`和`sscan`命令底层都是调用`scanGenericCommand`函数，`scanGenericCommand`函数执行逻辑主要有四步：
+ 解析命令参数；
  ```c
  void scanGenericCommand(client *c, robj *o, unsigned long cursor) {
      int i, j;
      // 一个链表，存放遍历到的对象
      list *keys = listCreate();
      listNode *node, *nextnode;
      long count = 10;
      sds pat = NULL;
      int patlen = 0, use_pattern = 0;
      dict *ht;

      serverAssert(o == NULL || o->type == OBJ_SET || o->type == OBJ_HASH ||
                  o->type == OBJ_ZSET);

      // o == NULL 说明是 scan 命令，i 表示 cursor 参数后面的参数索引，
      // o != NULL 说明是 hscan 或 sscan 命令
      i = (o == NULL) ? 2 : 3; /* Skip the key argument if needed. */

      /* Step 1: Parse options. */
      while (i < c->argc) {
          j = c->argc - i;
          if (!strcasecmp(c->argv[i]->ptr, "count") && j >= 2) {
              // 匹配 count 参数，获取 count 值
              if (getLongFromObjectOrReply(c, c->argv[i+1], &count, NULL)
                  != C_OK)
              {
                  goto cleanup;
              }

              if (count < 1) {
                  addReply(c,shared.syntaxerr);
                  goto cleanup;
              }
              i += 2;
          } else if (!strcasecmp(c->argv[i]->ptr, "match") && j >= 2) {
              // 匹配 match 参数，获取匹配模式
              pat = c->argv[i+1]->ptr;
              patlen = sdslen(pat);
              // 是否需要匹配模式
              use_pattern = !(pat[0] == '*' && patlen == 1);
              i += 2;
          } else {
              addReply(c,shared.syntaxerr);
              goto cleanup;
          }
      }
      ...
  }
  ```
  此步主要完成获取请求命令参数中的`count`和`match`值；
+ 开始遍历；如果参数`o`存在（`o`不存在说明是`scan`命令，遍历整个数据库），且对象`o`的编码方式不是`OBJ_ENCODING_HT`或`OBJ_ENCODING_SKIPLIST`，
则一次返回在对象`o`中的所有元素，返回游标`cursor=0`；
  ```c
  void scanGenericCommand(client *c, robj *o, unsigned long cursor) {
      ...
      // 参数 o 不存在或者参数对象 o 底层编码是 OBJ_ENCODING_HT/OBJ_ENCODING_SKIPLIST 时才会更新 ht（哈希表）
      ht = NULL;
      if (o == NULL) {
          ht = c->db->dict;
      } else if (o->type == OBJ_SET && o->encoding == OBJ_ENCODING_HT) {
          ht = o->ptr;
      } else if (o->type == OBJ_HASH && o->encoding == OBJ_ENCODING_HT) {
          ht = o->ptr;
          count *= 2; /* We return key / value for this type. */
      } else if (o->type == OBJ_ZSET && o->encoding == OBJ_ENCODING_SKIPLIST) {
          zset *zs = o->ptr;
          ht = zs->dict;
          count *= 2; /* We return key / value for this type. */
      }

      if (ht) {
          // privdata 参数是 scanCallback 函数的参数
          void *privdata[2];
          // 设置迭代次数为 10*count，避免稀疏的哈希表一次返回元素太少而导致阻塞多次查找
          long maxiterations = count*10;
          privdata[0] = keys;
          privdata[1] = o;
          do {
              // dictScan 逻辑很有意思，可以单独查看学习，每次都返回一个游标，给下次调用，
              // 返回游标为 0 表示整个数据库遍历完成。
              // 遍历到元素后在dictScan内部都会调用 scanCallback 函数，将元素对象添加到 keys 链表中
              cursor = dictScan(ht, cursor, scanCallback, NULL, privdata);
          } while (cursor &&
                maxiterations-- &&
                // 确保一次查找的元素个数不超过 count
                listLength(keys) < (unsigned long)count);
      } else if (o->type == OBJ_SET) {
          // 走到这里说明对象 o 的底层存储是整数集合，一次查找整数集合中所有元素
          int pos = 0;
          int64_t ll;

          while(intsetGet(o->ptr,pos++,&ll))
              listAddNodeTail(keys,createStringObjectFromLongLong(ll));
          // 设置游标为 0 表示查找结束
          cursor = 0;
      } else if (o->type == OBJ_HASH || o->type == OBJ_ZSET) {
          // 走到这里说明对象 o 的底层存储是压缩列表，一次查找压缩列表中所有元素
          unsigned char *p = ziplistIndex(o->ptr,0);
          unsigned char *vstr;
          unsigned int vlen;
          long long vll;

          while(p) {
              ziplistGet(p,&vstr,&vlen,&vll);
              listAddNodeTail(keys,
                  (vstr != NULL) ? createStringObject((char*)vstr,vlen) :
                                   createStringObjectFromLongLong(vll));
              p = ziplistNext(o->ptr,p);
          }
          // 设置游标为 0 表示查找结束
          cursor = 0;
      } else {
          serverPanic("Not handled encoding in SCAN.");
      }
      ...
  }
  ```
  如果需要遍历的对象是哈希表，则调用`dictScan`函数时，会将查找存在的每一个元素都调用`scanCallback`函数，将元素添加到链表`keys`中，
  `scanCallback`函数实现如下：
  ```c
  void scanCallback(void *privdata, const dictEntry *de) {
      void **pd = (void**) privdata;
      // 存储元素的链表
      list *keys = pd[0];
      // 调用 scanGenericCommand 的参数 o 对象
      robj *o = pd[1];
      robj *key, *val = NULL;

      if (o == NULL) {
          // 只查找 key
          sds sdskey = dictGetKey(de);
          key = createStringObject(sdskey, sdslen(sdskey));
      } else if (o->type == OBJ_SET) {
          // 只查找 key
          sds keysds = dictGetKey(de);
          key = createStringObject(keysds,sdslen(keysds));
      } else if (o->type == OBJ_HASH) {
          // 查找 key value
          sds sdskey = dictGetKey(de);
          sds sdsval = dictGetVal(de);
          key = createStringObject(sdskey,sdslen(sdskey));
          val = createStringObject(sdsval,sdslen(sdsval));
      } else if (o->type == OBJ_ZSET) {
          // 查找 key value
          sds sdskey = dictGetKey(de);
          key = createStringObject(sdskey,sdslen(sdskey));
          // val 表示 score 值
          val = createStringObjectFromLongDouble(*(double*)dictGetVal(de),0);
      } else {
          serverPanic("Type not handled in SCAN callback.");
      }

      listAddNodeTail(keys, key);
      if (val) listAddNodeTail(keys, val);
  }
  ```
  如果查找是`key`和`value`，会将`key`和`value`作为两个节点元素存放在链表`keys`中。
+ 过滤元素；
  ```c
  void scanCallback(void *privdata, const dictEntry *de) {
      ...
      /* Step 3: Filter elements. */
      node = listFirst(keys);
      while (node) {
          robj *kobj = listNodeValue(node);
          nextnode = listNextNode(node);
          // 表示当前节点元素是否需要过滤，0表示不需要，1表示需要
          int filter = 0;
          // 如果需要模式匹配，排除 keys 列表中不匹配的节点
          if (!filter && use_pattern) {
              if (sdsEncodedObject(kobj)) {
                  // 节点元素是字符串编码
                  if (!stringmatchlen(pat, patlen, kobj->ptr, sdslen(kobj->ptr), 0))
                      filter = 1;
              } else {
                  // 整数编码
                  char buf[LONG_STR_SIZE];
                  int len;
                  serverAssert(kobj->encoding == OBJ_ENCODING_INT);
                  len = ll2string(buf,sizeof(buf),(long)kobj->ptr);
                  if (!stringmatchlen(pat, patlen, buf, len, 0)) filter = 1;
              }
          }

          /* Filter element if it is an expired key. */
          if (!filter && o == NULL && expireIfNeeded(c->db, kobj)) filter = 1;

          /* Remove the element and its associted value if needed. */
          if (filter) {
              decrRefCount(kobj);
              listDelNode(keys, node);
          }
          // 如果参数对象 o 是有序集合或者哈希表，列表keys中存储是 key 和 value，下次迭代需要跳过 value
          if (o && (o->type == OBJ_ZSET || o->type == OBJ_HASH)) {
              node = nextnode;
              nextnode = listNextNode(node);
              if (filter) {
                  kobj = listNodeValue(node);
                  decrRefCount(kobj);
                  listDelNode(keys, node);
              }
          }
          node = nextnode;
      }
  }
  ```
  排除列表`keys`中过期或者模式不匹配的元素节点。
+ 回复客户端；
  ```c
  void scanCallback(void *privdata, const dictEntry *de) {
      ...
      /* Step 4: Reply to the client. */
      addReplyMultiBulkLen(c, 2);
      addReplyBulkLongLong(c,cursor);

      addReplyMultiBulkLen(c, listLength(keys));
      while ((node = listFirst(keys)) != NULL) {
          robj *kobj = listNodeValue(node);
          addReplyBulk(c, kobj);
          decrRefCount(kobj);
          listDelNode(keys, node);
      }
  }
  ```

**命令`randomkey`** 用于从当前数据库中随机返回(不删除)一个未过期的`key`。命令格式如下：
```bash
RANDOMKEY
```
`randomkey`命令相关源码实现如下：
```c
void randomkeyCommand(client *c) {
    robj *key;
    // 随机查找一个不过期的 key
    if ((key = dbRandomKey(c->db)) == NULL) {
        addReply(c,shared.nullbulk);
        return;
    }
    // 回复给客户端
    addReplyBulk(c,key);
    // 引用计数减 1，如果为 1 则删除对象，因为 key 对象是临时创建的，回复后需要清理
    decrRefCount(key);
}
```
随机返回一个`key`通过`dbRandomKey`函数实现，其源码如下：
```c
robj *dbRandomKey(redisDb *db) {
    dictEntry *de;
    // 最大迭代查找次数，针对从节点。因为从节点不会删除过期的key
    int maxtries = 100;
    // 表示是否所有的键都设置了过期时间
    int allvolatile = dictSize(db->dict) == dictSize(db->expires);

    while(1) {
        sds key;
        robj *keyobj;
        // 从数据库随机选择一个 key，
        // 如果没有在做rehash操作，从ht[0]哈希表选择，如果在rehash操作，ht[0]和ht[1]都会作为目标选择
        de = dictGetRandomKey(db->dict);
        if (de == NULL) return NULL;

        key = dictGetKey(de);
        keyobj = createStringObject(key,sdslen(key));
        // 判断选择的 key 对象是否在过期字典存在（存在说明 key 设置了过期时间）
        if (dictFind(db->expires,key)) {
            if (allvolatile && server.masterhost && --maxtries == 0) {
                return keyobj;
            }
            // 对于主节点，如果键过期，则删除数据库对应的键值对，
            // 对于从节点，如果键过期，则不会删除
            if (expireIfNeeded(db,keyobj)) {
                // 删除临时对象
                decrRefCount(keyobj);
                continue; /* search for another key. This expired. */
            }
        }
        return keyobj;
    }
}
```
+ 对于从节点来说，如果整个数据库键都设置了过期时间，且所有键都过期了（或者绝大部分过期），为了避免调用`dbRandomKey`函数陷入死循环，
增加最大迭代次数`maxtries=100`。
+ 对于主节点来说，遇到过期键，在`expireIfNeeded`函数内部会删除过期键值对，如果过期键比较多，操作执行较慢；

## 键操作
**命令`del`** 用于同步删除一个或者多个键值对，命令格式如下：
```bash
DEL <key1> [<key2> <key3> ...]
```
删除类似的命令还有`unlink`，用于异步删除。二者底层都是调用`delGenericCommand`函数，`delGenericCommand`实现如下：
```c
void delGenericCommand(client *c, int lazy) {
    int numdel = 0, j;

    for (j = 1; j < c->argc; j++) {
        // 从库不会删除过期键，主库会删除过期键
        expireIfNeeded(c->db,c->argv[j]);
        int deleted  = lazy ? dbAsyncDelete(c->db,c->argv[j]) :
                              dbSyncDelete(c->db,c->argv[j]);
        if (deleted) {
            // 删除成功，执行键修改通知
            signalModifiedKey(c->db,c->argv[j]);
            // 键空间通知，用于发布/订阅模式
            notifyKeyspaceEvent(NOTIFY_GENERIC,
                "del",c->argv[j],c->db->id);
            // 用于统计，记录数据库修改的次数（脏数据指被修改但没有持久化到磁盘）
            server.dirty++;
            numdel++;
        }
    }
    // 回复客户端删除成功的数量
    addReplyLongLong(c,numdel);
}
```
其中同步删除`dbSyncDelete`的实现如下：
```c
int dbSyncDelete(redisDb *db, robj *key) {
    if (dictSize(db->expires) > 0) dictDelete(db->expires,key->ptr);
    if (dictDelete(db->dict,key->ptr) == DICT_OK) {
        // 如果是集群模式，删除槽位和键对应
        if (server.cluster_enabled) slotToKeyDel(key);
        return 1;
    } else {
        return 0;
    }
}
```
同步删除会删除过期字典`db->expires`和数据库`db->dict`中指定的键值对。过期字典`db->expires`和数据库`db->dict`中的键都是指向键对象的指针，
过期字典`db->expires`中删除键不会实际删除键对象，因为在服务启动阶段`initServer`中初始化数据库时候：
```c
for (j = 0; j < server.dbnum; j++) {
    server.db[j].dict = dictCreate(&dbDictType,NULL);
    server.db[j].expires = dictCreate(&keyptrDictType,NULL);
    ...
}
```
指定字典对象`type`属性是`keyptrDictType`，其定义如下：
```c
/* Db->expires */
dictType keyptrDictType = {
    dictSdsHash,                /* hash function */
    NULL,                       /* key dup */
    NULL,                       /* val dup */
    dictSdsKeyCompare,          /* key compare */
    NULL,                       /* key destructor */
    NULL                        /* val destructor */
};
```
没有指定键和值对象释放函数。

下面看下异步删除`dbAsyncDelete`的实现：
```c
#define LAZYFREE_THRESHOLD 64
int dbAsyncDelete(redisDb *db, robj *key) {
    // 先删除过期字典中存在的，这步和同步删除一样
    if (dictSize(db->expires) > 0) dictDelete(db->expires,key->ptr);
    // 惰性删除数据库 dict 中存在的，只是调整指针关系，没有做实际对象删除操作，he 表示要删除对象指针
    dictEntry *de = dictUnlink(db->dict,key->ptr);
    if (de) {
        robj *val = dictGetVal(de);
        // 如果要删除的值对象是容器类型，例如哈希表，集合，列表等，返回元素个数，否则返回 1
        size_t free_effort = lazyfreeGetFreeEffort(val);
        // 如果实际要删除元素个数超过 64，且当前要删除对象没有其他地方引用，走异步删除，也就是删除有后台线程执行
        if (free_effort > LAZYFREE_THRESHOLD && val->refcount == 1) {
            atomicIncr(lazyfree_objects,1);
            // 创建后台任务
            bioCreateBackgroundJob(BIO_LAZY_FREE,val,NULL,NULL);
            dictSetVal(db->dict,de,NULL);
        }
    }

    if (de) {
        // 实际开始释放键值对对象，或者只是释放键对象，因为值对象在后台线程删除，已经被设置为 NULL
        dictFreeUnlinkedEntry(db->dict,de);
        // 如果是集群模式，删除槽位和键对应
        if (server.cluster_enabled) slotToKeyDel(key);
        return 1;
    } else {
        return 0;
    }
}
```
如果要删除的值对象包含太多的元素，对于异步删除会使用后台线程实际处理删除操作，不阻塞当前线程。创建后台删除任务`bioCreateBackgroundJob`实现如下：
```c
void bioCreateBackgroundJob(int type, void *arg1, void *arg2, void *arg3) {
    // 创建一个后台任务 job，设置时间和参数
    struct bio_job *job = zmalloc(sizeof(*job));
    job->time = time(NULL);
    job->arg1 = arg1;
    job->arg2 = arg2;
    job->arg3 = arg3;
    pthread_mutex_lock(&bio_mutex[type]);
    // 任务添加到列表尾，bio_jobs 是个数组，每个元素是一个双端链表
    listAddNodeTail(bio_jobs[type],job);
    bio_pending[type]++;
    // 通知线程开始处理（条件变量）
    pthread_cond_signal(&bio_newjob_cond[type]);
    pthread_mutex_unlock(&bio_mutex[type]);
}
```
`bioCreateBackgroundJob`函数是线程安全的。参数`type`表示异步类型类型，取值有如下三个：
+ `BIO_CLOSE_FILE`
+ `BIO_AOF_FSYNC`
+ `BIO_LAZY_FREE`

在服务启动阶段，`InitServerLast`函数内部会调用`bioInit`函数生成三个异步线程，`bioInit`函数实现如下：
```c
/* Initialize the background system, spawning the thread. */
void bioInit(void) {
    pthread_attr_t attr;
    pthread_t thread;
    size_t stacksize;
    int j;

    // BIO_NUM_OPS = 3
    for (j = 0; j < BIO_NUM_OPS; j++) {
        pthread_mutex_init(&bio_mutex[j],NULL);
        pthread_cond_init(&bio_newjob_cond[j],NULL);
        pthread_cond_init(&bio_step_cond[j],NULL);
        // 初始化链表，用于存放需要异步处理的任务
        bio_jobs[j] = listCreate();
        bio_pending[j] = 0;
    }

    // 设置线程栈大小
    pthread_attr_init(&attr);
    pthread_attr_getstacksize(&attr,&stacksize);
    if (!stacksize) stacksize = 1; /* The world is full of Solaris Fixes */
    while (stacksize < REDIS_THREAD_STACK_SIZE) stacksize *= 2;
    pthread_attr_setstacksize(&attr, stacksize);
    // 创建 BIO_NUM_OPS=3 个后台线程，线程函数是 bioProcessBackgroundJobs
    for (j = 0; j < BIO_NUM_OPS; j++) {
        void *arg = (void*)(unsigned long) j;
        if (pthread_create(&thread,&attr,bioProcessBackgroundJobs,arg) != 0) {
            serverLog(LL_WARNING,"Fatal: Can't initialize Background Jobs.");
            exit(1);
        }
        bio_threads[j] = thread;
    }
}
```
创建的异步线程入口函数是`bioProcessBackgroundJobs`，其会从每个`type`类型对应的链表首取出一个要处理的对象进行处理。
`bioProcessBackgroundJobs`函数是线程安全的，内部涉及锁的获取与释放。

**命令`dump`** 用于将给定`key`对应的值进行序列化，并返回序列化后的数据。命令格式如下：
```bash
DUMP key
```
序列号后的数据结构如下：
```bash
----------------+---------------------+---------------+
... RDB payload | 2 bytes RDB version | 8 bytes CRC64 |
----------------+---------------------+---------------+
```
`dump`命令使用样例如下：
```bash
my-redis:6379> SET my-key "hello world"
OK
my-redis:6379> DUMP my-key
"\x00\x0bhello world\x0b\x00b#\xf4\xca[XI\xbd"
my-redis:6379> DUMP my
(nil)
```

**命令`restore`** 用于反序列化，将反序列化后的结果和给定的`key`关联。命令格式如下：
```bash
RESTORE key ttl serialized-value
```
其中`ttl`表示以毫秒为单位设置的生存时间，如果`ttl=0`表示不给键`key`设置生存时间。指定的`key`必须是个不存在的新`key`。

**命令`move`** 用于将当前数据库的`key`移动到给定的数据库`db`当中。**命令`migrate`** 用于将`key`原子性地从当前实例传送到目标实例的指定数据库上，一旦传送成功，
`key`保证会出现在目标实例上，而当前实例上的`key`会被删除。这两个迁移命令这里不做详细结束。

**命令`sort`** 用于返回或保存给定列表、集合、有序集合`key`中经过排序的元素。命令格式如下：
```bash
SORT key [BY pattern] [LIMIT offset count] [GET pattern [GET pattern ...]] [ASC | DESC] [ALPHA] [STORE destination]
```
+ 不传任何附加参数，默认以数字排序；
  ```bash
  # 创建一个列表 key
  my-redis:6379> LPUSH test-list "wo"
  (integer) 1
  my-redis:6379> LPUSH test-list "men"
  (integer) 2
  my-redis:6379> LPUSH test-list "hao"
  (integer) 3
  my-redis:6379> LPUSH test-list "li"
  (integer) 4
  my-redis:6379> LPUSH test-list "hai"
  (integer) 5
  # 默认排序
  my-redis:6379> SORT test-list
  (error) ERR One or more scores can't be converted into double
  ```
  因为默认以数字排序，不能将值字符串转为浮点数，所以报错。
+ `ALPHA`：对字符串排序；
  ```bash
  my-redis:6379> SORT test-list alpha
  1) "hai"
  2) "hao"
  3) "li"
  4) "men"
  5) "wo"
  ```
+ `ASC|DESC`：正序或者倒序排序；
+ `LIMIT`：限制排序返回的元素；
  ```bash
  my-redis:6379> RPUSH rank 1 3 5 7 9 2 4 6 8 10
  (integer) 10
  my-redis:6379> SORT rank limit 1 5
  1) "2"
  2) "3"
  3) "4"
  4) "5"
  5) "6"
  my-redis:6379> SORT rank limit 2 5
  1) "3"
  2) "4"
  3) "5"
  4) "6"
  5) "7"
  ```
  其中`offset`参数表示要跳过的元素数量；`count`参数表示跳过`offset`个元素之后，要返回多少个对象。
+ `BY`：使用其他键的值作为权重进行排序，如果其他键不存在则跳过排序，直接返回；例如有如下的数据结构：
  |uid|user_name_{uid}|user_level_{uid}|
  |---|---------------|----------------|
  | 1 | admain | 999 |
  | 2 | jack | 10 |
  | 3 | peter | 25 |
  | 4 | mary | 70 |
  ```bash
  my-redis:6379> LPUSH uid 1 2 3 4
  (integer) 4
  my-redis:6379> SET user_name_1 admain
  OK
  my-redis:6379> SET user_level_1 999
  OK
  my-redis:6379> SET user_name_2 jack
  OK
  my-redis:6379> SET user_level_2 10
  OK
  my-redis:6379> SET user_name_3 peter
  OK
  my-redis:6379> SET user_level_3 25
  OK
  my-redis:6379> SET user_name_4 mary
  OK
  my-redis:6379> SET user_level_4 70
  OK
  my-redis:6379> SORT uid by user_level_*
  1) "2"
  2) "3"
  3) "4"
  4) "1"
  ```
  通过`BY`参数指定`user_level_{uid}`列值进行排序。如果`BY`后面的参数有`*`，则首先获取排序键`uid`包含的元素`1 2 3 4`，然后调用函数
  ```c
  robj *lookupKeyByPattern(redisDb *db, robj *pattern, robj *subst);
  ```
  将元素值添加到`user_level_*`中`*`位置，组合成键`user_level_1 user_level_2 user_level_3 user_level_4`，查找对应键的值作为排序比较对象。
  如果`BY`后面的参数没有`*`，则返回结果不会排序，也就是返回原始顺序。
+ `GET`：根据排序的结果来取出相应的键值；
  ```bash
  my-redis:6379> SORT uid by user_level_* get user_name_*
  1) "jack"
  2) "peter"
  3) "mary"
  4) "admain"
  ```
  `GET`后面参数`user_name_*`有`*`，处理逻辑和`BY`一样，也是先获取排序键`uid`包含的元素`1 2 3 4`，然后调用
  ```c
  robj *lookupKeyByPattern(redisDb *db, robj *pattern, robj *subst);
  ```
  将元素值添加到`user_name_*`中`*`位置，组合成键`user_name_1 user_name_2 user_name_3 user_name_4`，查找对应键的值返回。
+ `STORE`：将排序后的结果保存到指定的键`destination`；
  ```bash
  my-redis:6379> SORT uid by user_level_* get user_name_* store new-key
  (integer) 4
  my-redis:6379> LRANGE new-key 0 -1
  1) "jack"
  2) "peter"
  3) "mary"
  4) "admain"
  ```

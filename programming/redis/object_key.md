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
类似的命令还有`hscan`和`sscan`。
+ `cursor`：
+ `MATCH`：
+ `COUNT`：

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
          void *privdata[2];
          /* We set the max number of iterations to ten times the specified
           * COUNT, so if the hash table is in a pathological state (very
           * sparsely populated) we avoid to block too much time at the cost
           * of returning no or very few elements. */
          long maxiterations = count*10;

          /* We pass two pointers to the callback: the list to which it will
           * add new elements, and the object containing the dictionary so that
           * it is possible to fetch more data in a type-dependent way. */
          privdata[0] = keys;
          privdata[1] = o;
          do {
              cursor = dictScan(ht, cursor, scanCallback, NULL, privdata);
          } while (cursor &&
                maxiterations-- &&
                listLength(keys) < (unsigned long)count);
      } else if (o->type == OBJ_SET) {
          int pos = 0;
          int64_t ll;

          while(intsetGet(o->ptr,pos++,&ll))
              listAddNodeTail(keys,createStringObjectFromLongLong(ll));
          cursor = 0;
      } else if (o->type == OBJ_HASH || o->type == OBJ_ZSET) {
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
          cursor = 0;
      } else {
          serverPanic("Not handled encoding in SCAN.");
      }
      ...
  }
  ```

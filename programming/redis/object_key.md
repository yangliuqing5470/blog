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

    if (when <= mstime() && !server.loading && !server.masterhost) {
        robj *aux;

        int deleted = server.lazyfree_lazy_expire ? dbAsyncDelete(c->db,key) :
                                                    dbSyncDelete(c->db,key);
        serverAssertWithInfo(c,key,deleted);
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
        signalModifiedKey(c->db,key);
        notifyKeyspaceEvent(NOTIFY_GENERIC,"expire",key,c->db->id);
        server.dirty++;
        return;
    }
}
```

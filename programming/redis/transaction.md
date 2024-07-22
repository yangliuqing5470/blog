> 基于`redis`源码分支`5.0`

# 事务
`redis`事务能够保证一批命令原子性的执行，即所有命令要么都执行要么都不执行。并且在事务执行过程中不会为任何其他命令提供服务。
事务执行的完整流程主要有以下三阶段（除了正常流程，还有取消事务，监听键等流程）：
+ 事务开启
+ 命令入队
+ 事务执行

## 事务开启
命令`multi`用于显示开启一个事务。命令格式如下：
```bash
MULTI
```
`multi`命令源码实现如下：
```c
void multiCommand(client *c) {
    if (c->flags & CLIENT_MULTI) {
        addReplyError(c,"MULTI calls can not be nested");
        return;
    }
    c->flags |= CLIENT_MULTI;
    addReply(c,shared.ok);
}
```
只是给当前`client`对象设置一个`CLIENT_MULTI`标志位，并且`redis`的事务不能嵌套，即不能在一个开启的事务内再次调用`multi`命令开启一个新事务。

## 命令入队
在 [redis服务启动](./server.md) 小节介绍了`redis`服务端接收到客户端命令请求后会调用`processCommand`函数处理命令，对于事务相关的逻辑如下：
```c
int processCommand(client *c) {
    ...
    /* Exec the command */
    if (c->flags & CLIENT_MULTI &&
        c->cmd->proc != execCommand && c->cmd->proc != discardCommand &&
        c->cmd->proc != multiCommand && c->cmd->proc != watchCommand)
    {
        queueMultiCommand(c);
        addReply(c,shared.queued);
    }
    ...
}
```
如果当前客户端`client`有`CLIENT_MULTI`标志，且要执行的命令不是`exec`、`discard`、`multi`或`watch`，调用`queueMultiCommand`函数将命令入队。
命令入队函数`queueMultiCommand`实现如下：
```c
/* Add a new command into the MULTI commands queue */
void queueMultiCommand(client *c) {
    multiCmd *mc;
    int j;
    // 重新分配存放命令对象 multiCmd 的数组空间
    c->mstate.commands = zrealloc(c->mstate.commands,
            sizeof(multiCmd)*(c->mstate.count+1));
    // 初始化命令对象 mc
    mc = c->mstate.commands+c->mstate.count;
    mc->cmd = c->cmd;
    mc->argc = c->argc;
    mc->argv = zmalloc(sizeof(robj*)*c->argc);
    memcpy(mc->argv,c->argv,sizeof(robj*)*c->argc);
    for (j = 0; j < c->argc; j++)
        incrRefCount(mc->argv[j]);
    c->mstate.count++;
    c->mstate.cmd_flags |= c->cmd->flags;
}
```
其中每一个入队的命令都用`multiCmd`结构表示，`multiCmd`定于如下：
```c
typedef struct multiCmd {
    robj **argv;  // 命令参数数组
    int argc;     // 命令参数个数
    struct redisCommand *cmd; // 解析后的命令对象
} multiCmd;
```
客户端`client`有一个`multiState`对象用于存储事务条件下入队的所有命令对象`multiCmd`，`multiState`对象定义如下：
```c
typedef struct client {
    ...
    multiState mstate;      /* MULTI/EXEC state */
    ...
} client

typedef struct multiState {
    multiCmd *commands;     /* Array of MULTI commands */
    int count;              /* Total number of MULTI commands */
    int cmd_flags;          /* The accumulated command flags OR-ed together.
                               So if at least a command has a given flag, it
                               will be set in this field. */
    int minreplicas;        /* MINREPLICAS for synchronous replication */
    time_t minreplicas_timeout; /* MINREPLICAS timeout as unixtime. */
} multiState;
```

## 事务执行
命令`exec`用于执行所有入队命令并将命令返回值依次返回。命令格式如下：
```bash
EXEC
```
`exec`命令实现源码如下：
```c
void execCommand(client *c) {
    ...
    /* Exec all the queued commands */
    unwatchAllKeys(c); /* Unwatch ASAP otherwise we'll waste CPU cycles */
    orig_argv = c->argv;
    orig_argc = c->argc;
    orig_cmd = c->cmd;
    addReplyMultiBulkLen(c,c->mstate.count);
    for (j = 0; j < c->mstate.count; j++) {
        c->argc = c->mstate.commands[j].argc;
        c->argv = c->mstate.commands[j].argv;
        c->cmd = c->mstate.commands[j].cmd;
        // 有不是只读命令且不是管理命令，需要将命令传播给 AOF 或者从节点，为了保证数据一致性
        if (!must_propagate && !(c->cmd->flags & (CMD_READONLY|CMD_ADMIN))) {
            execCommandPropagateMulti(c);
            must_propagate = 1;
        }
        // 执行单个命令并回复客户端（将回复内容添加到输出缓存中）
        call(c,server.loading ? CMD_CALL_NONE : CMD_CALL_FULL);

        /* Commands may alter argc/argv, restore mstate. */
        c->mstate.commands[j].argc = c->argc;
        c->mstate.commands[j].argv = c->argv;
        c->mstate.commands[j].cmd = c->cmd;
    }
    c->argv = orig_argv;
    c->argc = orig_argc;
    c->cmd = orig_cmd;
    // 事务执行完后清理事务相关资源
    discardTransaction(c);
    ...
}
```
事务执行的核心逻辑就是按照命令入队顺序，依次执行命令并回复（回复内容添加到输出缓存）。
+ 在命令执行前，会`unwatch`当前客户端所有`watch`的键以避免`CPU`浪费，通过`unwatchAllKeys`函数实现；
+ 在所有命令执行后，会情况客户端的事务状态，通过`discardTransaction`函数实现；
  ```c
  void discardTransaction(client *c) {
      // 释放客户端释放状态分配的内容
      freeClientMultiState(c);
      // 初始化事务状态属性
      initClientMultiState(c);
      // 清理客户端事务相关标注
      c->flags &= ~(CLIENT_MULTI|CLIENT_DIRTY_CAS|CLIENT_DIRTY_EXEC);
      // unwatch 客户端监听的所有键
      unwatchAllKeys(c);
  }

  void freeClientMultiState(client *c) {
      int j;
  
      for (j = 0; j < c->mstate.count; j++) {
          int i;
          multiCmd *mc = c->mstate.commands+j;
  
          for (i = 0; i < mc->argc; i++)
              decrRefCount(mc->argv[i]);
          zfree(mc->argv);
      }
      zfree(c->mstate.commands);
  }
  
  void initClientMultiState(client *c) {
      c->mstate.commands = NULL;
      c->mstate.count = 0;
      c->mstate.cmd_flags = 0;
  }
  ```
事务执行前会有校验逻辑：
+ 检查客户端释放开启了事务；
  ```c
  if (!(c->flags & CLIENT_MULTI)) {
      addReplyError(c,"EXEC without MULTI");
      return;
  }
  ```
+ 被监听的键是否有改动或者命令参数等是否正确；
  ```c
  // 如果监听的键有改动，会有 CLIENT_DIRTY_CAS 标志
  if (c->flags & (CLIENT_DIRTY_CAS|CLIENT_DIRTY_EXEC)) {
      addReply(c, c->flags & CLIENT_DIRTY_EXEC ? shared.execaborterr :
                                                shared.nullmultibulk);
      discardTransaction(c);
      goto handle_monitor;
  }
  ```
+ 检查命令是否有写命令且节点不是主节点等；
  ```c
  if (!server.loading && server.masterhost && server.repl_slave_ro &&
      !(c->flags & CLIENT_MASTER) && c->mstate.cmd_flags & CMD_WRITE)
  {
      addReplyError(c,
          "Transaction contains write commands but instance "
          "is now a read-only slave. EXEC aborted.");
      discardTransaction(c);
      goto handle_monitor;
  }
  ```
## 取消事务
命令`discard`用于取消事务。命令格式如下：
```bash
DISCARD
```
`discard`命令源码如下：
```c
void discardCommand(client *c) {
    if (!(c->flags & CLIENT_MULTI)) {
        addReplyError(c,"DISCARD without MULTI");
        return;
    }
    discardTransaction(c);
    addReply(c,shared.ok);
}
```
首先判断当前客户端`client`是否开启事务，也就是是否有`CLIENT_MULTI`标志，只有开启了事务后，才可以取消。事务的取消通过`discardTransaction`函数实现，
`discardTransaction`函数详细介绍参考上一小节事务执行。最终，放弃一个事务时首先会将所有入队命令清空，
然后将`client`上事务相关的`flags`清空，最后将所有监听的`keys`取消监听。

## 监听键
命令`watch`用于实现一个乐观锁，在`exec`命令执行前监听任意数量的`keys`，并在`exec`命令执行时，检查被监听的键是否至少有一个被修改（被其它客户端修改），
如果有的话就放弃当前事务。`watch`命令只能在客户端进入事务状态之前执行。命令格式如下：
```bash
WATCH key [key ...]
```
`watch`命令的源码实现如下：
```c
void watchCommand(client *c) {
    int j;

    if (c->flags & CLIENT_MULTI) {
        addReplyError(c,"WATCH inside MULTI is not allowed");
        return;
    }
    for (j = 1; j < c->argc; j++)
        watchForKey(c,c->argv[j]);
    // 回复 ok
    addReply(c,shared.ok);
}
```
`watch`命令必须在`multi`命令之前执行，对于每一个需要监听的键，都会调用`watchForKey`函数将键添加到对应的字典属性：
```c
typedef struct watchedKey {
    robj *key;
    redisDb *db;
} watchedKey;

void watchForKey(client *c, robj *key) {
    list *clients = NULL;
    listIter li;
    listNode *ln;
    watchedKey *wk;

    // key 已经被监听，直接返回
    listRewind(c->watched_keys,&li);
    while((ln = listNext(&li))) {
        wk = listNodeValue(ln);
        if (wk->db == c->db && equalStringObjects(key,wk->key))
            return; /* Key already watched */
    }
    /* This key is not already watched in this DB. Let's add it */
    clients = dictFetchValue(c->db->watched_keys,key);
    if (!clients) {
        clients = listCreate();
        dictAdd(c->db->watched_keys,key,clients);
        incrRefCount(key);
    }
    listAddNodeTail(clients,c);
    /* Add the new key to the list of keys watched by this client */
    wk = zmalloc(sizeof(*wk));
    wk->key = key;
    wk->db = c->db;
    incrRefCount(key);
    listAddNodeTail(c->watched_keys,wk);
}
```
客户端对象`client`有一个`watched_keys`链表用于存储监听的`key`：
```c
typedef struct client {
    ...
    list *watched_keys;     /* Keys WATCHED for MULTI/EXEC CAS */
    ...
} client;
```
数据库对象`redisDB`有个`watched_keys`字典存储监听`key`相关，其中键对要监听的`key`，值为链表存放客户端对象`client`：
```c
typedef struct redisDb {
    ...
    dict *watched_keys;         /* WATCHED keys for MULTI/EXEC CAS */
    ...
} redisDb;
```
`watchForKey`函数逻辑主要有以下三步：
+ 检查监听的`key`是否已经在客户端对象`c->watched_keys`链表中，存在说明已经被监听，直接返回；
+ 键`key`没有被监听，将其添加到客户端对应数据库对象`redisDB`的`watched_keys`字典中；
+ 键`key`转为`watchedKey`对象，并添加到客户端对象`c->watched_keys`链表中；

对`redis`数据库键空间进行修改后都会调用`signalModifiedKey`函数：
```c
void signalModifiedKey(redisDb *db, robj *key) {
    touchWatchedKey(db,key);
}
```
进而`touchWatchedKey`函数被调用以通知监听的客户端：
```c
/* "Touch" a key, so that if this key is being WATCHed by some client the
 * next EXEC will fail. */
void touchWatchedKey(redisDb *db, robj *key) {
    list *clients;
    listIter li;
    listNode *ln;

    if (dictSize(db->watched_keys) == 0) return;
    clients = dictFetchValue(db->watched_keys, key);
    if (!clients) return;

    listRewind(clients,&li);
    while((ln = listNext(&li))) {
        client *c = listNodeValue(ln);
        // 添加监听此 key 的所有客户端标志 CLIENT_DIRTY_CAS
        c->flags |= CLIENT_DIRTY_CAS;
    }
}
```
`touchWatchedKey`函数会在数据库的`watchedKey`字典查找监听的`key`，并将监听此`key`的所有客户端标志增加`CLIENT_DIRTY_CAS`，
以标志此`key`被修改。

对于当前开启事务的客户端来说，在`exec`命令之前的命令都被入队，不会实际执行，所以`signalModifiedKey`函数不会调用。
`watch`命令的作用是防止其他客户端对数据库键的修改。

## 取消监听
命令`unwatch`用于取消`watch`命令对所有键的监控（针对当前客户端）。命令格式如下：
```bash
UNWATCH
```
`unwatch`命令源码实现如下：
```c
void unwatchCommand(client *c) {
    // 删除客户端监听的所有 key
    unwatchAllKeys(c);
    // 清除 CLIENT_DIRTY_CAS 标志
    c->flags &= (~CLIENT_DIRTY_CAS);
    // 回复 ok
    addReply(c,shared.ok);
}
```

# 事务特性
+ 在`exec`命令开始执行入队命令之前取消事务或者存在命令错误，整个事务命令都不会执行；
+ 在`exec`命令开始执行命令，某个命令失败，`redis`不会终止事务，而是继续执行其他命令，也就是不支持事务回滚；
+ `redis`事务不是原子性的，在事务过程中，其他客户端可以修改某个`key`。所以`redis`引入`watch`命令实现乐观锁机制；
+ `redis`事务中命令是相互独立的，后执行的命令不能依赖前面执行命令结果；
+ `redis`事务中每一个命令都需要回复，浪费网络资源，因为因为事务是一个批量执行的命令，按理说回复最终结果一次就行；

基于上述存在的问题，`redis`引入了`lua`脚本。

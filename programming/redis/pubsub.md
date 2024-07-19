> 基于`redis`源码分支`5.0`
# 发布订阅
`redis`提供的发布-订阅功能解耦了生产者和消费者。也就是生产者可以向指定的`channel`发送消息，而不需要关注消费者。
同理消费者订阅指定`channel`后可接收该`channel`的消息，而不需要关注生产者。

和发布订阅相关的数据结构定于在`server.h`文件的`redisServer`数据结构中（`client`对象也有）：
```c
dict *pubsub_channels;  /* Map channels to list of subscribed clients */
list *pubsub_patterns;  /* A list of pubsub_patterns */
```
+ `pubsub_channels`：一个字典结构，用于基于`channel`模式的发布订阅；其中`key`是`channel`的名字，`value`是个链表，
存放订阅该`channel`的每一个客户端；
+ `pubsub_patterns`：一个链表结构，每一个节点都是`pubsubPattern`数据类型
  ```c
  typedef struct pubsubPattern {
      client *client;
      robj *pattern;
  } pubsubPattern;
  ```
  + `client`：订阅该模式的客户端；
  + `pattern`：模式对象；

在`initServer`服务初始化中，对发布订阅结构初始化如下：
```c
server.pubsub_channels = dictCreate(&keylistDictType,NULL);
server.pubsub_patterns = listCreate();
```
其中`keylistDictType`结构定义如下：
```c
dictType keylistDictType = {
    dictObjHash,                /* hash function */
    NULL,                       /* key dup */
    NULL,                       /* val dup */
    dictObjKeyCompare,          /* key compare */
    dictObjectDestructor,       /* key destructor */
    dictListDestructor          /* val destructor */
};
```
键销毁函数`dictObjectDestructor`和值销毁函数`dictListDestructor`实现如下：
```c
// 键销毁函数
void dictObjectDestructor(void *privdata, void *val)
{
    DICT_NOTUSED(privdata);

    if (val == NULL) return; /* Lazy freeing will set value to NULL. */
    decrRefCount(val);
}
// 值销毁函数
void dictListDestructor(void *privdata, void *val)
{
    DICT_NOTUSED(privdata);
    listRelease((list*)val);
}
void listRelease(list *list)
{
    listEmpty(list);
    zfree(list);
}
```

## 发布命令
**命令`publish`** 用于将信息`message`发送到指定的频道`channel`。命令格式如下：
```bash
PUBLISH channel message
```
命令`publish`的源码实现如下：
```c
void publishCommand(client *c) {
    // 将消息分发到订阅的客户端
    int receivers = pubsubPublishMessage(c->argv[1],c->argv[2]);
    // 集群模式传播命令
    if (server.cluster_enabled)
        clusterPropagatePublish(c->argv[1],c->argv[2]);
    // 需要的化强制命令广播到从节点
    else
        forceCommandPropagation(c,PROPAGATE_REPL);
    // 回复订阅客户端数量
    addReplyLongLong(c,receivers);
}
```
发布消息实际工作是调用`pubsubPublishMessage`函数完成，`pubsubPublishMessage`函数执行逻辑有如下两步：
+ 从`pubsub_channels`字典中取出所有订阅该`channel`的客户端，依次往每个客户端发布消息；
  ```c
  int pubsubPublishMessage(robj *channel, robj *message) {
      int receivers = 0;
      dictEntry *de;
      listNode *ln;
      listIter li;
  
      /* Send to clients listening for that channel */
      de = dictFind(server.pubsub_channels,channel);
      if (de) {
          list *list = dictGetVal(de);
          listNode *ln;
          listIter li;
  
          listRewind(list,&li);
          // 依次往每个客户端发布消息
          while ((ln = listNext(&li)) != NULL) {
              client *c = ln->value;
  
              addReply(c,shared.mbulkhdr[3]);
              // 回复 "message"
              addReply(c,shared.messagebulk);
              // 回复 channel 的具体名字
              addReplyBulk(c,channel);
              // 回复消息内容
              addReplyBulk(c,message);
              receivers++;
          }
      }
      ...
  }
  ```
+ 遍历`pubsub_patterns`链表，比较每一个节点中的模式`pattern`字段是否和当前`channel`匹配，如果匹配就往对应的客户端发送消息；
  ```c
  int pubsubPublishMessage(robj *channel, robj *message) {
      ...
      /* Send to clients listening to matching channels */
      if (listLength(server.pubsub_patterns)) {
          listRewind(server.pubsub_patterns,&li);
          channel = getDecodedObject(channel);
          while ((ln = listNext(&li)) != NULL) {
              pubsubPattern *pat = ln->value;
              // 模式 pattern 和 channel 是否匹配 
              if (stringmatchlen((char*)pat->pattern->ptr,
                                  sdslen(pat->pattern->ptr),
                                  (char*)channel->ptr,
                                  sdslen(channel->ptr),0)) {
                  addReply(pat->client,shared.mbulkhdr[4]);
                  // 回复 "pmessage"
                  addReply(pat->client,shared.pmessagebulk);
                  // 回复 pattern 值
                  addReplyBulk(pat->client,pat->pattern);
                  // 回复实际 channel 名字
                  addReplyBulk(pat->client,channel);
                  // 回复具体消息
                  addReplyBulk(pat->client,message);
                  receivers++;
              }
          }
          // 在 getDecodedObject 函数中可能会增加引用或者返回临时遍历，
          // 这里需要恢复引用或者删除临时值
          decrRefCount(channel);
      }
      return receivers;
  }
  ```
命令`publish`返回结果是订阅客户端数量，样例如下：
```bash
# 向有多个订阅者的频道发送信息
redis> publish chat_room "hello~ everyone"
(integer) 3
```
`publish`命令执行完毕之后会同步到`redis`从服务中。这样，如果一个客户端订阅了从服务的`channel`，
在主服务中向该`channel`推送消息时，该客户端也能收到推送的消息。
> 相关请求命令执行完后会调用`propagate`函数执行命令的传播，这里不做具体介绍。

## 订阅命令
**命令`subscribe`** 用于订阅给定的一个或多个频道的信息。命令格式如下：
```bash
SUBSCRIBE channel [channel ...]
```
命令`subscribe`的源码实现如下：
```c
void subscribeCommand(client *c) {
    int j;
    // 依次对指定的每一个 channel 执行订阅操作
    for (j = 1; j < c->argc; j++)
        pubsubSubscribeChannel(c,c->argv[j]);
    // 客户端置CLIENT_PUBSUB标志，进入pub/sub模式
    c->flags |= CLIENT_PUBSUB;
}
```
对某一个`channel`执行订阅实现是调用`pubsubSubscribeChannel`函数：
```c
int pubsubSubscribeChannel(client *c, robj *channel) {
    dictEntry *de;
    list *clients = NULL;
    int retval = 0;
    // 将 channel 作为 key 添加到客户端的 pubsub_channels 字典
    // 成功说明 channel 作为键不存在，否则说明字典已经存在 channel 键
    if (dictAdd(c->pubsub_channels,channel,NULL) == DICT_OK) {
        retval = 1;
        // channel 在客户端 pubsub_channels 字典，引用计数加 1
        incrRefCount(channel);
        // 从服务端 pubsub_channels 字典查找 channel 键
        de = dictFind(server.pubsub_channels,channel);
        if (de == NULL) {
            // 新的 channel 作为键，创建一个链表存放订阅此 channel 所有客户端
            clients = listCreate();
            dictAdd(server.pubsub_channels,channel,clients);
            // channel 在服务端 pubsub_channels 字典，引用计数加 1
            incrRefCount(channel);
        } else {
            clients = dictGetVal(de);
        }
        // 将客户端添加到链表中
        listAddNodeTail(clients,c);
    }
    /* Notify the client */
    addReply(c,shared.mbulkhdr[3]);
    // 回复 "subscribe"
    addReply(c,shared.subscribebulk);
    // 回复 channel 名字
    addReplyBulk(c,channel);
    // 回复客户端订阅的频道数（channel + pattern )
    addReplyLongLong(c,clientSubscriptionsCount(c));
    return retval;
}
```
`subscribe`命令返回样例如下：
```bash
# 订阅 msg 和 chat_room 两个频道

# 1 - 6 行是执行 subscribe 之后的反馈信息
# 第 7 - 9 行才是接收到的第一条信息
# 第 10 - 12 行是第二条

redis> subscribe msg chat_room
1) "subscribe"       # 返回值的类型：显示订阅成功
2) "msg"             # 订阅的频道名字
3) (integer) 1       # 目前已订阅的频道数量

1) "subscribe"
2) "chat_room"
3) (integer) 2

1) "message"         # 返回值的类型：信息
2) "msg"             # 来源(从那个频道发送过来)
3) "hello moto"      # 信息内容

1) "message"
2) "chat_room"
3) "testing...haha"
```

客户端订阅成功后，会设置客户端标志为`c->flags |= CLIENT_PUBSUB`，使其进入`pub/sub`模式。在该模式下，只能执行`ping`、`quit`、
`subscribe`、`unsubcribe`、`psubscribe`和`punsubcribe`命令，实现方式是在`processCommand`函数中完成：
```c
/* Only allow SUBSCRIBE and UNSUBSCRIBE in the context of Pub/Sub */
if (c->flags & CLIENT_PUBSUB &&
    c->cmd->proc != pingCommand &&
    c->cmd->proc != subscribeCommand &&
    c->cmd->proc != unsubscribeCommand &&
    c->cmd->proc != psubscribeCommand &&
    c->cmd->proc != punsubscribeCommand) {
    addReplyError(c,"only (P)SUBSCRIBE / (P)UNSUBSCRIBE / PING / QUIT allowed in this context");
    return C_OK;
}
```
## 取消订阅
**命令`unsubcribe`** 用于客户端退订给定的频道，如果没有频道被指定，也即是，一个无参数的`UNSUBSCRIBE`调用被执行，那么客户端使用`SUBSCRIBE`命令订阅的所有频道都会被退订。
命令格式如下：
```bash
UNSUBSCRIBE [channel [channel ...]]
```
`unsubcribe`命令源码实现如下：
```c
void unsubscribeCommand(client *c) {
    if (c->argc == 1) {
        // 如果没有指定 channel 参数，取消所有订阅的频道
        pubsubUnsubscribeAllChannels(c,1);
    } else {
        int j;
        // 依次取消指定的频道 channel
        for (j = 1; j < c->argc; j++)
            pubsubUnsubscribeChannel(c,c->argv[j],1);
    }
    // 如果客户端没有订阅的频道，取消 CLIENT_PUBSUB 模式
    if (clientSubscriptionsCount(c) == 0) c->flags &= ~CLIENT_PUBSUB;
}
```
不管是取消指定的`channel`，还是取消所有的频道，底层都是调用`pubsubUnsubscribeChannel`函数，其源码实现如下：
```c
int pubsubUnsubscribeChannel(client *c, robj *channel, int notify) {
    dictEntry *de;
    list *clients;
    listNode *ln;
    int retval = 0;
    // 将引用计数加1，因为客户端对象 pubsub_channels 字典和服务端对象 pubsub_channels 字典存放 channel 键都是指针，
    // 避免过早删除 channel 实际对象
    incrRefCount(channel);
    // 从客户端对象 pubsub_channels 字典删除 channel 键
    if (dictDelete(c->pubsub_channels,channel) == DICT_OK) {
        retval = 1;
        // 从服务端 pubsub_channels 字典查找 channel 键对应的链表（存放所有订阅此 channel 的客户端）
        // 从链表中产出此客户端，也就是此客户端不在订阅此 channel
        de = dictFind(server.pubsub_channels,channel);
        serverAssertWithInfo(c,NULL,de != NULL);
        clients = dictGetVal(de);
        ln = listSearchKey(clients,c);
        serverAssertWithInfo(c,NULL,ln != NULL);
        listDelNode(clients,ln);
        // 当前 channel 没有订阅的客户端了，是否 channel 对应的键值对
        if (listLength(clients) == 0) {
            dictDelete(server.pubsub_channels,channel);
        }
    }
    /* Notify the client */
    if (notify) {
        addReply(c,shared.mbulkhdr[3]);
        // 回复 "unsubcribe"
        addReply(c,shared.unsubscribebulk);
        // 回复 channel 的名字
        addReplyBulk(c,channel);
        // 回复当前客户端订阅的频道数
        addReplyLongLong(c,dictSize(c->pubsub_channels)+
                       listLength(c->pubsub_patterns));

    }
    decrRefCount(channel); /* it is finally safe to release it */
    return retval;
}
```
取消订阅就是将客户端和服务端`pubsub_channels`字典中对应的数据删除。如果当前客户端没有订阅的频道，则退出`pub/sub`模式。

`unsubcribe`命令返回样例如下：
```bash
my-redis:6379> UNSUBSCRIBE channel1
1) "unsubscribe"
2) "channel1"
3) (integer) 0
```

## 订阅指定模式
**命令`psubscribe`** 用于订阅一个或多个符合给定模式的频道。每个模式以`*`作为匹配符，比如`it*`匹配所有以`it`开头的频道（`it.news`、`it.blog`、`it.tweets`等）。
命令格式如下：
```bash
PSUBSCRIBE pattern [pattern ...]
```
`psubscribe`命令实现源码如下：
```c
void psubscribeCommand(client *c) {
    int j;

    for (j = 1; j < c->argc; j++)
        pubsubSubscribePattern(c,c->argv[j]);
    // 客户端置CLIENT_PUBSUB标志，进入pub/sub模式
    c->flags |= CLIENT_PUBSUB;
}
```
订阅指定模式函数`pubsubSubscribePattern`实现如下：
```c
int pubsubSubscribePattern(client *c, robj *pattern) {
    int retval = 0;
    // 从客户端 pubsub_patterns 链表查找 pattern，如果存在，则说明客户端已经订阅过，否则执行订阅逻辑
    if (listSearchKey(c->pubsub_patterns,pattern) == NULL) {
        retval = 1;
        pubsubPattern *pat;
        // 添加到客户端 pubsub_patterns 链表
        listAddNodeTail(c->pubsub_patterns,pattern);
        incrRefCount(pattern);
        pat = zmalloc(sizeof(*pat));
        pat->pattern = getDecodedObject(pattern);
        pat->client = c;
        // 添加服务端 pubsub_patterns 链表
        listAddNodeTail(server.pubsub_patterns,pat);
    }
    /* Notify the client */
    addReply(c,shared.mbulkhdr[3]);
    // 回复 "psubscribe"
    addReply(c,shared.psubscribebulk);
    // 回复 pattern 的值
    addReplyBulk(c,pattern);
    // 回复客户端订阅频道数
    addReplyLongLong(c,clientSubscriptionsCount(c));
    return retval;
}
```
订阅指定模式实际是操作客户端和服务端的`pubsub_patterns`链表。`punsubcribe`命令返回样例如下：
```bash
# 订阅 news.* 和 tweet.* 两个模式

# 第 1 - 6 行是执行 psubscribe 之后的反馈信息
# 第 7 - 10 才是接收到的第一条信息
# 第 11 - 14 是第二条

redis> psubscribe news.* tweet.*
1) "psubscribe"                  # 返回值的类型：显示订阅成功
2) "news.*"                      # 订阅的模式
3) (integer) 1                   # 目前已订阅的模式的数量

1) "psubscribe"
2) "tweet.*"
3) (integer) 2

1) "pmessage"                    # 返回值的类型：信息
2) "news.*"                      # 信息匹配的模式
3) "news.it"                     # 信息本身的目标频道
4) "Google buy Motorola"         # 信息的内容

1) "pmessage"
2) "tweet.*"
3) "tweet.huangz"
4) "hello"
```
客户端订阅成功后，会设置客户端标志为`c->flags |= CLIENT_PUBSUB`，使其进入`pub/sub`模式。

## 取消订阅指定模式
**命令`punsubcribe`** 用于指示客户端退订所有给定模式。如果没有模式被指定，也即是，一个无参数的`PUNSUBSCRIBE`调用被执行，那么客户端使用`PSUBSCRIBE`命令订阅的所有模式都会被退订。
命令格式如下：
```bash
PUNSUBSCRIBE [pattern [pattern ...]]
```
`punsubcribe`命令实现逻辑和`unsubcribe`类似，只是操作`pubsub_patterns`链表，这里不做介绍。命令返回样例如下：
```bash
my-redis:6379> PUNSUBSCRIBE channel*
1) "punsubscribe"
2) "channel*"
3) (integer) 0
```

## 查看订阅与发布状态
**命令`pubsub`** 用于查看订阅与发布系统状态。命令格式如下：
```bash
PUBSUB <subcommand> [argument [argument ...]]
```
`<subcommand>`的取值有如下几种：
+ `help`：显示`pubsub`命令使用信息；
+ `channels`：使用方式`PUBSUB CHANNELS [<pattern>]`，返回当前活跃频道列表，如果不传`pattern`，返回所有活跃`channel`，否则只返回和`pattern`匹配的`channel`。
活跃频道指的是那些至少有一个订阅者的频道，只查询`pubsub_channels`字典，不涉及`pubsub_patterns`列表。
+ `numsub`：使用方式`PUBSUB NUMSUB [Channel_1 ... Channel_N]`，返回给定`channel`订阅者数量。只查询`pubsub_channels`字典，不涉及`pubsub_patterns`列表。
+ `numpat`：使用方式`PUBSUB NUMPAT`，返回客户端订阅的所有模式的数量总和。
  ```c
  addReplyLongLong(c,listLength(server.pubsub_patterns));
  ```

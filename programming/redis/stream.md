> 基于`redis`源码分支`5.0`
# Stream
`redis`的`stream`对象主要用于消息队列，其底层使用[`listpack`](./listpack.md)和[`rax`](./rax.md)树。`stream`主要由四部分组成：
+ 消息；
+ 生产者；
+ 消费者；
+ 消费组；

每一个消息具有如下特点：
+ 每个消息有唯一的消息`ID`，消息`ID`严格递增；
+ 消息内容由一个/多个键值对组成；

生产者负责向消息队列中生产消息，消费者消费某个消息流。消费者可以归属某个消费组，也可以不归属任何消费组。
当消费者不归属于任何消费组时，该消费者可以消费消息队列中的任何消息。

消费组具有如下特点：
+ 每个消费组通过组名唯一标识，每个消费组都可以消费该消息队列的全部消息，多个消费组之间相互独立；
+ 每个消费组可以有多个消费者，消费者通过名称唯一标识，一个消息只能由该组的一个成员消费；
+ 每个消费组都有一个待确认消息队列用于维护该消费组已经消费但没有确认的消息；
+ 每个消费组中的每个成员也有一个待确认消息队列，维护着该消费者已经消费尚未确认的消息；

## 数据结构设计
### 消息
**消息`ID`** 由两部分组成：消息创建的时间（从`1970-01-01`至今的毫秒数）和序列号组成。
```c
typedef struct streamID {
    uint64_t ms;        /* Unix time in milliseconds. */
    uint64_t seq;       /* Sequence number. */
} streamID;
```
如果消息`ID`的毫秒部分相同，则序列号会递增以确保消息`ID`的唯一性。

**消息内容**会存放在`listpack`对象中。`listpack`中每个元素都是一个`entry`，每个`listpack`可以存储的元素数量由配置文件中`stream-node-max-bytes`和`stream-node-max-entries`决定。
+ 每个`stream`消息会占用多个`entry`；
+ 每个`listpack`对象会存储多个消息；

每个`listpack`对象在创建时，都会构造该`listpack`的`master entry`项（**根据第一个插入的消息构建**），`master entry`结构如下：
```bash
+-------+---------+------------+---------+--/--+---------+---------+-+
| count | deleted | num-fields | field_1 | field_2 | ... | field_N |0|
+-------+---------+------------+---------+--/--+---------+---------+-+
```
`master entry`中的每一个字段都是`listpack`中的一个`entry`。各个字段含义如下：
+ `count`：当前`listpack`中所有未删除的消息个数（有效的消息个数）。
+ `deleted`：当前`listpack`中所有标记为删除的消息个数。
+ `num-fields`：为接下来`field_x`的个数。
+ `field_x`：第一个插入消息的所有`field`。
+ `0`：一个标示位，用于从后往前遍历该`listpack`所有消息时使用。

继续存储消息，如果该消息的`field`域和`master entry`的`field`完全一样，则不需要在此存储`field`域，此时存储的消息结构如下：
```bash
+-----+--------+-------+-/-+-------+--------+
|flags|entry-id|value-1|...|value-N|lp-count|
+-----+--------+-------+-/-+-------+--------+
```
+ `flags`：该消息的标志位（每一个添加的消息都有标志位）。
  + `STREAM_ITEM_FLAG_NONE`：无特殊标示
  + `STREAM_ITEM_FLAG_DELETED`：标识该消息被删除
  + `STREAM_ITEM_FLAG_SAMEFIELDS`：标识该消息的`field`与`master entry`的`field`完全一样
+ `entry-id`：由两个`entry`组成：值分别是该消息`ID`的`ms`和`seq`部分与`master entry`项`ID`的`ms`和`seq`差值。
  ```c
  lp = lpAppendInteger(lp,id.ms - master_id.ms);
  lp = lpAppendInteger(lp,id.seq - master_id.seq);
  ```
  其中`id`是该消息的`ID`，`master_id`是第一个插入消息的`ID`。
+ `value-x`：该消息每个`field`对应的值。
+ `lp-count`：该消息占用`listpack`元素`entry`个数，也就是`3 + N`。

如果该消息的`field`域和`master entry`的`field`不完全一样，此时消息的存储结构如下：
```bash
+-----+--------+----------+-------+-------+-/-+-------+-------+--------+
|flags|entry-id|num-fields|field-1|value-1|...|field-N|value-N|lp-count|
+-----+--------+----------+-------+-------+-/-+-------+-------+--------+
```
此时会存储该消息相关的`field`及`num-fields`值，同时`lp-count`值变为`4 + 2N`。

### Stream结构
**`stream`结构**定义如下：
```c
typedef struct stream {
    rax *rax;               /* The radix tree holding the stream. */
    uint64_t length;        /* Number of elements inside this stream. */
    streamID last_id;       /* Zero if there are yet no items. */
    rax *cgroups;           /* Consumer groups dictionary: name -> streamCG */
} stream;
```
+ `rax`：`radix tree`对象，存放生产者生产的所有消息，其中消息`ID`为键，消息内容存储在`rax`节点的`value`中。
+ `length`：消息个数，不包括标记为删除的消息。
+ `last_id`：最后插入的消息`ID`，如果为空没有消息，则为`0`。
+ `cgroups`：存放所有的消费组，其中消费组的组名为键，`streamCG`为值存放在`rax`对象中。

**消费组**通过组名区分，每个组名都会关联一个`streamCG`对象，其定义如下：
```c
typedef struct streamCG {
    streamID last_id;       /* Last delivered (not acknowledged) ID for this
                               group. Consumers that will just ask for more
                               messages will served with IDs > than this. */
    rax *pel;               /* Pending entries list. This is a radix tree that
                               has every message delivered to consumers (without
                               the NOACK option) that was yet not acknowledged
                               as processed. The key of the radix tree is the
                               ID as a 64 bit big endian number, while the
                               associated value is a streamNACK structure.*/
    rax *consumers;         /* A radix tree representing the consumers by name
                               and their associated representation in the form
                               of streamConsumer structures. */
} streamCG;
```
+ `last_id`：该消费组已经确认的最后一个消息`ID`。
+ `pel`：`Pending entries list`存放该消费组没有确认的消息，其中消息`ID`为键，`streamNACK`对象为值。
+ `consumers`：该消费组包含的所有消费者，其中消费者的名称为键，`streamConsumer`对象为值。

**消费者**对象`streamConsumer`的定义如下：
```c
typedef struct streamConsumer {
    mstime_t seen_time;         /* Last time this consumer was active. */
    sds name;                   /* Consumer name. This is how the consumer
                                   will be identified in the consumer group
                                   protocol. Case sensitive. */
    rax *pel;                   /* Consumer specific pending entries list: all
                                   the pending messages delivered to this
                                   consumer not yet acknowledged. Keys are
                                   big endian message IDs, while values are
                                   the same streamNACK structure referenced
                                   in the "pel" of the conumser group structure
                                   itself, so the value is shared. */
} streamConsumer;
```
+ `seen_time`：该消费者上次活跃的时间。
+ `name`：消费者的名字。
+ `pel`：该消费者没有确认的消息，其中消息`ID`为键，`streamNACK`对象为对应的值。

**未确认消息**对象`streamNACK`的定义如下（消费者中的`pel`和消费组中的`pel`中`streamNACK`对象是共享的）：
```c
typedef struct streamNACK {
    mstime_t delivery_time;     /* Last time this message was delivered. */
    uint64_t delivery_count;    /* Number of times this message was delivered.*/
    streamConsumer *consumer;   /* The consumer this message was delivered to
                                   in the last delivery. */
} streamNACK;
```
+ `delivery_count`：该消息已经发送的次数。
+ `delivery_time`：该消息最后发送给消费方的时间。
+ `consumer`：该消息当前归属的消费者。

## 初始化

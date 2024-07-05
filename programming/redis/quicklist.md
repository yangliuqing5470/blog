> 基于`redis`源码分支`5.0`
# quicklist
由于`ziplist`优点是节省空间，但不能存储太多元素，因为有连锁更新的确定，所以`quicklist`结合链表和`ziplist`的优势，在存储多的元素同时也可以进一步节省空间。

简单来说，一个`quicklist`就是一个链表（双向链表），而链表中的每个元素又是一个`ziplist`。

## 数据结构定义
`quicklist`中每一个节点`quicklistNode`的数据结构如下：
```c
typedef struct quicklistNode {
    struct quicklistNode *prev;
    struct quicklistNode *next;
    unsigned char *zl;
    unsigned int sz;             /* ziplist size in bytes */
    unsigned int count : 16;     /* count of items in ziplist */
    unsigned int encoding : 2;   /* RAW==1 or LZF==2 */
    unsigned int container : 2;  /* NONE==1 or ZIPLIST==2 */
    unsigned int recompress : 1; /* was this node previous compressed? */
    unsigned int attempted_compress : 1; /* node can't compress; too small */
    unsigned int extra : 10; /* more bits to steal for future usage */
} quicklistNode;
```
+ `prev`：前一个`quicklistNode`节点指针；
+ `next`：后一个`quicklistNode`节点指针；
+ `zl`：指向该节点对应的`ziplist`对象；
+ `sz`：`ziplist`对象的字节大小；
+ `count`：`ziplist`对象中元素的个数；
+ `encoding`：节点数据编码方式，取值`1`表示`RAW`，`2`表示`LZF`；
+ `container`：节点数据存储方式，`1`表示`NONE`，`2`表示`ZIPLIST`；
+ `recompress`：数据是否被压缩；
+ `attempted_compress`：数据能否被压缩；
+ `extra`：预留的`10`位数据；

`quicklist`的数据结构定义如下：
```c
typedef struct quicklist {
    quicklistNode *head;
    quicklistNode *tail;
    unsigned long count;        /* total count of all entries in all ziplists */
    unsigned long len;          /* number of quicklistNodes */
    int fill : 16;              /* fill factor for individual nodes */
    unsigned int compress : 16; /* depth of end nodes not to compress;0=off */
} quicklist;
```
+ `head`：指向首节点；
+ `tail`：指向尾节点；
+ `count`：链表中存储的元素总数，也就是所有`ziplist`对象中元素个数；
+ `len`：链表节点的个数；
+ `fill`：为正数表示每个`quicklistNode`节点中`ziplist`对象最大元素个数；为负数，取值有如下（可以通过修改配置文件中的`list-max-ziplist-size`选项，配置`ziplist`节点占内存大小）：
  + `-1`：`ziplist`节点最大为`4KB`；
  + `-2`：`ziplist`节点最大为`8KB`；
  + `-3`：`ziplist`节点最大为`16KB`；
  + `-4`：`ziplist`节点最大为`32KB`；
  + `-5`：`ziplist`节点最大为`64KB`；
+ `compress`：考虑`quicklistNode`节点个数较多时，我们经常访问的是两端的数据，为了进一步节省空间，`redis`允许对中间的`quicklistNode`节点进行压缩，
通过修改配置文件`list-compress-depth`进行配置，即设置`compress`参数，该项的具体含义是两端各有`compress`个节点不压缩；

下面给出`quicklist`结构示意图（实际是个双向链表，图没有表示出来）：
```bash
quicklist 头节点                          quicklist 尾节点
+-------------+      +-------------+      +-------------+
|quicklistNode| ---> |quicklistNode| ---> |quicklistNode|
+-------------+      +-------------+      +-------------+
      |                    |                    |
      v                    v                    v
  +-------+            +-------+            +-------+
  |ziplist|            |ziplist|            |ziplist|
  +-------+            +-------+            +-------+
```
`quicklist`是一个双向链表，插入元素的时候会先判断要插入的元素是否可以插入到插入位置的`ziplist`中，以下两个条件满足一个表示可以插入：
+ 单个`ziplist`是否不超过`8KB`；
+ 单个`ziplist`里的元素个数是否满足要求；

否则新建立一个`quicklistNode`节点存放新插入的元素。

`quicklist`通过控制每个`quicklistNode`中`ziplist`的大小或是元素个数，就有效减少了在`ziplist`中新增或修改元素后，
发生连锁更新的情况，从而提供了更好的访问性能。

> 基于`redis`源码分支`5.0`
# 压缩列表
压缩列表`ziplist`是列表键和哈希键的底层实现之一。当一个列表键包含少量的列表项，且每个列表项是小整数或者长度比较短的字符串，
`redis`使用压缩列表作为列表键的底层实现。或者当一个哈希键包含少量的键值对，且每个键值对的键和值要么是小整数值或长度比较短的字符串，
`redis`使用压缩列表作为哈希键的底层实现。

压缩列表`ziplist`是`redis`为了节约内存开发的，由一系列特殊编码的连续内存块组成的顺序型数据结构。
一个压缩列表可以包含任意个节点`entry`，每个节点保存一个字节数组（字符串），或一个整数。

节约内存体现如下：
+ 压缩列表使用连续的存储空间，避免内存碎片；
+ 和数组相比，数据每个元素大小是根据最大元素类型定义的，对于小元素类型存在浪费。但压缩列表中的每一`entry`大小是根据实际存储值决定，
也就是没有浪费，`entry`大小可能都不一样；
+ 和链表相比，压缩列表由于存储小整数和短字符串，节约了链表上指针开销（一个指针占用字节蛮多的，`64`位操作系统是`8`字节）；

## 数据结构定义
`redis`使用字节数组表示压缩列表`ziplist`，`ziplist`的结构如下：
```bash
+-------+------+-----+-----+-----+-----+-----+-----+
|zlbytes|zltail|zllen|entry|entry| ... |entry|zlend|
+-------+------+-----+-----+-----+-----+-----+-----+
```
+ `zlbytes`：`4`个字节（`uint32_t`类型），记录整个压缩列表占用的内存字节数。用于压缩列表进行内存重分配或者计算特殊值`zlend`位置。
+ `zltail`：`4`个字节（`uint32_t`类型），记录压缩列表最后一个`entry`到压缩列表起始地址有多少字节，
通过这个偏移量，不需要遍历完整的压缩列表就可以知道压缩列表最后`entry`的地址。
+ `zllen`：`2`个字节（`uint16_t`类型），记录压缩列表节点数量，当实际压缩列表节点数量超过`2^16-1`时，
需要遍历整个`entry`项才可以获取实际节点数量。
+ `entry`：压缩列表中保存的节点，节点的长度由节点保存的内存决定。
+ `zlend`：`1`个字节（`uint8_t`类型），特殊值`0xFF`，表示压缩列表的结束。

节点`entry`的结构如下：
```bash
+-------+--------+----------+
|prevlen|encoding|entry-data|
+-------+--------+----------+
```
+ `prevlen`：记录压缩列表前一个节点的长度，以字节为单位。
  + 如果前一个节点长度小于`254`个字节，则`prevlen`的值用`1`个字节表示；
  + 如果前一个节点长度大于等于`254`个字节，则`prevlen`的值用`5`个字节表示，且第一个字节设置为`0xFE`，
  接下来的`4`个字节表示前一个节点的长度；
+ `encoding`：记录`entry-data`属性所保存数据类型以及长度，`encoding`的值大小可以是`1`字节、`2`字节或者`5字节`。
  + `encoding`前两位取值`00`，表示`entry-data`是一个**字符串**，且字符串长度小于等于`63`（`6 bits`），此时`encoding`大小是`1`字节。
  + `encoding`前两位取值`01`，表示`entry-data`是一个**字符串**，且字符串长度小于等于`16384`（`14 bits`），此时`encoding`大小是`2`字节。
  + `encoding`前两位取值`10`，表示`entry-data`是一个**字符串**，且字符串长度小于等于`2^32-1`（后面`4`字节表示长度），此时`encoding`大小是`5`字节。
  + `encoding`前两位取值`11`，表示`entry-data`是一个**整数**，`encoding`大小是`1`字节。
    + `encoding`取值`11000000`，表示`entry-data`保存整数是`int16_t`类型数据；
    + `encoding`取值`11010000`，表示`entry-data`保存整数是`int32_t`类型数据；
    + `encoding`取值`11100000`，表示`entry-data`保存整数是`int64_t`类型数据；
    + `encoding`取值`11110000`，表示`entry-data`保存整数是`24`位有符号数据；
    + `encoding`取值`11111110`，表示`entry-data`保存整数是`8`位有符号整数；
    + `encoding`取值`1111xxxx`，其中`xxxx`在`(0000, 1101]`之间，表示`0-12`整数（`xxxx`值减`1`），此时没有`entry-data`属性；
+ `entry-data`：保存的实际值，一个整数或者字符串。

每个节点由于有`prevlen`属性以及压缩列表有`zltail`属性，可以实现从节点尾部向前开始遍历节点。

## 创建压缩列表
压缩列表的创建实现如下：
```c
/* Create a new empty ziplist. */
unsigned char *ziplistNew(void) {
    // 计算压缩列表头（zlbytes, zltail, zllen）+ 尾（zlend）内存大小
    unsigned int bytes = ZIPLIST_HEADER_SIZE+ZIPLIST_END_SIZE;
    // 一个字符数组表示压缩列表
    unsigned char *zl = zmalloc(bytes);
    // 初始化压缩列表的总大小（单位字节），也就是初始化 zlbytes 值
    ZIPLIST_BYTES(zl) = intrev32ifbe(bytes);
    // 初始化 zltail 值
    ZIPLIST_TAIL_OFFSET(zl) = intrev32ifbe(ZIPLIST_HEADER_SIZE);
    // 初始化 zllen 值为 0
    ZIPLIST_LENGTH(zl) = 0;
    // 初始化 zlend 值为 0xFF
    zl[bytes-1] = ZIP_END;
    return zl;
}
```
其中相关的宏定义如下：
```c
/* The size of a ziplist header: two 32 bit integers for the total
 * bytes count and last item offset. One 16 bit integer for the number
 * of items field. */
#define ZIPLIST_HEADER_SIZE     (sizeof(uint32_t)*2+sizeof(uint16_t))

/* Size of the "end of ziplist" entry. Just one byte. */
#define ZIPLIST_END_SIZE        (sizeof(uint8_t))

/* Return total bytes a ziplist is composed of. */
#define ZIPLIST_BYTES(zl)       (*((uint32_t*)(zl)))

/* Return the offset of the last item inside the ziplist. */
#define ZIPLIST_TAIL_OFFSET(zl) (*((uint32_t*)((zl)+sizeof(uint32_t))))

/* Return the length of a ziplist, or UINT16_MAX if the length cannot be
 * determined without scanning the whole ziplist. */
#define ZIPLIST_LENGTH(zl)      (*((uint16_t*)((zl)+sizeof(uint32_t)*2)))

#define ZIP_END 255         /* Special "end of ziplist" entry. */
```
宏定义主要是根据内存布局，取对应地址的值以获取对应属性值，内存布局参考上面的数据结构定义。

执行创建压缩列表后，对应的数据结构如下（上面是每个属性占空间大小，下面是每个属性取值）：
```bash
  4字节   4字节  2字节  1字节
+-------+------+-----+-----+
|zlbytes|zltail|zllen|zlend|
+-------+------+-----+-----+
  11      10     0     255
```

## 节点添加

```bash
  4字节   4字节  2字节  1字节
+-+-+-+-+-+-+-+-+--+--+-----+
|zlbytes|zltail |zllen|zlend|
+-+-+-+-+-+-+-+-+--+--+-----+
```
压缩列表节点插入流程主要分三步：
+ 将元素内容编码，也就是确定节点各个属性值及空间大小；
+ 压缩列表空间重分配；
+ 数据移动；

插入相关的`API`定义如下：
```c
unsigned char *__ziplistInsert(unsigned char *zl, unsigned char *p, unsigned char *s, unsigned int slen);
```
+ `zl`：表示压缩列表的首地址；
+ `p`：节点要插入的位置地址；
+ `s`：插入元素的地址，用字节数组表示数据；
+ `slen`：插入元素的长度；

元素的插入有如下三种情况

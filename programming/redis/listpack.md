> 基于`redis`源码分支`5.0`

# listpack
`listpack`数据结构和之前介绍的[ziplist数据结构](./ziplist.md)很像，其实`listpack`是作为`ziplist`的替代，
主要解决`ziplist`中的连锁更新问题，因为`listpack`不记录上一个元素节点的大小信息，所以不会存在连锁更新问题。

## listpack数据结构
`listpack`（`A lists of strings serialization format`）是一个序列化格式的字符串列表，数据结构如下：
```bash
+------------+----------+--------+-----+--------+-----+
| total bytes| num elem | entry1 | ... | entryN | end |
+------------+----------+--------+-----+--------+-----+
```
+ `total bytes`：整个`listpack`对象的空间大小，`4`个字节；
+ `num elem`：`listpack`对象包含的元素个数，也就是`entry`的个数，`2`个字节，如果`num elem`值是`65535`，
说明实际元素的个数可能比`65535`大，为了获取实际的元素个数，需要遍历整个`listpack`；
+ `end`：`listpack`对象结束标志，`1`个字节，值为`0xFF`；
+ `entryx`：实际存储的元素。`enrty`可以存储字符串或者整数，`entry`的由三部分组成：
  ```bash
  +--------+---------+---------+
  | encode | content | backlen |
  +--------+---------+---------+
  ``` 
  + `encode`：编码类型，决定后面`content`存储的内容，`1`个字节，`encode`值和含义说明如下：
    + 取值`0xxx xxxx`：`7`位长度的无符号整数，范围`0-127`，后`7`位为数据；
    + 取值`110x xxxx`：`13`位长度表示的有符号整数，范围`-4096-4095`，后`5`位及接下来一个字节表示数据；
    + 取值`1111 0001`：表示`16`位有符号整数，范围`-32768-32767`，接下来`2`个字节表示数据；
    + 取值`1111 0010`：表示`24`位有符号整数，范围`-8388608-8388607`，接下来`3`个字节表示数据；
    + 取值`1111 0011`：表示`32`位有符号整数，范围`-2147483648-2147483647`，接下来`4`个字节表示数据；
    + 取值`1111 0100`：表示`64`位有符号整数，接下来`8`个字节表示数据；
    + 取值`10xx xxxx`：`6`位长度表示的无符号整数字符串长度，后`6`位表示字符串长度，接下来是字符串数据；
    + 取值`1110 xxxx`：`12`位长度表示的无符号整数字符串长度，后`4`位是高位，接下里`1`个字节是低位，在之后才是字符串数据；
    + 取值`1111 0000`：`32`位长度表示的无符号整数字符串长度，接下来`4`个字节表示字符串长度，之后才是字符串数据；
    
    对于负整数，`redis`将其转为正整数存储，例如对于`13`位整数存储中，存储范围`[0, 8191]`，
    其中`[0, 4095]`表示`0-4095`，`[4096, 8191]`表示`-4096 - -1`。
  + `content`：实际存储的数据，字符串或者整数；
  + `backlen`：值表示当前`entry`的`encode`加`content`的长度，单位字节，占用字节数小于等于`5`；
  `backlen`的每个字节的第一位是标志位，`0`表示结束，`1`表示未结束，剩下的七位为有效位。
  `backlen`用于`listpack`对象从后往前遍历。`backlen`的编码和解码规则如下：
    ```bash
            +-+-+-+-+-+-+-+-+
    1个字节 |0|x|x|x|x|x|x|x|
            +-+-+-+-+-+-+-+-+

            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    2个字节 |0|x|x|x|x|x|x|x|1|x|x|x|x|x|x|x|
            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
  
            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    3个字节 |0|x|x|x|x|x|x|x|1|x|x|x|x|x|x|x|1|x|x|x|x|x|x|x|
            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    4个字节 |0|x|x|x|X|x|x|x|1|x|x|x|x|x|x|x|1|x|x|x|x|x|x|x|1|x|x|x|x|x|x|x|
            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    5个字节 |0|x|x|x|X|x|x|x|1|x|x|x|x|x|x|x|1|x|x|x|x|x|x|x|1|x|x|x|x|x|x|x|1|x|x|x|x|x|x|x|
            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    ```
    编码规则：从左往右。解码规则：从右往左。例如数字`136`的二进制是`0000001 0001000`，需要`2`个字节存储（每个字节只有七位是有效的），
    编码流程如下：
    + 右移`7`位，保留高`7`位，也就是`0000001`，保存在`p[0]`位置，`p[0]`的第一位为`0`；
    + 将剩下的低`7`位，也就是`00010001`，保存在`p[1]`位置，`p[1]`的第一位为`1`；
    此时`backlen`的二进制值是`00000001 10001000`；

    解码的流程如下：
    + 解码`p[1]`的值`10001000`取低`7`位`0001000`，也就是十进制`8`，保存为`v=8`；
    取最高位值看是否为`1`，如果为`1`继续取下一个字节；
    + 解码`p[0]`的值`00000001`，取低`7`位`0000001`，因为是解码的第二个字节，将其左移`7`位，
    即`0000001 << 7 = 128`，将其和上一步的`v`相加，即`v = 8 + 128 = 136`；取最高位为`0`，解码结束，
    得到`backlen=136`；

## listpack创建
`listpack`的创建实现如下：
```c
/* Create a new, empty listpack.
 * On success the new listpack is returned, otherwise an error is returned. */
unsigned char *lpNew(void) {
    // 加 1 表示 end 属性占一个字节
    unsigned char *lp = lp_malloc(LP_HDR_SIZE+1);
    if (lp == NULL) return NULL;
    // 初始化 total bytes 值， 4 个字节
    lpSetTotalBytes(lp,LP_HDR_SIZE+1);
    // 初始化 num elem 值，2 个字节
    lpSetNumElements(lp,0);
    // 设置 end 值，0xFF
    lp[LP_HDR_SIZE] = LP_EOF;
    return lp;
}
// total bytes + num elem
#define LP_HDR_SIZE 6       /* 32 bit total len + 16 bit number of elements. */
```
创建一个`listpack`会初始化一个字节数组，`6`字节`header`和`1`字节`end`，然后会初始化`total bytes`属性（`4`个字节），
和`num elem`属性（`2`个字节），相关实现如下：
```c
#define lpSetTotalBytes(p,v) do { \
    (p)[0] = (v)&0xff; \
    (p)[1] = ((v)>>8)&0xff; \
    (p)[2] = ((v)>>16)&0xff; \
    (p)[3] = ((v)>>24)&0xff; \
} while(0)

#define lpSetNumElements(p,v) do { \
    (p)[4] = (v)&0xff; \
    (p)[5] = ((v)>>8)&0xff; \
} while(0)
```
新的`listpack`创建后的数据结构如下：
```bash
  4 字节         2字节    1字节
+------------+----------+-----+
| total bytes| num elem | end |
+------------+----------+-----+
     7            0       255
```
## listpack插入
插入的`API`定义如下：
```c
unsigned char *lpInsert(unsigned char *lp, unsigned char *ele, uint32_t size, unsigned char *p, int where, unsigned char **newp);
```
+ `lp`：`listpack`对象的首地址；
+ `ele`：插入元素的地址，如果`ele=NULL`，会删除位置`p`处的元素；
+ `size`：插入元素的大小；
+ `p`：表示要插入的位置，`p`通过`lpFirst`、`lpLast()`、`lpIndex()`、`lpNext()`、`lpPrev()`或`lpSeek()`返回；
+ `where`：表示实际插入在位置`p`的哪里，取值如下：
  + `LP_BEFORE`：插入在`p`的前面；
  + `LP_AFTER`：插入在`p`的后面；
  + `LP_REPLACE`：替换位置`p`的元素；
+ `newp`：如果不为空，设置添加元素的地址，如果是删除操作，`newp`是删除元素下一个元素地址（右边一个），
如果删除元素是最后一个元素，`newp`设置为`NULL`；

**首先**会对插入元素进行编码，实现如下：
```c
    // LP_MAX_INT_ENCODING_LEN = 9，如果是整数，encode + content 最多占 9 个字节，
    // 其中 encode 是 1 字节，content 最多是 8 字节，
    // intenc 数组存放 encode + content 的值
    unsigned char intenc[LP_MAX_INT_ENCODING_LEN];
    // LP_MAX_BACKLEN_SIZE = 5，backlen 属性最多占 5 个字节
    // backlen 数组存放 backlen 的值
    unsigned char backlen[LP_MAX_BACKLEN_SIZE];
    // 表示 encode + content 占字节数
    uint64_t enclen; /* The length of the encoded element. */

    /* An element pointer set to NULL means deletion, which is conceptually
     * replacing the element with a zero-length element. So whatever we
     * get passed as 'where', set it to LP_REPLACE. */
    if (ele == NULL) where = LP_REPLACE;

    /* If we need to insert after the current element, we just jump to the
     * next element (that could be the EOF one) and handle the case of
     * inserting before. So the function will actually deal with just two
     * cases: LP_BEFORE and LP_REPLACE. */
    if (where == LP_AFTER) {
        // 找到下一个元素
        p = lpSkip(p);
        where = LP_BEFORE;
    }

    /* Store the offset of the element 'p', so that we can obtain its
     * address again after a reallocation. */
    unsigned long poff = p-lp;

    /* Calling lpEncodeGetType() results into the encoded version of the
     * element to be stored into 'intenc' in case it is representable as
     * an integer: in that case, the function returns LP_ENCODING_INT.
     * Otherwise if LP_ENCODING_STR is returned, we'll have to call
     * lpEncodeString() to actually write the encoded string on place later.
     *
     * Whatever the returned encoding is, 'enclen' is populated with the
     * length of the encoded element. */
    int enctype;
    if (ele) {
        enctype = lpEncodeGetType(ele,size,intenc,&enclen);
    } else {
        enctype = -1;
        enclen = 0;
    }

    /* We need to also encode the backward-parsable length of the element
     * and append it to the end: this allows to traverse the listpack from
     * the end to the start. */
    unsigned long backlen_size = ele ? lpEncodeBacklen(backlen,enclen) : 0;
    uint64_t old_listpack_bytes = lpGetTotalBytes(lp);
    uint32_t replaced_len  = 0;
    if (where == LP_REPLACE) {
        replaced_len = lpCurrentEncodedSize(p);
        replaced_len += lpEncodeBacklen(NULL,replaced_len);
    }

    uint64_t new_listpack_bytes = old_listpack_bytes + enclen + backlen_size
                                  - replaced_len;
    if (new_listpack_bytes > UINT32_MAX) return NULL;
```
如果参数`where=LP_AFTER`，表示在位置`p`的后面插入元素，实际会先找到`p`的下一个元素，
在下一个元素之前插入指定的元素，找到`p`下一个元素`lpSkip`实现如下：
```c
/* Skip the current entry returning the next. It is invalid to call this
 * function if the current element is the EOF element at the end of the
 * listpack, however, while this function is used to implement lpNext(),
 * it does not return NULL when the EOF element is encountered. */
unsigned char *lpSkip(unsigned char *p) {
    unsigned long entrylen = lpCurrentEncodedSize(p);
    entrylen += lpEncodeBacklen(NULL,entrylen);
    p += entrylen;
    return p;
}
```

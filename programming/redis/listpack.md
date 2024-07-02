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

**首先**会对插入元素进行编码（获取`encode + content + backlen`属性大小及值），实现如下：
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
    //  enctype 表示插入元素编码的类型，整数编码还是字符串编码
    int enctype;
    if (ele) {
        // 对插入元素进行编码，此函数下面有解释
        enctype = lpEncodeGetType(ele,size,intenc,&enclen);
    } else {
        enctype = -1;
        enclen = 0;
    }

    /* We need to also encode the backward-parsable length of the element
     * and append it to the end: this allows to traverse the listpack from
     * the end to the start. */
    // 如果是插入操作，获取 backlen 占字节大小，否则设置为 0
    unsigned long backlen_size = ele ? lpEncodeBacklen(backlen,enclen) : 0;
    // 读取 listpack 对象的前 4 个字节（lp[0]是低字节），获取旧的 listpack 对象的大小
    uint64_t old_listpack_bytes = lpGetTotalBytes(lp);
    uint32_t replaced_len  = 0;
    if (where == LP_REPLACE) {
        // 如果是替换操作，replaced_len 表示需要替换元素的大小（encode + content + backlen）占字节大小
        replaced_len = lpCurrentEncodedSize(p);
        replaced_len += lpEncodeBacklen(NULL,replaced_len);
    }
    // 获取元素更新后新的 listpack 的大小
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
    // entrylen 表示节点 p 的 encode + content 占用字节数
    unsigned long entrylen = lpCurrentEncodedSize(p);
    // 根据 entrylen 值，计算 backlen 占几个字节，并将其添加到 entrylen 上得到节点 p 占字节大小(encode + content + backlen)
    entrylen += lpEncodeBacklen(NULL,entrylen);
    // 指针往后移 entrylen 大小，得都下个节点首地址
    p += entrylen;
    return p;
}
```
如果是插入相关操作，会编码得到插入元素的`encode + content`值，存放在`intenc`数组（如果插入元素是整数的话），和`encode + content`占字节大小。
调用函数`lpEncodeGetType`实现如下：
```c
int lpEncodeGetType(unsigned char *ele, uint32_t size, unsigned char *intenc, uint64_t *enclen) {
    int64_t v;
    if (lpStringToInt64((const char*)ele, size, &v)) {
        if (v >= 0 && v <= 127) {
            /* Single byte 0-127 integer. */
            intenc[0] = v;
            *enclen = 1;
        } else if (v >= -4096 && v <= 4095) {
            /* 13 bit integer. */
            if (v < 0) v = ((int64_t)1<<13)+v;
            intenc[0] = (v>>8)|LP_ENCODING_13BIT_INT;
            intenc[1] = v&0xff;
            *enclen = 2;
        } else if (v >= -32768 && v <= 32767) {
            /* 16 bit integer. */
            if (v < 0) v = ((int64_t)1<<16)+v;
            intenc[0] = LP_ENCODING_16BIT_INT;
            intenc[1] = v&0xff;
            intenc[2] = v>>8;
            *enclen = 3;
        } else if (v >= -8388608 && v <= 8388607) {
            /* 24 bit integer. */
            if (v < 0) v = ((int64_t)1<<24)+v;
            intenc[0] = LP_ENCODING_24BIT_INT;
            intenc[1] = v&0xff;
            intenc[2] = (v>>8)&0xff;
            intenc[3] = v>>16;
            *enclen = 4;
        } else if (v >= -2147483648 && v <= 2147483647) {
            /* 32 bit integer. */
            if (v < 0) v = ((int64_t)1<<32)+v;
            intenc[0] = LP_ENCODING_32BIT_INT;
            intenc[1] = v&0xff;
            intenc[2] = (v>>8)&0xff;
            intenc[3] = (v>>16)&0xff;
            intenc[4] = v>>24;
            *enclen = 5;
        } else {
            /* 64 bit integer. */
            uint64_t uv = v;
            intenc[0] = LP_ENCODING_64BIT_INT;
            intenc[1] = uv&0xff;
            intenc[2] = (uv>>8)&0xff;
            intenc[3] = (uv>>16)&0xff;
            intenc[4] = (uv>>24)&0xff;
            intenc[5] = (uv>>32)&0xff;
            intenc[6] = (uv>>40)&0xff;
            intenc[7] = (uv>>48)&0xff;
            intenc[8] = uv>>56;
            *enclen = 9;
        }
        return LP_ENCODING_INT;
    } else {
        if (size < 64) *enclen = 1+size;
        else if (size < 4096) *enclen = 2+size;
        else *enclen = 5+size;
        return LP_ENCODING_STRING;
    }
}
```
函数`lpEncodeGetType`的入参如下：
+ `ele`：插入的元素首地址；
+ `size`：插入元素大小；
+ `intenc`：如果插入元素可以编码为整数，则`intenc`数组存储编码后`encode + content`的值；
+ `enclen`：编码后`encode + content`占字节的大小；

对于整数编码，如果是负数，则会将其转为正数存储，例如对于`13`位表示的整数：
```c
/* 13 bit integer. */
if (v < 0) v = ((int64_t)1<<13)+v;
```
如果是字符串编码，只计算`encode + content`占字节大小`enclen`值。函数`lpEncodeGetType`返回值有如下：
+ `LP_ENCODING_INT`：插入元素是整数，整数编码；
+ `LP_ENCODING_STRING`：插入元素是字符串，字符串编码

**最后**需要分配新的空间大小，并拷贝内存，实现如下：
```c
    /* We now need to reallocate in order to make space or shrink the
     * allocation (in case 'when' value is LP_REPLACE and the new element is
     * smaller). However we do that before memmoving the memory to
     * make room for the new element if the final allocation will get
     * larger, or we do it after if the final allocation will get smaller. */

    unsigned char *dst = lp + poff; /* May be updated after reallocation. */

    /* Realloc before: we need more room. */
    if (new_listpack_bytes > old_listpack_bytes) {
        // 扩容操作，例如插入新元素
        if ((lp = lp_realloc(lp,new_listpack_bytes)) == NULL) return NULL;
        dst = lp + poff;
    }

    /* Setup the listpack relocating the elements to make the exact room
     * we need to store the new one. */
    if (where == LP_BEFORE) {
        // 将插入位置 dst 往后的元素向后移动新元素大小距离
        memmove(dst+enclen+backlen_size,dst,old_listpack_bytes-poff);
    } else { /* LP_REPLACE. */
        long lendiff = (enclen+backlen_size)-replaced_len;
        // 替换操作，将替换元素之后的元素往前移动替换元素大小的位置
        memmove(dst+replaced_len+lendiff,
                dst+replaced_len,
                old_listpack_bytes-poff-replaced_len);
    }

    /* Realloc after: we need to free space. */
    if (new_listpack_bytes < old_listpack_bytes) {
        // 替换元素，需要缩容
        if ((lp = lp_realloc(lp,new_listpack_bytes)) == NULL) return NULL;
        dst = lp + poff;
    }

    /* Store the entry. */
    if (newp) {
        // 更新 newp 值，newp 是返回值。插入操作，newp 表示插入的元素，删除操作表示删除位置的下一个元素（右边），
        // 如果删除元素的下一个元素是 end，newp 设置 NULL
        *newp = dst;
        /* In case of deletion, set 'newp' to NULL if the next element is
         * the EOF element. */
        if (!ele && dst[0] == LP_EOF) *newp = NULL;
    }
    if (ele) {
        // 插入操作，将元素放在 listpack 对象指定位置
        if (enctype == LP_ENCODING_INT) {
            memcpy(dst,intenc,enclen);
        } else {
            lpEncodeString(dst,ele,size);
        }
        dst += enclen;
        // 更新 backlen 值
        memcpy(dst,backlen,backlen_size);
        dst += backlen_size;
    }

    /* Update header. */
    // 插入操作，更新 listpack 对象的 num elem 值
    if (where != LP_REPLACE || ele == NULL) {
        uint32_t num_elements = lpGetNumElements(lp);
        if (num_elements != LP_HDR_NUMELE_UNKNOWN) {
            if (ele)
                lpSetNumElements(lp,num_elements+1);
            else
                lpSetNumElements(lp,num_elements-1);
        }
    }
    // 更新 listpack 对象新的字节大小
    lpSetTotalBytes(lp,new_listpack_bytes);
    return lp;
```
内存拷贝有两种情况，如果是插入操作，内存操作示例如下：
```bash
+------------+----------+----------+--------+----------+-----+
| total bytes| num elem | entryP-1 | entryP | entryP+1 | end |
+------------+----------+----------+--------+----------+-----+
                                         \
                                          \
+------------+----------+----------+-----+--------+----------+-----+
| total bytes| num elem | entryP-1 | new | entryP | entryP+1 | end |
+------------+----------+----------+-----+--------+----------+-----+
```
如果是替换操作：
```bash
+------------+----------+----------+--------+----------+-----+
| total bytes| num elem | entryP-1 | entryP | entryP+1 | end |
+------------+----------+----------+--------+----------+-----+
                                              /                  
                               +-------------+
                              /
+------------+----------+----------+----------+-----+
| total bytes| num elem | entryP-1 | entryP+1 | end |
+------------+----------+----------+----------+-----+
```

## listpack删除
删除操作实现如下：
```c
/* Remove the element pointed by 'p', and return the resulting listpack.
 * If 'newp' is not NULL, the next element pointer (to the right of the
 * deleted one) is returned by reference. If the deleted element was the
 * last one, '*newp' is set to NULL. */
unsigned char *lpDelete(unsigned char *lp, unsigned char *p, unsigned char **newp) {
    return lpInsert(lp,NULL,0,p,LP_REPLACE,newp);
}
```
删除操作逻辑具体在`lpInsert`里面实现，参考上面介绍。

## listpack查找
`redis`提供了`lpNext`、`lpPrev`、`lpFirst`、`lpLast`和`lpSeek`方法用于`listpack`对象的检索。下面介绍`lpNext`和`lpPrev`实现。
`lpNext`实现如下：
```c
/* If 'p' points to an element of the listpack, calling lpNext() will return
 * the pointer to the next element (the one on the right), or NULL if 'p'
 * already pointed to the last element of the listpack. */
unsigned char *lpNext(unsigned char *lp, unsigned char *p) {
    ((void) lp); /* lp is not used for now. However lpPrev() uses it. */
    p = lpSkip(p);
    if (p[0] == LP_EOF) return NULL;
    return p;
}
```
`lpNext`返回指定位置`p`的下一个元素。内部调用`lpSkip`实现，查看插入小节介绍。

`lpPrev`的实现如下：
```c
/* If 'p' points to an element of the listpack, calling lpPrev() will return
 * the pointer to the preivous element (the one on the left), or NULL if 'p'
 * already pointed to the first element of the listpack. */
unsigned char *lpPrev(unsigned char *lp, unsigned char *p) {
    // 如果 p 是第一个元素，返回 NULL
    if (p-lp == LP_HDR_SIZE) return NULL;
    p--; /* Seek the first backlen byte of the last element. */
    uint64_t prevlen = lpDecodeBacklen(p);
    prevlen += lpEncodeBacklen(NULL,prevlen);
    return p-prevlen+1; /* Seek the first byte of the previous entry. */
}
```
`lpPrev`返回指定位置`p`的前一个元素。解码`backlen`的值实现如下（解码从右往左）：
```c
/* Decode the backlen and returns it. If the encoding looks invalid (more than
 * 5 bytes are used), UINT64_MAX is returned to report the problem. */
uint64_t lpDecodeBacklen(unsigned char *p) {
    uint64_t val = 0;
    uint64_t shift = 0;
    do {
        // 取每个字节的低 7 为
        val |= (uint64_t)(p[0] & 127) << shift;
        // 每个字节的最高位是否为 0，为 0 表示 backlen 值结束
        if (!(p[0] & 128)) break;
        // 每个字节只有低 7 为有效，每次左移 7 位
        shift += 7;
        p--;
        if (shift > 28) return UINT64_MAX;
    } while(1);
    return val;
}
```
`backlen`用于`listpack`对象从后往前遍历。

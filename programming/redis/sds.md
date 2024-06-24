> 基于`resis`源码分支`5.0`
# 动态字符串SDS
`redis`实现了自定义的字符串类型，和传统的`c`字符串相比，具有如下特点：
+ 常数时间复杂度获取字符串的长度；
+ 避免操作字符串时缓冲区益处；
+ 减少修改字符串带来的内存分配次数；
+ 二进制安全；
+ 兼容部分`c`字符串函数；

## SDS定义
`redis`在`sds.h`文件中定义了不同大小的字符串数据类型：
```c
/* Note: sdshdr5 is never used, we just access the flags byte directly.
 * However is here to document the layout of type 5 SDS strings. */
struct __attribute__ ((__packed__)) sdshdr5 {
    unsigned char flags; /* 3 lsb of type, and 5 msb of string length */
    char buf[];
};
struct __attribute__ ((__packed__)) sdshdr8 {
    uint8_t len; /* used */
    uint8_t alloc; /* excluding the header and null terminator */
    unsigned char flags; /* 3 lsb of type, 5 unused bits */
    char buf[];
};
struct __attribute__ ((__packed__)) sdshdr16 {
    uint16_t len; /* used */
    uint16_t alloc; /* excluding the header and null terminator */
    unsigned char flags; /* 3 lsb of type, 5 unused bits */
    char buf[];
};
struct __attribute__ ((__packed__)) sdshdr32 {
    uint32_t len; /* used */
    uint32_t alloc; /* excluding the header and null terminator */
    unsigned char flags; /* 3 lsb of type, 5 unused bits */
    char buf[];
};
struct __attribute__ ((__packed__)) sdshdr64 {
    uint64_t len; /* used */
    uint64_t alloc; /* excluding the header and null terminator */
    unsigned char flags; /* 3 lsb of type, 5 unused bits */
    char buf[];
};
// 宏定义
#define SDS_TYPE_5  0
#define SDS_TYPE_8  1
#define SDS_TYPE_16 2
#define SDS_TYPE_32 3
#define SDS_TYPE_64 4
#define SDS_TYPE_MASK 7
#define SDS_TYPE_BITS 3
#define SDS_HDR_VAR(T,s) struct sdshdr##T *sh = (void*)((s)-(sizeof(struct sdshdr##T)));
#define SDS_HDR(T,s) ((struct sdshdr##T *)((s)-(sizeof(struct sdshdr##T))))
#define SDS_TYPE_5_LEN(f) ((f)>>SDS_TYPE_BITS)
```
其中各个字段的含义如下：
+ `len`：字符串的长度，不包括`\0`字符；
+ `alloc`：表示`buf`已经分配的字节数（包括空闲空间），也就是`size(buf)-1`，`-1`表示留一个字节给`\0`；
+ `flags`：一个字节，低 3 位表示数据结构的类型，表示上述定义的`sdshdrxx`；
+ `buf`：存放以`\0`结尾的字符串；

定义结构体中有`__attribute__ ((__packed__))`关键字，目的是告诉编译器不使用内存对齐，以紧凑模式分配内存。

`sds`数据类型内存布局样例如下，其中`buf`存储的是`hello`字符串：
```bash
          headers                    buf
           ^                          ^
+----------+----------+---------------+--------------+
|                     |                              |
+-----+-------+-------+---+---+---+---+---+----+-----+
| len | alloc | flags | h | e | l | l | o | \0 | ... |
+-----+-------+-------+---+---+---+---+---+----+-----+
```
## 查询字符串的大小
通过直接返回`len`属性值以获取字符串的长度，时间复杂度为`O(1)`：
```c
static inline size_t sdslen(const sds s) {
    unsigned char flags = s[-1];
    switch(flags&SDS_TYPE_MASK) {
        case SDS_TYPE_5:
            return SDS_TYPE_5_LEN(flags);
        case SDS_TYPE_8:
            return SDS_HDR(8,s)->len;
        case SDS_TYPE_16:
            return SDS_HDR(16,s)->len;
        case SDS_TYPE_32:
            return SDS_HDR(32,s)->len;
        case SDS_TYPE_64:
            return SDS_HDR(64,s)->len;
    }
    return 0;
}
```
其中参数`const sds s`表示`buf`属性的首地址，`s[-1]`表示地址往前移动一位对应的值，也即表示`flags`属性值。
## 减少修改字符串带来的内存分配次数
每次更新字符串前都会判断是否需要拓展空间或者释放多余的空间。`redis`拓展`sds`字符串空间的实现如下：
```c
/* Enlarge the free space at the end of the sds string so that the caller
 * is sure that after calling this function can overwrite up to addlen
 * bytes after the end of the string, plus one more byte for nul term.
 *
 * Note: this does not change the *length* of the sds string as returned
 * by sdslen(), but only the free buffer space we have. */
sds sdsMakeRoomFor(sds s, size_t addlen) {
    void *sh, *newsh;
    // 获取当前 s 剩余可用空间大小 (alloc - len = avail)
    size_t avail = sdsavail(s);
    size_t len, newlen;
    // s[-1] 表示 s 的 flags 属性值
    char type, oldtype = s[-1] & SDS_TYPE_MASK;
    int hdrlen;

    /* Return ASAP if there is enough space left. */
    // 可用空间够，直接返回
    if (avail >= addlen) return s;

    len = sdslen(s);
    // 指针（buf 属性首地址）前移 s数据类型的 headers 大小，也即 sh 表示 sdshdrxx s 的首地址，也就是 len 属性地址
    sh = (char*)s-sdsHdrSize(oldtype);
    // 新的字符串的最小长度
    newlen = (len+addlen);
    // SDS_MAX_PREALLOC = 1024*1024
    if (newlen < SDS_MAX_PREALLOC)
        newlen *= 2;
    else
        newlen += SDS_MAX_PREALLOC;
    // 新的字符串长度对应的数据类型（8位，16位等）
    type = sdsReqType(newlen);

    /* Don't use type 5: the user is appending to the string and type 5 is
     * not able to remember empty space, so sdsMakeRoomFor() must be called
     * at every appending operation. */
    if (type == SDS_TYPE_5) type = SDS_TYPE_8;
    // 存储新的字符串对应的数据类型 header 大小    
    hdrlen = sdsHdrSize(type);
    if (oldtype==type) {
        // 存储新的字符串数据类型没有变化
        // 调用 realloc 内存分配
        newsh = s_realloc(sh, hdrlen+newlen+1);
        if (newsh == NULL) return NULL;
        s = (char*)newsh+hdrlen;
    } else {
        /* Since the header size changes, need to move the string forward,
         * and can't use realloc */
        newsh = s_malloc(hdrlen+newlen+1);
        if (newsh == NULL) return NULL;
        // 将原来的字符串拷贝到新分配的内存地址
        memcpy((char*)newsh+hdrlen, s, len+1);
        // 释放原来的内存
        s_free(sh);
        // s 指向新 buf 属性地址
        s = (char*)newsh+hdrlen;
        // 更新 flags 属性
        s[-1] = type;
        // 更新 len 属性值
        sdssetlen(s, len);
    }
    // 更新 alloc 属性值
    sdssetalloc(s, newlen);
    return s;
}
```

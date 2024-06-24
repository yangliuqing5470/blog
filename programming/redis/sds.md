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
每次更新字符串前都会判断是否需要拓展空间。`redis`拓展`sds`字符串空间的实现如下：
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
`sdsMakeRoomFor`实现了空间预分配，用以减少连续执行字符串增长操作需要的内存分配次数。
`sdsMakeRoomFor`做的具体工作如下：
+ 检查当前空闲空间大小是否满足扩容需求，如果满足直接返回，否则执行下一步；
+ 计算新的`SDS`需要的长度（即`len`属性值），如果`newlen < 1MB`，则实际分配`2*newlen`大小空间。
例如，如果计算`newlen=100B`，则实际分配`200B`大小的`buf`；如果`newlen >= 1MB`，则实际分配`newlen+1MB`大小空间。
例如，如果`newlen=2MB`，则实际分配`3MB`大小的`buf`；
+ 如果新的`SDS`实例和老的`SDS`实例是同一个数据类型，例如都是`sdshdr32`类型，则调用`realloc`分配内存，
否则调用`malloc`分配内存。最后初始化新的`SDS`实例数据，并释放旧的内存（需要的话）；

惰性空间释放用于优化`SDS`字符串缩短操作，例如函数`sdstrim`接收一个`SDS`和一个`c`字符串两个参数，
从`SDS`左右两边分别移除所有在`c`字符串中出现的字符。实际不会释放多余的内存，只是修改`SDS`的`len`属性值，
这些没有释放的内存用于将来`SDS`增长操作。`sdstrim`源码如下：
```c
/* Remove the part of the string from left and from right composed just of
 * contiguous characters found in 'cset', that is a null terminted C string.
 *
 * After the call, the modified sds string is no longer valid and all the
 * references must be substituted with the new pointer returned by the call.
 *
 * Example:
 *
 * s = sdsnew("AA...AA.a.aa.aHelloWorld     :::");
 * s = sdstrim(s,"Aa. :");
 * printf("%s\n", s);
 *
 * Output will be just "Hello World".
 */
sds sdstrim(sds s, const char *cset) {
    char *start, *end, *sp, *ep;
    size_t len;

    sp = start = s;
    ep = end = s+sdslen(s)-1;
    // strchr 查找字符在字符串的位置，没有则返回 null
    // 从左边开始查找
    while(sp <= end && strchr(cset, *sp)) sp++;
    // 从右边开始查找
    while(ep > sp && strchr(cset, *ep)) ep--;
    // 新的 SDS 长度
    len = (sp > ep) ? 0 : ((ep-sp)+1);
    // void *memmove(void *__dest, const void *__src, size_t __n)
    // Copy N bytes of SRC to DEST, guaranteeing
    // correct behavior for overlapping strings.
    if (s != sp) memmove(s, sp, len);
    // 惰性删除，只更改 len 属性值
    s[len] = '\0';
    sdssetlen(s,len);
    return s;
}
```
如果需要释放未使用空间内存，`SDS`提供了如下函数调用：
```c
/* Reallocate the sds string so that it has no free space at the end. The
 * contained string remains not altered, but next concatenation operations
 * will require a reallocation.
 *
 * After the call, the passed sds string is no longer valid and all the
 * references must be substituted with the new pointer returned by the call. */
sds sdsRemoveFreeSpace(sds s) {
    void *sh, *newsh;
    char type, oldtype = s[-1] & SDS_TYPE_MASK;
    int hdrlen, oldhdrlen = sdsHdrSize(oldtype);
    size_t len = sdslen(s);
    // 指针前移，sh 表示 SDS 的首地址
    sh = (char*)s-oldhdrlen;

    /* Check what would be the minimum SDS header that is just good enough to
     * fit this string. */
    type = sdsReqType(len);
    hdrlen = sdsHdrSize(type);

    /* If the type is the same, or at least a large enough type is still
     * required, we just realloc(), letting the allocator to do the copy
     * only if really needed. Otherwise if the change is huge, we manually
     * reallocate the string to use the different header type. */
    if (oldtype==type || type > SDS_TYPE_8) {
        newsh = s_realloc(sh, oldhdrlen+len+1);
        if (newsh == NULL) return NULL;
        s = (char*)newsh+oldhdrlen;
    } else {
        newsh = s_malloc(hdrlen+len+1);
        if (newsh == NULL) return NULL;
        memcpy((char*)newsh+hdrlen, s, len+1);
        s_free(sh);
        s = (char*)newsh+hdrlen;
        s[-1] = type;
        sdssetlen(s, len);
    }
    sdssetalloc(s, len);
    return s;
}
```
`sdsRemoveFreeSpace`内部内存释放有如下优化策略：
+ 如果目标`SDS`数据类型和老的`SDS`数据类型（未释放内存前）一样（例如都是`SDS_TYPE_16`），
或者目标`SDS`数据类型比较大（超过`SDS_TYPE_8`），则调用`realloc`；
+ 如果目标`SDS`数据类型比较小（小于等于`SDS_TYPE_8`），则直接调用`malloc`分配新的内存，
将字符串拷贝到新内存，释放旧内存；

## 避免修改字符串带来缓冲区溢出
`SDS`的 API 需要修改`SDS`时，对应的 API 会先检查`SDS`空闲空间是否满足修改需求，
如果不满足，则会调用`sdsMakeRoomFor`进行空间预分配，然后才会进行实际的`SDS`修改操作。
例如拼接两个字符串`sdscat`实现源码如下：
```c
/* Append the specified binary-safe string pointed by 't' of 'len' bytes to the
 * end of the specified sds string 's'.
 *
 * After the call, the passed sds string is no longer valid and all the
 * references must be substituted with the new pointer returned by the call. */
sds sdscatlen(sds s, const void *t, size_t len) {
    size_t curlen = sdslen(s);
    // 空间预分配
    s = sdsMakeRoomFor(s,len);
    if (s == NULL) return NULL;
    // 执行字符串拼接操作
    memcpy(s+curlen, t, len);
    sdssetlen(s, curlen+len);
    s[curlen+len] = '\0';
    return s;
}

/* Append the specified null termianted C string to the sds string 's'.
 *
 * After the call, the passed sds string is no longer valid and all the
 * references must be substituted with the new pointer returned by the call. */
sds sdscat(sds s, const char *t) {
    return sdscatlen(s, t, strlen(t));
}
```
## 二进制安全
`c`字符串由于没有字符长度属性，只能通过`\0`表示字符串结束，所以`c`字符串中不能有`\0`字符，
否则会被误认为字符串结尾。由于这些限制，`c`字符串不能保存图片，音频等二进制数据，
只能保存字符串数据。

`SDS`字符串由于有`len`属性记录字符串长度，所以`SDS`字符串是二进制安全的，
可以用来保存任意二进制数据。

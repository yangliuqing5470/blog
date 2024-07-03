> 基于`redis`源码分支`5.0`

# Rax树
`rax`树，即基数树，是前缀树（字典树）的一种。例如一个包含`foo`、`foobar`和`footer`的字典树如下：
```bash
              (f) ""
                \
                (o) "f"
                  \
                  (o) "fo"
                    \
                  [t   b] "foo"
                  /     \
         "foot" (e)     (a) "foob"
                /         \
      "foote" (r)         (r) "fooba"
              /             \
    "footer" []             [] "foobar"
```
+ 其中`[]`形式表示一个`key`；
+ 旁边标注的的字符串表示当前节点的前缀字符串；

上面的字典树表示最大的问题就是空间占用高，每个节点只存储一个字符。所以可以做一种优化就是将只有一个子节点的连续节点压缩到一个节点存储，
这个压缩后的节点存储的不是单个字符，而是字符串，这就是`rax`树，结构如下：
```bash
                  ["foo"] ""
                     |
                  [t   b] "foo"
                  /     \
        "foot" ("er")    ("ar") "foob"
                 /          \
       "footer" []          [] "foobar"
```
+ 其中`[]`形式表示一个`key`；
+ 旁边标注的的字符串表示当前节点的前缀字符串；

`rax`树的实现会变的更加复杂，插入和删除会涉及节点的分裂与合并。例如上面的`rax`树，如果插入一个新的`key=first`，会导致节点分裂，
插入`first`后的结构如下：
```bash
                    (f) ""
                    /
                 (i o) "f"
                 /   \
    "firs"  ("rst")  (o) "fo"
              /        \
    "first" []       [t   b] "foo"
                     /     \
           "foot" ("er")    ("ar") "foob"
                    /          \
          "footer" []          [] "foobar"
```
+ 其中`[]`形式表示一个`key`；
+ 旁边标注的的字符串表示当前节点的前缀字符串；

## rax树数据结构
在`redis`中，`rax`树的节点定义如下：
```c
typedef struct raxNode {
    uint32_t iskey:1;     /* Does this node contain a key? */
    uint32_t isnull:1;    /* Associated value is NULL (don't store it). */
    uint32_t iscompr:1;   /* Node is compressed. */
    uint32_t size:29;     /* Number of children, or compressed string len. */
    unsigned char data[];
} raxNode;
```
+ `iskey`：表示从根节点到当前节点的父节点路径包含的字符串是否是一个`key`，取值`1`表示是，`0`表示不是。当前节点表示的`key`不包含当前节点的内容。
+ `isnull`：表示当前节点表示的`key`对应的`value`是否为空，也就是有没有`value`值。如果取值`1`，表示没有`value`值，
也就在`data`中没有指向`value`的指针；
+ `iscompr`：表示当前节点是压缩节点还是非压缩节点；
+ `size`：如果是压缩节点，表示压缩字符串长度；如果是非压缩节点，表示子节点个数（每个字符都有一个子节点）；
+ `data`：用于保存节点的实际数据（前面的`iskey`、`isnull`、`iscompr`和`size`表示节点的`header`，分别占用`1`位，`1`位，`1`位和`29`位）；
  + 如果节点是非压缩节点（`iscompr=0`），节点的数据结构如下：
    ```bash
    |---> header <---|--------------> data <---------------|
    [header iscompr=0][abc][a-ptr][b-ptr][c-ptr](value-ptr?)
    ```
    `data`中有`3`个字符`abc`，紧跟着是`3`个指针，分别指向对应的子节点。如果`iskey=1 & isnull=0`，紧跟着是`value`指针，否则没有`value`指针。
  + 如果节点是压缩节点（`iscompr=1`），节点的数据结构如下：
    ```bash
    |---> header <---|-------> data <--------|
    [header iscompr=1][xyz][z-ptr](value-ptr?)
    ```
    `data`中存储的压缩字符串`abc`长度是`3`，后面紧跟着一个指针指向下一个子几点。如果`iskey=1 & isnull=0`，紧跟着是`value`指针，否则没有`value`指针。

在`redis`中，`rax`树的定义如下：
```c
typedef struct rax {
    raxNode *head;
    uint64_t numele;
    uint64_t numnodes;
} rax;
```
+ `head`：指向头节点（根节点）的指针，头节点不是空节点，和正常节点一样会存储数据；
+ `numele`：表示元素的个数（`key`的数量）；
+ `numnodes`：表示节点的数量；

`redis`提供了`raxStack`和`raxIterator`两种数据结构用于`rax`树的遍历操作。`raxStack`的结构定义如下：
```c
/* Stack data structure used by raxLowWalk() in order to, optionally, return
 * a list of parent nodes to the caller. The nodes do not have a "parent"
 * field for space concerns, so we use the auxiliary stack when needed. */
#define RAX_STACK_STATIC_ITEMS 32
typedef struct raxStack {
    void **stack; /* Points to static_items or an heap allocated array. */
    size_t items, maxitems; /* Number of items contained and total space. */
    /* Up to RAXSTACK_STACK_ITEMS items we avoid to allocate on the heap
     * and use this static array of pointers instead. */
    void *static_items[RAX_STACK_STATIC_ITEMS];
    int oom; /* True if pushing into this stack failed for OOM at some point. */
} raxStack;
```
`raxStack`用于存储从根节点到当前节点的路径（存放的是指针）。
+ `stack`：指向`static_items`的指针（路径短的时候），或者指向堆空间分配的内存数组地址；
+ `items`：栈中存储的元素个数；
+ `maxitems`：栈可存储元素个数的最大值；
+ `static_items`：指针数组，存放`raxNode`节点的指针；
+ `oom`：取值`1`表示内存分配失败，遇到`OOM`，默认`0`；

`raxIterator`用于遍历`rax`树中所有的`key`，数据结构定义如下：
```c
typedef int (*raxNodeCallback)(raxNode **noderef);
#define RAX_ITER_STATIC_LEN 128

typedef struct raxIterator {
    int flags;
    rax *rt;                /* Radix tree we are iterating. */
    unsigned char *key;     /* The current string. */
    void *data;             /* Data associated to this key. */
    size_t key_len;         /* Current key length. */
    size_t key_max;         /* Max key len the current key buffer can hold. */
    unsigned char key_static_string[RAX_ITER_STATIC_LEN];
    raxNode *node;          /* Current node. Only for unsafe iteration. */
    raxStack stack;         /* Stack used for unsafe iteration. */
    raxNodeCallback node_cb; /* Optional node callback. Normally set to NULL. */
} raxIterator;
```
+ `flags`：迭代器的标志位，取值有如下三种：
  + `RAX_ITER_JUST_SEEKED`：
  + `RAX_ITER_EOF`：
  + `RAX_ITER_SAFE`：
+ `rt`：指向`rax`对象的指针；
+ `key`：指向当前`key`的字符串数组，小字符串指向`key_static_string`，大字符串指向堆空间分配的字符串数组地址；
+ `data`：当前`key`对应的`value`值；
+ `key_len`：当前`key`的长度；
+ `key_max`：存放当前`key`缓存的最大值；
+ `key_static_string`：字符串数组，存放当前`key`；
+ `node`：当前`key`所在的`raxNode`节点；
+ `stack`：记录从根节点到当前节点路径，用于节点向上遍历；
+ `node_cb`：节点回调函数，默认为`NULL`；

## rax树创建
`rax`树创建实现如下：
```c
/* Allocate a new rax and return its pointer. On out of memory the function
 * returns NULL. */
rax *raxNew(void) {
    rax *rax = rax_malloc(sizeof(*rax));
    if (rax == NULL) return NULL;
    // 初始化元素个数（key 的个数）为 0
    rax->numele = 0;
    // 初始化 rax 树节点个数为 1，因为包含一个 head 节点
    rax->numnodes = 1;
    // 初始化 head 节点
    rax->head = raxNewNode(0,0);
    if (rax->head == NULL) {
        rax_free(rax);
        return NULL;
    } else {
        return rax;
    }
}
```
创建`raxNode`节点函数`raxNewNode`实现如下：
```c
/* Allocate a new non compressed node with the specified number of children.
 * If datafiled is true, the allocation is made large enough to hold the
 * associated data pointer.
 * Returns the new node pointer. On out of memory NULL is returned. */
raxNode *raxNewNode(size_t children, int datafield) {
    // 计算一个 raxNode 节点大小 header + data，将节点按非压缩节点处理
    size_t nodesize = sizeof(raxNode)+children+raxPadding(children)+
                      sizeof(raxNode*)*children;
    // 如果有数据，也就key是对应的 value，加上指向 value 指针的大小
    if (datafield) nodesize += sizeof(void*);
    raxNode *node = rax_malloc(nodesize);
    if (node == NULL) return NULL;
    node->iskey = 0;
    node->isnull = 0;
    // 初始按非压缩节点
    node->iscompr = 0;
    node->size = children;
    return node;
}
```
参数含义解释如下：
+ `children`：当前节点子节点个数；
+ `datafield`：当前节点是否有对应的`value`，取值`0`表示没有，取值非`0`表示有；

新创建后`rax`数据结构如下：
```bash               
                      |-------------> head <----------------|
+-------------+       +--------+---------+----------+-------+----+
|     head    |  ---> |iskey: 0|isnull: 0|iscompr: 0|size: 0|data|
+-------------+       +--------+---------+----------+-------+----+
| numele: 0   |       
+-------------+       
| numnodes: 1 |       
+-------------+       
```
## rax树节点添加子节点
`raxNode`有压缩节点和非压缩节点，先看非压缩节点添加子节点`raxAddChild`函数实现。
`raxAddChild`函数定义如下：
```c
raxNode *raxAddChild(raxNode *n, unsigned char c, raxNode **childptr, raxNode ***parentlink)
```
+ `n`：表示要添加子节点的节点；
+ `c`：节点`n`要添加的字符，因为是非压缩节点，所以是一个字符；
+ `childptr`：指向插入新的子节点地址的指针；
+ `parentlink`：指向节点`n`中指向新节点地址的指针；

`raxAddChild`操作主要有如下几步：
+ 节点空间分配；
  ```c
    assert(n->iscompr == 0);
    // 获取节点 n 更新前的大小，header + data 的大小
    size_t curlen = raxNodeCurrentLength(n);
    // 因为添加一个字符，节点 size 值加 1
    n->size++;
    // 获取节点 你更新后的大小，header + data 的大小
    // 添加一个字符，也会添加一个子节点指针 + 填充字节大小（内存对齐）
    size_t newlen = raxNodeCurrentLength(n);
    n->size--; /* For now restore the orignal size. We'll update it only on
                  success at the end. */

    /* Alloc the new child we will link to 'n'. */
    // 分配一个空的子节点（data 属性没有数据）
    raxNode *child = raxNewNode(0,0);
    if (child == NULL) return NULL;

    /* Make space in the original node. */
    // 从新给节点分配空间
    raxNode *newn = rax_realloc(n,newlen);
    if (newn == NULL) {
        rax_free(child);
        return NULL;
    }
    n = newn;
  ```
  重新分配空间后，会增加一个字节存储字符`c`，填充字节用于内存对齐，一个指针指向新的子节点：
  ```bash
  // 分配前节点存储 abde 4个字符
  [HDR*][abde][Aptr][Bptr][Dptr][Eptr]|AUXP|
  // 分配后的空间
  [HDR*][abde][Aptr][Bptr][Dptr][Eptr]|AUXP|[....][....]
  ```
+ 查找字符`c`要在节点`n`中添加的位置；
  ```c
    int pos;
    for (pos = 0; pos < n->size; pos++) {
        if (n->data[pos] > c) break;
    }
  ```
  节点中存储的字符保持字典序。
+ 将指向`value`的指针移动到新分配空间的末尾；
  ```c
    unsigned char *src, *dst;
    // 确保当前的节点 n 有指向 value 的指针
    if (n->iskey && !n->isnull) {
        src = ((unsigned char*)n+curlen-sizeof(void*));
        dst = ((unsigned char*)n+newlen-sizeof(void*));
        memmove(dst,src,sizeof(void*));
    }
  ```
  移动后数据结构如下：
  ```bash
  [HDR*][abde][Aptr][Bptr][Dptr][Eptr][....][....]|AUXP|
  ```
+ 移动插入位置后的指向子节点指针，给要添加新的指向子节点指针留出空间；
  ```c
  size_t shift = newlen - curlen - sizeof(void*);
  src = n->data+n->size+
        raxPadding(n->size)+
        sizeof(raxNode*)*pos;
  memmove(src+shift+sizeof(raxNode*),src,sizeof(raxNode*)*(n->size-pos));
  ```
  移动后的数据结构如下：
  ```bash
  [HDR*][abde][Aptr][Bptr][....][....][Dptr][Eptr]|AUXP|
  ```
+ 移动插入位置前的指向子节点指针，给要添加字符及填充字节留出空间；
  ```c
    if (shift) {
        src = (unsigned char*) raxNodeFirstChildPtr(n);
        memmove(src+shift,src,sizeof(raxNode*)*pos);
    }
  ```
  移动后的数据结构如下：
  ```bash
  [HDR*][abde][....][Aptr][Bptr][....][Dptr][Eptr]|AUXP|
  ```
+ 移动插入位置后的字符，给要添加的字符留出空间；
  ```c
  src = n->data+pos;
  memmove(src+1,src,n->size-pos);
  ```
  移动后的数据结构如下：
  ```bash
  [HDR*][ab.d][e...][Aptr][Bptr][....][Dptr][Eptr]|AUXP|
  ```
+ 最后将添加的字符`c`及指向新的子节点指针添加到指定位置；
  ```c
  n->data[pos] = c;
  n->size++;
  src = (unsigned char*) raxNodeFirstChildPtr(n);
  // 指向新节点地址指针的指针
  raxNode **childfield = (raxNode**)(src+sizeof(raxNode*)*pos);
  memcpy(childfield,&child,sizeof(child));
  *childptr = child;
  *parentlink = childfield;
  return n;
  ```
  最终的数据结构如下：
  ```bash
  [HDR*][abcd][e...][Aptr][Bptr][....][Dptr][Eptr]|AUXP|
  [HDR*][abcd][e...][Aptr][Bptr][Cptr][Dptr][Eptr]|AUXP|
  ```
接下来看将空的非压缩节点转为压缩节点`raxCompressNode`函数实现。`raxCompressNode`函数定义如下：
```c
raxNode *raxCompressNode(raxNode *n, unsigned char *s, size_t len, raxNode **child);
```
+ `n`：待转换的节点，必须是空的非压缩节点，也就是没有任何子节点的非压缩节点；
+ `s`：添加的字符串；
+ `len`：添加字符串的长度；
+ `child`：指向存放子节点地址的指针；

`raxCompressNode`的实现主要有如下几步：
+ 节点空间分配；
  ```c
    // 确保是空的非压缩节点
    assert(n->size == 0 && n->iscompr == 0);
    void *data = NULL; /* Initialized only to avoid warnings. */
    size_t newsize;

    debugf("Compress node: %.*s\n", (int)len,s);

    /* Allocate the child to link to this node. */
    // 初始化一个空的非压缩子节点
    *child = raxNewNode(0,0);
    if (*child == NULL) return NULL;

    /* Make space in the parent node. */
    // header大小 + 添加字符串大小 + 填充字节大小 + 指向子节点指针
    newsize = sizeof(raxNode)+len+raxPadding(len)+sizeof(raxNode*);
    if (n->iskey) {
        // data 是 value 数据的地址
        data = raxGetData(n); /* To restore it later. */
        // 如果有指向 value 指针，在加上一个指针大小
        if (!n->isnull) newsize += sizeof(void*);
    }
    raxNode *newn = rax_realloc(n,newsize);
    if (newn == NULL) {
        rax_free(*child);
        return NULL;
    }
    n = newn;
  ```
+ 节点数据更新，将插入的字符串`s`及指向子节点指针添加到指定位置；
  ```c
    // 设置节点为压缩节点
    n->iscompr = 1;
    n->size = len;
    // 将字符串 s 拷贝到节点指定位置
    memcpy(n->data,s,len);
    // 将指向 value 指针更新到节点指定位置
    if (n->iskey) raxSetData(n,data);
    raxNode **childfield = raxNodeLastChildPtr(n);
    // 更新指向子节点指针
    memcpy(childfield,child,sizeof(*child));
    return n;
  ```

## rax树遍历
`rax`树遍历的函数`raxLowWalk`的定义如下：
```c
static inline size_t raxLowWalk(rax *rax, unsigned char *s, size_t len, raxNode **stopnode, raxNode ***plink, int *splitpos, raxStack *ts);
```
+ `rax`：需要遍历的`rax`树的地址；
+ `s`：查找的字符串地址；
+ `len`：查找的字符串长度；
+ `stopnode`：遍历结束的节点；
+ `plink`：在`stopnode`节点父节点中指向`stopnode`节点的指针地址；
+ `splitpos`：如果是压缩节点，表示在压缩节点中第一个不匹配`s`字符串的位置；
+ `ts`：`raxStack`结构，存放从头节点开始遍历到`stopnode`节点父节点的指针；

`raxLowWalk`的返回值表示已经检查查找字符串`s`中字符的个数。

`raxLowWalk`的实现如下：
```c
static inline size_t raxLowWalk(rax *rax, unsigned char *s, size_t len, raxNode **stopnode, raxNode ***plink, int *splitpos, raxStack *ts) {
    raxNode *h = rax->head;
    raxNode **parentlink = &rax->head;

    // i 表示检查字符串 s 中字符的位置，从 s[0] 开始检查
    size_t i = 0; /* Position in the string. */
    // j 表示当前检查节点存储的字符串中已检查的位置
    size_t j = 0; /* Position in the node children (or bytes if compressed).*/
    while(h->size && i < len) {
        debugnode("Lookup current node",h);
        // 当前检查节点存储的字符串地址
        unsigned char *v = h->data;
        // 压缩节点，只有一个子节点，处理逻辑
        if (h->iscompr) {
            for (j = 0; j < h->size && i < len; j++, i++) {
                if (v[j] != s[i]) break;
            }
            // 遇到不匹配，或者 s 遍历完，提前终止遍历
            if (j != h->size) break;
        // 非压缩节点，每个字符一个子节点，处理逻辑
        } else {
            /* Even when h->size is large, linear scan provides good
             * performances compared to other approaches that are in theory
             * more sounding, like performing a binary search. */
            for (j = 0; j < h->size; j++) {
                if (v[j] == s[i]) break;
            }
            // 在当前节点没有找到当前 s[i] 匹配字符，终止遍历
            if (j == h->size) break;
            i++;
        }

        if (ts) raxStackPush(ts,h); /* Save stack of parent nodes. */
        raxNode **children = raxNodeFirstChildPtr(h);
        if (h->iscompr) j = 0; /* Compressed node only child is at index 0. */
        // 更新遍历的节点 h 为下一个子节点
        memcpy(&h,children+j,sizeof(h));
        parentlink = children+j;
        j = 0; /* If the new node is compressed and we do not
                  iterate again (since i == l) set the split
                  position to 0 to signal this node represents
                  the searched key. */
    }
    debugnode("Lookup stop node is",h);
    if (stopnode) *stopnode = h;
    if (plink) *plink = parentlink;
    if (splitpos && h->iscompr) *splitpos = j;
    return i;
}
```

## rax树元素插入

`rax`树元素插入实现如下：
```c
/* Overwriting insert. Just a wrapper for raxGenericInsert() that will
 * update the element if there is already one for the same key. */
int raxInsert(rax *rax, unsigned char *s, size_t len, void *data, void **old) {
    return raxGenericInsert(rax,s,len,data,old,1);
}
```
实际会调用`raxGenericInsert`函数，`raxGenericInsert`函数的定义如下：
```c
int raxGenericInsert(rax *rax, unsigned char *s, size_t len, void *data, void **old, int overwrite);
```
+ `rax`：需要插入元素的`rax`树地址；
+ `s`：插入字符串地址；
+ `len`：插入字符串长度；
+ `data`：当前`key`对应的`value`地址（插入的每一个字符串都表示一个`key`）；
+ `old`：作为返回值，表示插入元素`s`已经存在，其对应的`value`地址；
+ `overwrite`：如果插入元素已经存在，是否更新已存在`value`地址；

`raxGenericInsert`操作有多种情况，分别如下：
+ 插入的元素已经存在；
  ```c
    size_t i;
    int j = 0; /* Split position. If raxLowWalk() stops in a compressed
                  node, the index 'j' represents the char we stopped within the
                  compressed node, that is, the position where to split the
                  node for insertion. */
    raxNode *h, **parentlink;

    debugf("### Insert %.*s with value %p\n", (int)len, s, data);
    // 遍历 rax 树查找元素 s。h 表示遍历终止的节点，parentlink 表示 h 的父节点中指向 h 的指针位置，
    // j 表示压缩节点中不匹配的字符位置，i 表示已经检查字符串 s 的位置。
    i = raxLowWalk(rax,s,len,&h,&parentlink,&j,NULL);

    /* If i == len we walked following the whole string. If we are not
     * in the middle of a compressed node, the string is either already
     * inserted or this middle node is currently not a key, but can represent
     * our key. We have just to reallocate the node and make space for the
     * data pointer. */
    // 在 rax 中存在字符串 s，且 s 不是在压缩节点中间某个位置结束，
    // 这时候不需要分裂节点
    if (i == len && (!h->iscompr || j == 0 /* not in the middle if j is 0 */)) {
        debugf("### Insert: node representing key exists\n");
        /* Make space for the value pointer if needed. */
        if (!h->iskey || (h->isnull && overwrite)) {
            // 从新分配空间，存放对应 value 数据的地址
            h = raxReallocForData(h,data);
            if (h) memcpy(parentlink,&h,sizeof(h));
        }
        if (h == NULL) {
            errno = ENOMEM;
            return 0;
        }

        /* Update the existing key if there is already one. */
        if (h->iskey) {
            if (old) *old = raxGetData(h);
            if (overwrite) raxSetData(h,data);
            errno = 0;
            return 0; /* Element already exists. */
        }

        /* Otherwise set the node as a key. Note that raxSetData()
         * will set h->iskey. */
        raxSetData(h,data);
        // 更新 rax 树 key 的个数加 1
        rax->numele++;
        return 1; /* Element inserted. */
    }
  ```
  插入元素`s`已经存在说明在遍历终止的节点`h`的所有父节点（不包含节点`h`）可以完全匹配查找字符串`s`。节点`h`可能是一个`key`（`iskey=1`），
  也可能不是一个`key`（`iskey=0`）。如果节点`h`没有存放对应`value`值的指针，需要重新分配节点空间存放`value`值指针，
  否则根据参数`overwrite`执行是否更新存放`value`地址。
+ 查找的字符串`s`不存在，遍历终止的节点`h`是压缩节点，且查找字符串`s`在节点`h`中间某个位置不匹配；
  假如插入前存在数据结构（两个压缩节点，箭头表示子节点指针）：
  ```bash
  "ANNIBALE" -> "SCO" -> []
  ```
  根据插入元素不同，分下面四种情况：
  + 插入`ANNIENTARE`元素后如下：
    ```bash
              |B| -> "ALE" -> "SCO" -> []
    "ANNI" -> |-|
              |E| -> (... continue algo ...) "NTARE" -> []
    ```
  + 插入`ANNIBALI`元素后如下：
    ```bash
                 |E| -> "SCO" -> []
    "ANNIBAL" -> |-|
                 |I| -> (... continue algo ...) []
    
    ```
  + 插入`AGO`元素后如下：
    ```bash
           |N| -> "NIBALE" -> "SCO" -> []
    |A| -> |-|
           |G| -> (... continue algo ...) |O| -> []
    ```
    插入前的原始节点需要设置`iscompr=0`。
  + 插入`CIAO`元素后如下：
    ```bash
    |A| -> "NNIBALE" -> "SCO" -> []
    |-|
    |C| -> (... continue algo ...) "IAO" -> []
    ```
  针对上面的插入情况，程序执行流程如下：
  + 保存插入前节点的`next`指针（指向子节点的指针）；
    ```bash
    "ANNIBALE" -> "SCO" -> []
    ```
    例如保存指向`SCO`子节点的指针；
    ```c
    // 终止节点是压缩节点，查询字符串 s 不存在，也就是在终止节点存储字符串中间某个位置不匹配
    if (h->iscompr && i != len) {
        /* 1: Save next pointer. */
        raxNode **childfield = raxNodeLastChildPtr(h);
        raxNode *next;
        memcpy(&next,childfield,sizeof(next));
    ```
  + 创建一个`split node`节点（存储一个字符的非压缩节点），将压缩节点中的第一个非公共字母作为`split node`存储的数据，插入元素中的非公共字母会在后面的步骤作为`split node`的子节点添加；
  如果压缩节点第一个非公共字母左边存在字符串数据，创建一个`trimmed`节点，保存左边字符串数据。如果压缩节点第一个非公共字母右边有字符串数据，
  创建一个`postfix`节点，保存右边的数据。
    ```bash
    // 原始压缩节点
    "ANNIBALE" -> "SCO" -> []

    // 例如插入 ANNIENTARE
              |B| -> "ALE" -> "SCO" -> []
    "ANNI" -> |-|
              |E| -> (... continue algo ...) "NTARE" -> []
    ```
    创建一个`split node`节点保存压缩字符串中第一个非公共字符`B`：
    ```bash
    +-------+--------+---------+------+-+-------+-----+----------+
    |iskey:0|isnull:0|iscompr:0|size:1|B|padding|B-Ptr|value-ptr?|
    +-------+--------+---------+------+-+-------+-----+----------+
    ```
    创建`trimmed`节点和`postfix`节点：
    ```bash
    // trimmed 节点
    +-------+--------+---------+------+----+-------+-----+----------+
    |iskey:?|isnull:?|iscompr:1|size:4|ANNI|padding|I-Ptr|value-ptr?|
    +-------+--------+---------+------+----+-------+-----+----------+
    // postfix 节点
    +-------+--------+---------+------+---+-------+-----+----------+
    |iskey:0|isnull:0|iscompr:1|size:3|ALE|padding|E-Ptr|value-ptr?|
    +-------+--------+---------+------+---+-------+-----+----------+
    ```
    源码实现如下：
    ```c
        /* Set the length of the additional nodes we will need. */
        // 压缩节点中第一个非公共字符左边字符串长度（不包括用于分割的非公共字符）
        size_t trimmedlen = j;
        // 压缩节点中第一个非公共字符右边字符串长度（不包括用于分割的非公共字符）
        size_t postfixlen = h->size - j - 1;
        // 如果是在压缩节点中间某个字符不匹配，则 split node 节点肯定不是 key，此时 split node 节点父节点是 trimmed 节点，
        // 如果是在压缩节点第一个字符不匹配，则 split node 节点是不是 key 取决于压缩节点 h，此时 split node 节点父节点是 h
        int split_node_is_key = !trimmedlen && h->iskey && !h->isnull;
        size_t nodesize;

        /* 2: Create the split node. Also allocate the other nodes we'll need
         *    ASAP, so that it will be simpler to handle OOM. */
        // 创建一个只包含一个子节点的 split node 节点，非压缩节点
        raxNode *splitnode = raxNewNode(1, split_node_is_key);
        raxNode *trimmed = NULL;
        raxNode *postfix = NULL;

        if (trimmedlen) {
            nodesize = sizeof(raxNode)+trimmedlen+raxPadding(trimmedlen)+
                       sizeof(raxNode*);
            if (h->iskey && !h->isnull) nodesize += sizeof(void*);
            trimmed = rax_malloc(nodesize);
        }

        if (postfixlen) {
            nodesize = sizeof(raxNode)+postfixlen+raxPadding(postfixlen)+
                       sizeof(raxNode*);
            postfix = rax_malloc(nodesize);
        }

        /* OOM? Abort now that the tree is untouched. */
        if (splitnode == NULL ||
            (trimmedlen && trimmed == NULL) ||
            (postfixlen && postfix == NULL))
        {
            rax_free(splitnode);
            rax_free(trimmed);
            rax_free(postfix);
            errno = ENOMEM;
            return 0;
        }
        splitnode->data[0] = h->data[j];

        if (j == 0) {
            /* 3a: Replace the old node with the split node. */
            if (h->iskey) {
                void *ndata = raxGetData(h);
                raxSetData(splitnode,ndata);
            }
            memcpy(parentlink,&splitnode,sizeof(splitnode));
        } else {
            /* 3b: Trim the compressed node. */
            trimmed->size = j;
            memcpy(trimmed->data,h->data,j);
            trimmed->iscompr = j > 1 ? 1 : 0;
            trimmed->iskey = h->iskey;
            trimmed->isnull = h->isnull;
            if (h->iskey && !h->isnull) {
                void *ndata = raxGetData(h);
                raxSetData(trimmed,ndata);
            }
            raxNode **cp = raxNodeLastChildPtr(trimmed);
            memcpy(cp,&splitnode,sizeof(splitnode));
            memcpy(parentlink,&trimmed,sizeof(trimmed));
            parentlink = cp; /* Set parentlink to splitnode parent. */
            rax->numnodes++;
        }

        /* 4: Create the postfix node: what remains of the original
         * compressed node after the split. */
        if (postfixlen) {
            /* 4a: create a postfix node. */
            postfix->iskey = 0;
            postfix->isnull = 0;
            postfix->size = postfixlen;
            postfix->iscompr = postfixlen > 1;
            memcpy(postfix->data,h->data+j+1,postfixlen);
            raxNode **cp = raxNodeLastChildPtr(postfix);
            memcpy(cp,&next,sizeof(next));
            rax->numnodes++;
        } else {
            /* 4b: just use next as postfix node. */
            postfix = next;
        }

        /* 5: Set splitnode first child as the postfix node. */
        raxNode **splitchild = raxNodeLastChildPtr(splitnode);
        memcpy(splitchild,&postfix,sizeof(postfix));

        /* 6. Continue insertion: this will cause the splitnode to
         * get a new child (the non common character at the currently
         * inserted key). */
        rax_free(h);
        h = splitnode;
    ```










































## rax树迭代器启动
`redis`创建一个`rax`迭代器的实现如下：
```c
/* Initialize a Rax iterator. This call should be performed a single time
 * to initialize the iterator, and must be followed by a raxSeek() call,
 * otherwise the raxPrev()/raxNext() functions will just return EOF. */
void raxStart(raxIterator *it, rax *rt) {
    it->flags = RAX_ITER_EOF; /* No crash if the iterator is not seeked. */
    it->rt = rt;
    it->key_len = 0;
    it->key = it->key_static_string;
    it->key_max = RAX_ITER_STATIC_LEN;
    it->data = NULL;
    it->node_cb = NULL;
    raxStackInit(&it->stack);
}
#define RAX_ITER_STATIC_LEN 128

/* Initialize the stack. */
static inline void raxStackInit(raxStack *ts) {
    ts->stack = ts->static_items;
    ts->items = 0;
    ts->maxitems = RAX_STACK_STATIC_ITEMS;
    ts->oom = 0;
}
#define RAX_STACK_STATIC_ITEMS 32
```
主要完成迭代器`raxIterator`对象各个属性初始化。

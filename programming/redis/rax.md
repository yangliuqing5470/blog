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

`redis`提供了`raxStack`和`raxIterator`两种数据结构用于`rax`树的遍历操作，`raxIterator`迭代器下面介绍。`raxStack`的结构定义如下：
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
            // 给 trimmed 节点分配内存
            nodesize = sizeof(raxNode)+trimmedlen+raxPadding(trimmedlen)+
                       sizeof(raxNode*);
            if (h->iskey && !h->isnull) nodesize += sizeof(void*);
            trimmed = rax_malloc(nodesize);
        }

        if (postfixlen) {
            // 给 postfix 节点分配内存
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
        // 将压缩节点中第一个非公共字符存入到 split node 节点中
        splitnode->data[0] = h->data[j];
        // 在压缩节点第一个字符不匹配（没有 trimmed 节点），
        // 此时 split node 节点承担之前的 h 节点位置
        if (j == 0) {
            /* 3a: Replace the old node with the split node. */
            if (h->iskey) {
                // 将原始节点中的 value 指针设置到 split node 节点中
                void *ndata = raxGetData(h);
                raxSetData(splitnode,ndata);
            }
            memcpy(parentlink,&splitnode,sizeof(splitnode));
        // 在压缩节点中间某个位置不匹配（有 trimmed 节点），
        // 此时 trimmed 节点承担之前的 h 节点位置
        } else {
            /* 3b: Trim the compressed node. */
            trimmed->size = j;
            // 将非公共节点左边（不包含非公共节点）拷贝到 trimmed 节点
            memcpy(trimmed->data,h->data,j);
            // 如果多个字符设置为压缩节点，单个字符设置为非压缩节点
            trimmed->iscompr = j > 1 ? 1 : 0;
            // iskey，isnull，value-ptr 和原始节点 h 保持一致
            trimmed->iskey = h->iskey;
            trimmed->isnull = h->isnull;
            if (h->iskey && !h->isnull) {
                void *ndata = raxGetData(h);
                raxSetData(trimmed,ndata);
            }
            // cp 是 trimmed 节点中最后指向子节点指针的位置
            raxNode **cp = raxNodeLastChildPtr(trimmed);
            // trimmed 最后一个字节点指针指向 splitnode 节点
            memcpy(cp,&splitnode,sizeof(splitnode));
            // 之前 h 的父节点设置指向 trimmed 节点
            memcpy(parentlink,&trimmed,sizeof(trimmed));
            parentlink = cp; /* Set parentlink to splitnode parent. */
            rax->numnodes++;
        }

        /* 4: Create the postfix node: what remains of the original
         * compressed node after the split. */
        // 设置 postfix 节点属性值，非 key 节点，因为是 h 节点分裂出的节点
        if (postfixlen) {
            /* 4a: create a postfix node. */
            postfix->iskey = 0;
            postfix->isnull = 0;
            postfix->size = postfixlen;
            // 如果多个字符设置为压缩节点，单个字符设置为非压缩节点
            postfix->iscompr = postfixlen > 1
            // 将非公共节点右边（不包含非公共节点）拷贝到 postfix 节点
            memcpy(postfix->data,h->data+j+1,postfixlen);
            raxNode **cp = raxNodeLastChildPtr(postfix);
            // postfix 节点的子节点指向之前保持的 next 值
            memcpy(cp,&next,sizeof(next));
            rax->numnodes++;
        } else {
            /* 4b: just use next as postfix node. */
            // 没有 postfix 节点
            postfix = next;
        }

        /* 5: Set splitnode first child as the postfix node. */
        // splitnode 节点的子节点指向 postfix 节点
        raxNode **splitchild = raxNodeLastChildPtr(splitnode);
        memcpy(splitchild,&postfix,sizeof(postfix));

        /* 6. Continue insertion: this will cause the splitnode to
         * get a new child (the non common character at the currently
         * inserted key). */
        // 是否旧的节点 h
        rax_free(h);
        h = splitnode;
    ```
+ 插入的元素`s`是压缩节点的前缀；
  ```bash
  // 原始压缩节点
  "ANNIBALE" -> "SCO" -> []

  // 插入 ANNI
  "ANNI" -> "BALE" -> "SCO" -> []
  ```
  这种情况，程序的执行流程如下：
  + 保存插入前节点的`next`指针（指向子节点的指针）；
    ```bash
    "ANNIBALE" -> "SCO" -> []
    ```
    例如保存指向`SCO`子节点的指针；
    ```c
    else if (h->iscompr && i == len) {
        /* 1: Save next pointer. */
        raxNode **childfield = raxNodeLastChildPtr(h);
        raxNode *next;
        memcpy(&next,childfield,sizeof(next));
    ```
  + 创建`trimmed`节点，保存压缩节点中分割点（`j`）左边的字符串（不包括分割点字符）和`postfix`节点，
  保存分割点右边字符串（包括分割点字符）；
    ```bash
    // trimmed 节点
    +-------+--------+---------+------+----+-------+-----+----------+
    |iskey:?|isnull:?|iscompr:1|size:4|ANNI|padding|I-Ptr|value-ptr?|
    +-------+--------+---------+------+----+-------+-----+----------+
    // postfix 节点
    +-------+--------+---------+------+---+-------+-----+----------+
    |iskey:1|isnull:0|iscompr:1|size:4|BALE|padding|E-Ptr|value-ptr?|
    +-------+--------+---------+------+---+-------+-----+----------+
    ```
    `trimmed`和`postfix`节点都是只有一个子节点。源码实现如下：
    ```c
        /* Allocate postfix & trimmed nodes ASAP to fail for OOM gracefully. */
        // 分配 postfix 节点内存，postfix 节点是个 key，因为可以完整找到插入元素 s
        size_t postfixlen = h->size - j;
        size_t nodesize = sizeof(raxNode)+postfixlen+raxPadding(postfixlen)+
                          sizeof(raxNode*);
        if (data != NULL) nodesize += sizeof(void*);
        raxNode *postfix = rax_malloc(nodesize);
        // 分配 trimmed 节点内存，trimmed 节点承担之前 h 节点位置
        nodesize = sizeof(raxNode)+j+raxPadding(j)+sizeof(raxNode*);
        if (h->iskey && !h->isnull) nodesize += sizeof(void*);
        raxNode *trimmed = rax_malloc(nodesize);

        if (postfix == NULL || trimmed == NULL) {
            rax_free(postfix);
            rax_free(trimmed);
            errno = ENOMEM;
            return 0;
        }
        /* 2: Create the postfix node. */
        postfix->size = postfixlen;
        postfix->iscompr = postfixlen > 1;
        // postfix 节点是个 key
        postfix->iskey = 1;
        postfix->isnull = 0;
        memcpy(postfix->data,h->data+j,postfixlen);
        raxSetData(postfix,data);
        // postfix 节点子节点指针指向保存的 next 值
        raxNode **cp = raxNodeLastChildPtr(postfix);
        memcpy(cp,&next,sizeof(next));
        rax->numnodes++;

        /* 3: Trim the compressed node. */
        trimmed->size = j;
        trimmed->iscompr = j > 1;
        trimmed->iskey = 0;
        trimmed->isnull = 0;
        memcpy(trimmed->data,h->data,j);
        // 之前 h 的父节点设置指向 trimmed 节点
        memcpy(parentlink,&trimmed,sizeof(trimmed));
        if (h->iskey) {
            void *aux = raxGetData(h);
            // 里面会更新 iskey 和 isnull 值
            raxSetData(trimmed,aux);
        }

        /* Fix the trimmed node child pointer to point to
         * the postfix node. */
        // trimmed 节点的子节点指针指向 postfix 节点
        cp = raxNodeLastChildPtr(trimmed);
        memcpy(cp,&postfix,sizeof(postfix));

        /* Finish! We don't need to continue with the insertion
         * algorithm for ALGO 2. The key is already inserted. */
        rax->numele++;
        rax_free(h);
        return 1; /* Key inserted. */
    }
    ```
+ 经过上面三步，继续走到此逻辑，说明插入的元素`s`没有遍历完，也就是`i < len`，需要将插入元素剩下的字符添加到`rax`树中；
  ```c
    /* We walked the radix tree as far as we could, but still there are left
     * chars in our string. We need to insert the missing nodes. */
    while(i < len) {
        raxNode *child;

        /* If this node is going to have a single child, and there
         * are other characters, so that that would result in a chain
         * of single-childed nodes, turn it into a compressed node. */
        if (h->size == 0 && len-i > 1) {
            debugf("Inserting compressed node\n");
            size_t comprsize = len-i;
            if (comprsize > RAX_NODE_MAX_SIZE)
                comprsize = RAX_NODE_MAX_SIZE;
            // 压缩节点，看上面节点添加详细介绍
            raxNode *newh = raxCompressNode(h,s+i,comprsize,&child);
            if (newh == NULL) goto oom;
            h = newh;
            memcpy(parentlink,&h,sizeof(h));
            parentlink = raxNodeLastChildPtr(h);
            i += comprsize;
        } else {
            debugf("Inserting normal node\n");
            raxNode **new_parentlink;
            // 非压缩节点，看上面节点添加详细介绍
            raxNode *newh = raxAddChild(h,s[i],&child,&new_parentlink);
            if (newh == NULL) goto oom;
            h = newh;
            memcpy(parentlink,&h,sizeof(h));
            parentlink = new_parentlink;
            i++;
        }
        rax->numnodes++;
        h = child;
    }
    // 下面主要更新指向 value 地址的指针
    raxNode *newh = raxReallocForData(h,data);
    if (newh == NULL) goto oom;
    h = newh;
    if (!h->iskey) rax->numele++;
    raxSetData(h,data);
    memcpy(parentlink,&h,sizeof(h));
    return 1; /* Element inserted. */
    
    // 下面是 oom 处理逻辑
    oom:
    /* This code path handles out of memory after part of the sub-tree was
     * already modified. Set the node as a key, and then remove it. However we
     * do that only if the node is a terminal node, otherwise if the OOM
     * happened reallocating a node in the middle, we don't need to free
     * anything. */
    if (h->size == 0) {
        h->isnull = 1;
        h->iskey = 1;
        rax->numele++; /* Compensate the next remove. */
        assert(raxRemove(rax,s,i,NULL) != 0);
    }
    errno = ENOMEM;
    return 0;
  }
  ```
## rax树元素查找
查找逻辑主要是调用`raxLowWalk`函数进行遍历查找，实现如下：
```c
/* Find a key in the rax, returns raxNotFound special void pointer value
 * if the item was not found, otherwise the value associated with the
 * item is returned. */
void *raxFind(rax *rax, unsigned char *s, size_t len) {
    raxNode *h;

    debugf("### Lookup: %.*s\n", (int)len, s);
    int splitpos = 0;
    // rax 树遍历，查找元素 s，遍历操作看上面介绍
    size_t i = raxLowWalk(rax,s,len,&h,NULL,&splitpos,NULL);
    if (i != len || (h->iscompr && splitpos != 0) || !h->iskey)
        return raxNotFound;
    return raxGetData(h);
}
```
## rax树元素删除
元素删除`raxRemove`函数定有如下：
```c
int raxRemove(rax *rax, unsigned char *s, size_t len, void **old);
```
+ `rax`：`rax`树地址；
+ `s`：要删除元素（`key`）地址；
+ `len`：要删除元素的长度；
+ `old`：如果要删除元素是个`key`，`old`是对应`value`的地址，如果要删除元素不是`key`，`old`是`NULL`；

删除操作涉及节点的合并操作，删除操作执行逻辑主要有以下几步：
+ 遍历查找`rax`树，如果没有找到要删除的元素`s`，直接返回`0`，否则执行下一步；
  ```c
  /* Remove the specified item. Returns 1 if the item was found and
   * deleted, 0 otherwise. */
  int raxRemove(rax *rax, unsigned char *s, size_t len, void **old) {
    raxNode *h;
    raxStack ts;

    debugf("### Delete: %.*s\n", (int)len, s);
    // 初始化 raxStack 对象，用于存储遍历查找 s 经历的节点地址，不包括停止节点 h
    raxStackInit(&ts);
    int splitpos = 0;
    size_t i = raxLowWalk(rax,s,len,&h,NULL,&splitpos,&ts);
    // rax 中不存在 s 的 key，直接返回
    if (i != len || (h->iscompr && splitpos != 0) || !h->iskey) {
        raxStackFree(&ts);
        return 0;
    }
  ```
+ 查找的元素存在，需要判断是否需要执行节点合并以及删除（针对停止节点是空节点）已遍历路径上那些只有一个子节点，且不是`key`的节点；
  ```c
    // 将删除元素对应的 value 地址存储在 old，返回给调用方
    if (old) *old = raxGetData(h);
    // 元素 s 要删除，所以 h->iskey 需要设置为 0 表示不是 key 节点
    h->iskey = 0;
    // rax 树元素（key）个数减 1
    rax->numele--;

    /* If this node has no children, the deletion needs to reclaim the
     * no longer used nodes. This is an iterative process that needs to
     * walk the three upward, deleting all the nodes with just one child
     * that are not keys, until the head of the rax is reached or the first
     * node with more than one child is found. */
    // 标志位，是否需要执行节点合并
    int trycompress = 0; /* Will be set to 1 if we should try to optimize the
                            tree resulting from the deletion. */
    // 如果停止节点是空节点（没有子节点），需要回收遍历路径上不使用的节点（回收只有一个子节点且不是 key 的节点）
    if (h->size == 0) {
        debugf("Key deleted in node without children. Cleanup needed.\n");
        raxNode *child = NULL;
        while(h != rax->head) {
            child = h;
            debugf("Freeing child %p [%.*s] key:%d\n", (void*)child,
                (int)child->size, (char*)child->data, child->iskey);
            // 释放节点内存
            rax_free(child);
            // 更新 rax 树的节点个数，减 1
            rax->numnodes--;
            h = raxStackPop(&ts);
             /* If this node has more then one child, or actually holds
              * a key, stop here. */
            if (h->iskey || (!h->iscompr && h->size != 1)) break;
        }
        if (child) {
            debugf("Unlinking child %p from parent %p\n",
                (void*)child, (void*)h);
            // 移除父节点和子节点之间的指向关系，因为子节点已经被删除了，返回值是新的父节点地址，
            // 如果父节点是压缩节点，直接将父节点转为空节点（没有子节点）非压缩节点即可，
            // 如果父节点不是压缩节点，需要删除指向 child 子节点指针，及对应的字符，涉及父节点内存重新分配
            raxNode *new = raxRemoveChild(h,child);
            // 因为 new 可能经过内存分配是个新的地址，需要更新下原始 h 父节点指向 new 的指针
            if (new != h) {
                raxNode *parent = raxStackPeek(&ts);
                raxNode **parentlink;
                if (parent == NULL) {
                    parentlink = &rax->head;
                } else {
                    parentlink = raxFindParentLink(parent,h);
                }
                memcpy(parentlink,&new,sizeof(new));
            }

            /* If after the removal the node has just a single child
             * and is not a key, we need to try to compress it. */
            // 更新后的非压缩节点 new 只有一个子节点，且不是 key，可能需要执行节点合并，设置 trycompress = 1
            if (new->size == 1 && new->iskey == 0) {
                trycompress = 1;
                h = new;
            }
        }
    // 如果停止节点 h 只有一个子节点，可能需要执行节点合并，
    // 这种场景下，不能回收节点，因为有其他的 key 依赖查询遍历的节点，
    // 如果节点 h 有多个子节点，说明结构已经满足 rax 数据结构，不需要合并
    } else if (h->size == 1) {
        /* If the node had just one child, after the removal of the key
         * further compression with adjacent nodes is pontentially possible. */
        trycompress = 1;
    }

    /* Don't try node compression if our nodes pointers stack is not
     * complete because of OOM while executing raxLowWalk() */
    if (trycompress && ts.oom) trycompress = 0;
  ```
+ 如果删除后需要执行节点合并。节点合并有如下几种情况：
  ```bash
  // 树存储 key FOO 和 key FOOBAR
  "FOO" -> "BAR" -> [] (2)
            (1)

  // 移除 FOO 后
  "FOOBAR" -> [] (2)
  ```
  另一种情况：
  ```bash
  // 树存储 key FOOBAR 和 key FOOTER
           |B| -> "AR" -> [] (1)
  "FOO" -> |-|
           |T| -> "ER" -> [] (2)

  // 移除 FOOTER
  "FOO" -> |B| -> "AR" -> [] (1)
  // 最后合并后
  "FOOBAR" -> [] (1)
  ```
  执行合并操作首先需要向根节点方向找到可以合并的起始节点，可以合并的节点必须是非`key`节点且如果是非压缩节点必须只有一个子节点：
  ```c
  if (trycompress) {
      /* Try to reach the upper node that is compressible.
         * At the end of the loop 'h' will point to the first node we
         * can try to compress and 'parent' to its parent. */
        raxNode *parent;
        // 遍历向上查找可以合并的起始节点
        while(1) {
            parent = raxStackPop(&ts);
            // 非 key 节点且如果是非压缩节点只能有一个子节点才可以合并
            if (!parent || parent->iskey ||
                (!parent->iscompr && parent->size != 1)) break;
            h = parent;
            debugnode("Going up to",h);
        }
        raxNode *start = h; /* Compression starting node. */
  ```
  然后需要遍历查找合并节点的个数以及合并后节点存储字符串大小：
  ```c
        /* Scan chain of nodes we can compress. */
        size_t comprsize = h->size;
        int nodes = 1;
        while(h->size != 0) {
            raxNode **cp = raxNodeLastChildPtr(h);
            memcpy(&h,cp,sizeof(h));
            // 判断子节点是否满足合并条件
            if (h->iskey || (!h->iscompr && h->size != 1)) break;
            /* Stop here if going to the next node would result into
             * a compressed node larger than h->size can hold. */
            if (comprsize + h->size > RAX_NODE_MAX_SIZE) break;
            nodes++;
            comprsize += h->size;
        }
  ```
  如果合并节点个数为`1`，直接返回；否则执行合并操作（合并后的节点是压缩节点）：
  ```c
        if (nodes > 1) {
            /* If we can compress, create the new node and populate it. */
            size_t nodesize =
                sizeof(raxNode)+comprsize+raxPadding(comprsize)+sizeof(raxNode*);
            // 合并后新的节点分配内存
            raxNode *new = rax_malloc(nodesize);
            /* An out of memory here just means we cannot optimize this
             * node, but the tree is left in a consistent state. */
            if (new == NULL) {
                raxStackFree(&ts);
                return 1;
            }
            // 合并后新的节点是个压缩节点，初始化节点属性
            // 因为参与合并的节点都是非 key 节点，所以这里设置为 iskey=0
            new->iskey = 0;
            new->isnull = 0;
            new->iscompr = 1;
            new->size = comprsize;
            rax->numnodes++;

            /* Scan again, this time to populate the new node content and
             * to fix the new node child pointer. At the same time we free
             * all the nodes that we'll no longer use. */
            comprsize = 0;
            h = start;
            // 将所有参与合并的节点存储的数据内容拷贝到新的节点 new 中
            while(h->size != 0) {
                memcpy(new->data+comprsize,h->data,h->size);
                comprsize += h->size;
                raxNode **cp = raxNodeLastChildPtr(h);
                raxNode *tofree = h;
                memcpy(&h,cp,sizeof(h));
                rax_free(tofree); rax->numnodes--;
                if (h->iskey || (!h->iscompr && h->size != 1)) break;
            }
            debugnode("New node",new);

            /* Now 'h' points to the first node that we still need to use,
             * so our new node child pointer will point to it. */
            // 更新新的合并后的节点 new 的子节点
            raxNode **cp = raxNodeLastChildPtr(new);
            memcpy(cp,&h,sizeof(h));

            /* Fix parent link. */
            // 更新指向新的合并后节点的父指针
            if (parent) {
                raxNode **parentlink = raxFindParentLink(parent,start);
                memcpy(parentlink,&new,sizeof(new));
            } else {
                rax->head = new;
            }

            debugf("Compressed %d nodes, %d total bytes\n",
                nodes, (int)comprsize);
        }
  ```
对于下面这种情况（都是压缩节点），删除后应该执行节点合并，但目前的源码并没有执行：
```bash
// 树存储 key FOO 和 key FOOBAR
"FOO" -> "BAR" -> [] (2)
          (1)

// 移除 FOO 后
"FOOBAR" -> [] (2)
```
`github`上有个[`pr`](https://github.com/redis/redis/pull/10825)针对这个情况，目前还没`merge`。

## rax树迭代器启动
迭代器`raxIterator`的数据结构如下：
```c
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

#define RAX_ITER_STATIC_LEN 128
```
+ `flags`：迭代器的标志位，取值有如下三种：
    + `RAX_ITER_JUST_SEEKED`：刚刚调用`raxSeek`函数，这时候可以取迭代器值，并清除这个标志；
    + `RAX_ITER_EOF`：迭代器遍历结束；
    + `RAX_ITER_SAFE`：安全迭代器标志；
+ `rt`：指向`rax`对象的指针；
+ `key`：迭代器当前`key`的字符串数组，小字符串指向`key_static_string`，大字符串指向堆空间分配的字符串数组地址；
+ `data`：迭代器当前`key`对应的`value`值；
+ `key_len`：迭代器当前`key`的长度；
+ `key_max`：当前`key`缓存的最大值；
+ `key_static_string`：字符串数组，存放迭代器当前`key`；
+ `node`：当前`key`所在的`raxNode`节点；
+ `stack`：记录从根节点到当前节点路径，用于节点向上遍历；
+ `node_cb`：节点回调函数，默认为`NULL`；

迭代器的启动`raxStart`函数实现如下：
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

/* Initialize the stack. */
static inline void raxStackInit(raxStack *ts) {
    ts->stack = ts->static_items;
    ts->items = 0;
    ts->maxitems = RAX_STACK_STATIC_ITEMS;
    ts->oom = 0;
}
```

## rax树迭代前/后一个元素
先看下向后迭代一个元素`raxIteratorNextStep`函数的实现（迭代下一个更大的`key`），其定义如下：
```c
int raxIteratorNextStep(raxIterator *it, int noup);
```
+ `it`：迭代器对象；
+ `noup`：是否可以向上遍历，取值`1`表示不向上遍历；`noup`取`1`表示迭代器的当前节点被假设是迭代器目标`key`的父节点，
需要从迭代器当前节点查找其他的子节点。

`raxIteratorNextStep`前置准备如下：
```c
int raxIteratorNextStep(raxIterator *it, int noup) {
    // 标志位检查
    if (it->flags & RAX_ITER_EOF) {
        return 1;
    } else if (it->flags & RAX_ITER_JUST_SEEKED) {
        it->flags &= ~RAX_ITER_JUST_SEEKED;
        return 1;
    }

    /* Save key len, stack items and the node where we are currently
     * so that on iterator EOF we can restore the current key and state. */
    size_t orig_key_len = it->key_len;
    size_t orig_stack_items = it->stack.items;
    raxNode *orig_node = it->node;
```
`raxIteratorNextStep`遍历逻辑如下：
+ 如果迭代器当前节点有子节点且不需要查找迭代器当前节点（`noup=0`），则沿着最左侧子节点（字典序最小）一直往下查找，
直到找到一个`key`；
  ```c
    while(1) {
        // 获取迭代器当前节点子节点个数
        int children = it->node->iscompr ? 1 : it->node->size;
        if (!noup && children) {
            debugf("GO DEEPER\n");
            /* Seek the lexicographically smaller key in this subtree, which
             * is the first one found always going torwards the first child
             * of every successive node. */
            if (!raxStackPush(&it->stack,it->node)) return 0;
            // 最左节点
            raxNode **cp = raxNodeFirstChildPtr(it->node);
            if (!raxIteratorAddChars(it,it->node->data,
                it->node->iscompr ? it->node->size : 1)) return 0;
            memcpy(&it->node,cp,sizeof(it->node));
            /* Call the node callback if any, and replace the node pointer
             * if the callback returns true. */
            if (it->node_cb && it->node_cb(&it->node))
                memcpy(cp,&it->node,sizeof(it->node));
            /* For "next" step, stop every time we find a key along the
             * way, since the key is lexicograhically smaller compared to
             * what follows in the sub-children. */
            if (it->node->iskey) {
                it->data = raxGetData(it->node);
                return 1;
            }
  ```
+ 如果迭代器当前节点没有子节点（或如果`noup=1`表示需要查找迭代器当前节点，这时候已经假设迭代器当前节点是目标`key`的父节点，第一次需要跳过从`raxStack`中弹出父节点），
依次弹出`raxStack`保存的遍历路径上父节点，查找父节点的其他子节点（找比当前`key`大的子节点）；
  ```c
    } else {
            /* If we finished exporing the previous sub-tree, switch to the
             * new one: go upper until a node is found where there are
             * children representing keys lexicographically greater than the
             * current key. */
            while(1) {
                int old_noup = noup;

                /* Already on head? Can't go up, iteration finished. */
                // 到达 head 节点（head 节点也已经查找了），迭代器终止
                if (!noup && it->node == it->rt->head) {
                    it->flags |= RAX_ITER_EOF;
                    it->stack.items = orig_stack_items;
                    it->key_len = orig_key_len;
                    it->node = orig_node;
                    return 1;
                }
                /* If there are no children at the current node, try parent's
                 * next child. */
                unsigned char prevchild = it->key[it->key_len-1];
                if (!noup) {
                    // 迭代器当前节点没有子节点，取出父节点
                    it->node = raxStackPop(&it->stack);
                } else {
                    // 对于 noup=1 ，第一次跳过取父节点，因为当前节点已经假设是父节点，需要查找其他子节点
                    noup = 0;
                }
                /* Adjust the current key to represent the node we are
                 * at. */
                int todel = it->node->iscompr ? it->node->size : 1;
                // 更新迭代器的 key，去掉当前节点存储的字符
                raxIteratorDelChars(it,todel);

                /* Try visiting the next child if there was at least one
                 * additional child. */
                if (!it->node->iscompr && it->node->size > (old_noup ? 0 : 1)) {
                    raxNode **cp = raxNodeFirstChildPtr(it->node);
                    int i = 0;
                    // 遍历当前节点所有的子节点，找到比当前 key 大的子节点
                    while (i < it->node->size) {
                        debugf("SCAN NEXT %c\n", it->node->data[i]);
                        if (it->node->data[i] > prevchild) break;
                        i++;
                        cp++;
                    }
                    // 找到了
                    if (i != it->node->size) {
                        debugf("SCAN found a new node\n");
                        raxIteratorAddChars(it,it->node->data+i,1);
                        if (!raxStackPush(&it->stack,it->node)) return 0;
                        // 更新迭代器的节点
                        memcpy(&it->node,cp,sizeof(it->node));
                        /* Call the node callback if any, and replace the node
                         * pointer if the callback returns true. */
                        if (it->node_cb && it->node_cb(&it->node))
                            memcpy(cp,&it->node,sizeof(it->node));
                        if (it->node->iskey) {
                            it->data = raxGetData(it->node);
                            return 1;
                        }
                        break;
                    }
                }
            }
        }
  ```
向前迭代一个元素`raxIteratorPrevStep`函数（迭代下一个更小的`key`）逻辑和`raxIteratorNextStep`差不多，这里不做介绍。

## rax树迭代查找
迭代器查找中某个元素函数`raxSeek`，其定义如下：
```c
int raxSeek(raxIterator *it, const char *op, unsigned char *ele, size_t len);
```
+ `it`：为`raxStart`初始化的迭代器；
+ `op`：查找操作符，取值`>`、`<`、`=`、`>=`、`<=`、`^`和`$`，其中`^`表示首元素，`$`表示末尾元素；
+ `ele`：要查找的元素`key`；
+ `len`：要查找元素的长度；

`raxSeek`变量初始化及参数解析如下：
```c
/* Seek an iterator at the specified element.
 * Return 0 if the seek failed for syntax error or out of memory. Otherwise
 * 1 is returned. When 0 is returned for out of memory, errno is set to
 * the ENOMEM value. */
int raxSeek(raxIterator *it, const char *op, unsigned char *ele, size_t len) {
    int eq = 0, lt = 0, gt = 0, first = 0, last = 0;

    it->stack.items = 0; /* Just resetting. Intialized by raxStart(). */
    it->flags |= RAX_ITER_JUST_SEEKED;
    it->flags &= ~RAX_ITER_EOF;
    it->key_len = 0;
    it->node = NULL;

    /* Set flags according to the operator used to perform the seek. */
    // 解析 op 参数
    if (op[0] == '>') {
        gt = 1;
        if (op[1] == '=') eq = 1;
    } else if (op[0] == '<') {
        lt = 1;
        if (op[1] == '=') eq = 1;
    } else if (op[0] == '=') {
        eq = 1;
    } else if (op[0] == '^') {
        first = 1;
    } else if (op[0] == '$') {
        last = 1;
    } else {
        errno = 0;
        return 0; /* Error. */
    }
```
查找首元素或者尾元素实现如下：
```c
    /* If there are no elements, set the EOF condition immediately and
     * return. */
    // 如果 rax 树没有元素，直接返回
    if (it->rt->numele == 0) {
        it->flags |= RAX_ITER_EOF;
        return 1;
    }
    // 查找首元素
    if (first) {
        /* Seeking the first key greater or equal to the empty string
         * is equivalent to seeking the smaller key available. */
        return raxSeek(it,">=",NULL,0);
    }
    // 查找尾元素
    if (last) {
        /* Find the greatest key taking always the last child till a
         * final node is found. */
        it->node = it->rt->head;
        if (!raxSeekGreatest(it)) return 0;
        assert(it->node->iskey);
        it->data = raxGetData(it->node);
        return 1;
    }
```
其中查找尾元素直接在`rax`树中找最右侧叶子节点，调用`raxSeekGreatest`函数，实现如下：
```c
/* Seek the grestest key in the subtree at the current node. Return 0 on
 * out of memory, otherwise 1. This is an helper function for different
 * iteration functions below. */
int raxSeekGreatest(raxIterator *it) {
    while(it->node->size) {
        if (it->node->iscompr) {
            // 压缩节点
            if (!raxIteratorAddChars(it,it->node->data,
                it->node->size)) return 0;
        } else {
            // 非压缩节点
            if (!raxIteratorAddChars(it,it->node->data+it->node->size-1,1))
                return 0;
        }
        raxNode **cp = raxNodeLastChildPtr(it->node);
        if (!raxStackPush(&it->stack,it->node)) return 0;
        // 继续查找最右侧的子节点
        memcpy(&it->node,cp,sizeof(it->node));
    }
    return 1;
}
```
`raxSeek`查找指定的元素`key`，程序执行有如下流程：
+ 如果指定的元素`ele`在`rax`树中找到，且`op`包含`=`，则操作完成；
  ```c
    /* We need to seek the specified key. What we do here is to actually
     * perform a lookup, and later invoke the prev/next key code that
     * we already use for iteration. */
    int splitpos = 0;
    // 遍历 rax 树，查找 ele，it->node 是遍历终止节点
    size_t i = raxLowWalk(it->rt,ele,len,&it->node,NULL,&splitpos,&it->stack);

    /* Return OOM on incomplete stack info. */
    if (it->stack.oom) return 0;

    if (eq && i == len && (!it->node->iscompr || splitpos == 0) &&
        it->node->iskey)
    {
        /* We found our node, since the key matches and we have an
         * "equal" condition. */
        if (!raxIteratorAddChars(it,ele,len)) return 0; /* OOM. */
        it->data = raxGetData(it->node);
    }
  ```
+ 如果指定的元素`ele`在`rax`树中没找到，且`op`设置为`=`，则设置迭代器标志为`RAX_ITER_EOF`返回；
  ```c
    else {
        /* If we are here just eq was set but no match was found. */
        it->flags |= RAX_ITER_EOF;
        return 1;
    }
  ```
+ 如果指定的元素`ele`在`rax`树中没找到，且`op`包含`>`或者`<`，则继续查找；
  + 更新`it->key`值，也就是将遍历到终止节点经历的所有节点数据存储到`it->key`：
    ```c
      else if (lt || gt) {
        /* Exact key not found or eq flag not set. We have to set as current
         * key the one represented by the node we stopped at, and perform
         * a next/prev operation to seek. To reconstruct the key at this node
         * we start from the parent and go to the current node, accumulating
         * the characters found along the way. */
        if (!raxStackPush(&it->stack,it->node)) return 0;
        for (size_t j = 1; j < it->stack.items; j++) {
            raxNode *parent = it->stack.stack[j-1];
            raxNode *child = it->stack.stack[j];
            if (parent->iscompr) {
                // 压缩节点
                if (!raxIteratorAddChars(it,parent->data,parent->size))
                    return 0;
            } else {
                // 非压缩节点
                raxNode **cp = raxNodeFirstChildPtr(parent);
                unsigned char *p = parent->data;
                // 找到子节点位置
                while(1) {
                    raxNode *aux;
                    memcpy(&aux,cp,sizeof(aux));
                    if (aux == child) break;
                    cp++;
                    p++;
                }
                if (!raxIteratorAddChars(it,p,1)) return 0;
            }
        }
        raxStackPop(&it->stack);
    ```
  + 如果终止节点`it->node`是非压缩节点，且待查找的元素`ele`没有比较完，也就是`i != len`（由于不匹配停止在非压缩节点中间），
  直接在迭代器当前节点（也就是停止节点）查找子节点（将当前节点作为父节点，`noup=1`）：
    ```c
        if (i != len && !it->node->iscompr) {
            /* If we stopped in the middle of a normal node because of a
             * mismatch, add the mismatching character to the current key
             * and call the iterator with the 'noup' flag so that it will try
             * to seek the next/prev child in the current node directly based
             * on the mismatching character. */
            if (!raxIteratorAddChars(it,ele+i,1)) return 0;
            debugf("Seek normal node on mismatch: %.*s\n",
                (int)it->key_len, (char*)it->key);

            it->flags &= ~RAX_ITER_JUST_SEEKED;
            if (lt && !raxIteratorPrevStep(it,1)) return 0;
            if (gt && !raxIteratorNextStep(it,1)) return 0;
            it->flags |= RAX_ITER_JUST_SEEKED; /* Ignore next call. */
        }
    ```
  + 如果终止节点`it->node`是压缩节点，且待查找的元素`ele`没有比较完，也就是`i != len`（由于不匹配停止在压缩节点中间）：
    ```c
        else if (i != len && it->node->iscompr) {
            debugf("Compressed mismatch: %.*s\n",
                (int)it->key_len, (char*)it->key);
            /* In case of a mismatch within a compressed node. */
            // 终止节点中不匹配的字符
            int nodechar = it->node->data[splitpos];
            // 待查找元素不匹配字符
            int keychar = ele[i];
            it->flags &= ~RAX_ITER_JUST_SEEKED;
            if (gt) {
                /* If the key the compressed node represents is greater
                 * than our seek element, continue forward, otherwise set the
                 * state in order to go back to the next sub-tree. */
                // 如果是 > ，且终止节点不匹配字符已经大于待查找元素不匹配字符，直接在终止节点的子节点查找即可
                if (nodechar > keychar) {
                    if (!raxIteratorNextStep(it,0)) return 0;
                } else {
                    // 终止节点不匹配字符小于待查找元素不匹配字符，由于是压缩节点，更新 it->key 为了可以正确在父节点查找其他子节点
                    // 在 raxIteratorNextStep 中，对于压缩节点，it->key 会直接删除压缩节点全部字符串，所有这里先加上
                    if (!raxIteratorAddChars(it,it->node->data,it->node->size))
                        return 0;
                    if (!raxIteratorNextStep(it,1)) return 0;
                }
            }
            if (lt) {
                /* If the key the compressed node represents is smaller
                 * than our seek element, seek the greater key in this
                 * subtree, otherwise set the state in order to go back to
                 * the previous sub-tree. */
                if (nodechar < keychar) {
                    // 终止节点不匹配字符小于待查找元素不匹配字符，直接查找终止节点的最右侧的子树
                    if (!raxSeekGreatest(it)) return 0;
                    it->data = raxGetData(it->node);
                } else {
                    // 终止节点不匹配字符大于待查找元素不匹配字符，更新 it->key 为了可以正确在父节点查找其他子节点，
                    // 在 raxIteratorNextStep 中，对于压缩节点，it->key 会直接删除压缩节点全部字符串，所有这里先加上
                    if (!raxIteratorAddChars(it,it->node->data,it->node->size))
                        return 0;
                    if (!raxIteratorPrevStep(it,1)) return 0;
                }
            }
            it->flags |= RAX_ITER_JUST_SEEKED; /* Ignore next call. */
        }
    ```
  + 如果所有`ele`元素匹配完成，但停止在压缩节点中间，或者停止节点不是`key`：
    ```c
        else {
            debugf("No mismatch: %.*s\n",
                (int)it->key_len, (char*)it->key);
            /* If there was no mismatch we are into a node representing the
             * key, (but which is not a key or the seek operator does not
             * include 'eq'), or we stopped in the middle of a compressed node
             * after processing all the key. Continue iterating as this was
             * a legitimate key we stopped at. */
            it->flags &= ~RAX_ITER_JUST_SEEKED;
            if (it->node->iscompr && it->node->iskey && splitpos && lt) {
                /* If we stopped in the middle of a compressed node with
                 * perfect match, and the condition is to seek a key "<" than
                 * the specified one, then if this node is a key it already
                 * represents our match. For instance we may have nodes:
                 *
                 * "f" -> "oobar" = 1 -> "" = 2
                 *
                 * Representing keys "f" = 1, "foobar" = 2. A seek for
                 * the key < "foo" will stop in the middle of the "oobar"
                 * node, but will be our match, representing the key "f".
                 *
                 * So in that case, we don't seek backward. */
            } else {
                if (gt && !raxIteratorNextStep(it,0)) return 0;
                if (lt && !raxIteratorPrevStep(it,0)) return 0;
            }
            it->flags |= RAX_ITER_JUST_SEEKED; /* Ignore next call. */
        }
    ```
## rax树迭代器停止
`raxStop`实现如下：
```c
/* Free the iterator. */
void raxStop(raxIterator *it) {
    if (it->key != it->key_static_string) rax_free(it->key);
    raxStackFree(&it->stack);
}
```

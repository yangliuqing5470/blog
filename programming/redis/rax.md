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
+ `head`：指向头节点（根节点）的指针；
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
    // 初始化 head 节点，head 节点没有子节点和指向`value`值的指针
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

## rax树元素插入








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

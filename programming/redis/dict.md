> 基于`redis`源码分支`5.0`
# 字典
## 数据结构定义
`redis`字典底层使用哈希表实现，哈希表可以有多个哈希节点，一个哈希节点保存一个健值对。在`dict.h`中，哈希节点的定义如下：
```c
typedef struct dictEntry {
    void *key;
    union {
        void *val;
        uint64_t u64;
        int64_t s64;
        double d;
    } v;
    struct dictEntry *next;
} dictEntry;
```
+ `key`：表示健值对中的健值，可以是任意数据类型。
+ `v`：表示健值对的值，值可以是一个任意类型的指针，或者一个`uint64_t`类型的数据，或者是`int64_t`类型的数据，
在或者是`double`类型的数据。
+ `next`：指向另一个哈希节点的指针，用于解决哈希冲突问题（冲突的健用单向链表解决）。

哈希表的定义如下：
```c
/* This is our hash table structure. Every dictionary has two of this as we
 * implement incremental rehashing, for the old to the new table. */
typedef struct dictht {
    dictEntry **table;
    unsigned long size;
    unsigned long sizemask;
    unsigned long used;
} dictht;
```
+ `table`：表示一个数组，数组中的每一个元素都是`dictEntry`类型的元素（也即哈希节点）；
+ `size`：表示哈希表的大小，也即`table`数组的大小；
+ `used`：表示当前哈希表已有哈希节点数量；
+ `sizemask`：取值为`size-1`，用于和健值对中健计算的哈希值一起决定应该存放`table`数组索引；

下面给出了哈希表和哈希节点的关系样例：
```bash
   dictht              哈希节点
+----------+      +----------------+
|  table   | ---> | dictEntry *[4] |
+----------+      +----------------+
|   size   |      |       0        | ---> NULL
|    4     |      +----------------+
+----------+      |       1        | ---> NULL              dictEntry
| sizemask |      +----------------+      +---------+      +---------+
|    3     |      |       2        | ---> | k1 | v1 | ---> | k0 | v0 |
+----------+      +----------------+      +---------+      +---------+
|   used   |      |       3        | ---> NULL
|    2     |      +----------------+
+----------+
```
字典的定义如下：
```c
typedef struct dict {
    dictType *type;
    void *privdata;
    dictht ht[2];
    long rehashidx; /* rehashing not in progress if rehashidx == -1 */
    unsigned long iterators; /* number of iterators currently running */
} dict;

// dictType 类型
typedef struct dictType {
    // 计算健的哈希值函数
    uint64_t (*hashFunction)(const void *key);
    // 复制健函数
    void *(*keyDup)(void *privdata, const void *key);
    // 复制值函数
    void *(*valDup)(void *privdata, const void *obj);
    // 比较健的函数
    int (*keyCompare)(void *privdata, const void *key1, const void *key2);
    // 销毁健的函数
    void (*keyDestructor)(void *privdata, void *key);
    // 销毁值的函数
    void (*valDestructor)(void *privdata, void *obj);
} dictType;
```
+ `type`：指向`dictType`类型的指针，`dictType`结构保存一簇用于操作特定类型健值对的函数，`redis`为不同类型的字典设置不同类型的特定函数。
+ `privdata`：`dictType`结构里函数的参数。
+ `ht`：包含两个哈希表（`dictht`）的数组，一般情况下字典只使用`ht[0]`哈希表，`ht[1]`哈希表只是对`ht[0]`哈希表进行`rehash`操作时候使用。
+ `rehashidx`：记录`rehash`的进度，用于渐进式`rehash`操作（`rehash`操作分多次操作完成，下面会介绍）。
+ `iterators`：当前正在运作的安全迭代器数量。

下面给出`dict`数据结构的说明样例：
```bash
    dict         ht[0]       dictht
+-----------+    +---> +-------------+      +----------------+
|   type    |    |     |   table     | ---> | dictEntry *[4] |              dictEntry
+-----------+    |     +-------------+      +----------------+      +--------------------+
| privdata  |    |     | sizemask: 3 |      |       0        | ---> | key1 | val1 | next | ---> NULL
+-----------+    |     +-------------+      +----------------+      +--------------------+
|           |    |     |   size: 4   |      |       1        | ---> NULL
|    ht     | ---+     +-------------+      +----------------|      +--------------------+
|           |    |     |   used: 2   |      |       2        | ---> | key2 | val2 | next | ---> NULL
+-----------+    |     +-------------+      +----------------+      +--------------------+
| rehashidx |    |                          |       3        | ---> NULL
+-----------+    |                          +----------------+
| iterators |    |
+-----------+    +---> +-------------+
                 ht[1] |    table    | ---> NULL
                       +-------------+
                       |    size: 0  |
                       +-------------+
                       | sizemask: 0 |
                       +-------------+
                       |    used: 0  |
                       +-------------+
```
## 哈希表索引计算
将一个新的健值对添加到字典中时，需要根据健值计算出存放的哈希表索引。哈希表索引计算规则如下：
```c
// 计算 key 的哈希值，参数 d 表示字典对象 dict
#define dictHashKey(d, key) (d)->type->hashFunction(key)
hash = dictHashKey(d,key);
// 结合哈希表的 sizemask 值，计算索引值。根据是否需要 rehash 操作，ht[table]可能是ht[0]或者ht[1]
idx = hash & d->ht[table].sizemask;
```
获取哈希表索引的源码实现如下：
```c
/* Returns the index of a free slot that can be populated with
 * a hash entry for the given 'key'.
 * If the key already exists, -1 is returned
 * and the optional output parameter may be filled.
 *
 * Note that if we are in the process of rehashing the hash table, the
 * index is always returned in the context of the second (new) hash table. */
static long _dictKeyIndex(dict *d, const void *key, uint64_t hash, dictEntry **existing)
{
    unsigned long idx, table;
    dictEntry *he;
    // 初始化，existing 指向哈希表中存在的项地址（存放健值对的哈希节点地址）
    if (existing) *existing = NULL;

    /* Expand the hash table if needed */
    if (_dictExpandIfNeeded(d) == DICT_ERR)
        return -1;
    for (table = 0; table <= 1; table++) {
        idx = hash & d->ht[table].sizemask;
        /* Search if this slot does not already contain the given key */
        he = d->ht[table].table[idx];
        while(he) {
            // 判断指定的健是否已经存在，存在返回-1
            if (key==he->key || dictCompareKeys(d, key, he->key)) {
                if (existing) *existing = he;
                return -1;
            }
            he = he->next;
        }
        if (!dictIsRehashing(d)) break;
    }
    return idx;

#define dictIsRehashing(d) ((d)->rehashidx != -1)
#define dictCompareKeys(d, key1, key2) \
    (((d)->type->keyCompare) ? \
        (d)->type->keyCompare((d)->privdata, key1, key2) : \
        (key1) == (key2))
```
如果当前字典在`rehash`操作中（字典的`rehashidx != -1`），则从`ht[1]`哈希表返回索引，否则从`ht[0]`表返回索引。

## 哈希冲突
当多个健计算得到相同的哈希索引时，就发送了冲突。`redis`的字典数据结构使用链表方式解决哈希冲突，也就是每一个哈希节点`dictEntry`都有一个`next`指针，
指向下一个哈希节点`dictEntry`，这样发生冲突的健值对，使用链表数据结构连接。哈希冲突数据结构样例说明如下：
```bash
   dictht              哈希节点
+----------+      +----------------+
|  table   | ---> | dictEntry *[4] |
+----------+      +----------------+
|   size   |      |       0        | ---> NULL
|    4     |      +----------------+
+----------+      |       1        | ---> NULL              dictEntry
| sizemask |      +----------------+      +---------+      +---------+
|    3     |      |       2        | ---> | k1 | v1 | ---> | k0 | v0 |
+----------+      +----------------+      +---------+      +---------+
|   used   |      |       3        | ---> NULL
|    2     |      +----------------+
+----------+
```
其中健`key1`和`key0`存在哈希冲突，使用链表连接。

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
其中健`key1`和`key0`存在哈希冲突，使用链表连接。程序总是将新节点添加到链表的头位置，
添加新的键值对实现如下：
```c
/* Add an element to the target hash table */
int dictAdd(dict *d, void *key, void *val)
{
    dictEntry *entry = dictAddRaw(d,key,NULL);

    if (!entry) return DICT_ERR;
    // 更新对应的 val 值
    dictSetVal(d, entry, val);
    return DICT_OK;
}

/* Low level add or find:
 * This function adds the entry but instead of setting a value returns the
 * dictEntry structure to the user, that will make sure to fill the value
 * field as he wishes.
 *
 * This function is also directly exposed to the user API to be called
 * mainly in order to store non-pointers inside the hash value, example:
 *
 * entry = dictAddRaw(dict,mykey,NULL);
 * if (entry != NULL) dictSetSignedIntegerVal(entry,1000);
 *
 * Return values:
 *
 * If key already exists NULL is returned, and "*existing" is populated
 * with the existing entry if existing is not NULL.
 *
 * If key was added, the hash entry is returned to be manipulated by the caller.
 */
dictEntry *dictAddRaw(dict *d, void *key, dictEntry **existing)
{
    long index;
    dictEntry *entry;
    dictht *ht;

    if (dictIsRehashing(d)) _dictRehashStep(d);

    /* Get the index of the new element, or -1 if
     * the element already exists. */
    if ((index = _dictKeyIndex(d, key, dictHashKey(d,key), existing)) == -1)
        return NULL;

    /* Allocate the memory and store the new entry.
     * Insert the element in top, with the assumption that in a database
     * system it is more likely that recently added entries are accessed
     * more frequently. */
    ht = dictIsRehashing(d) ? &d->ht[1] : &d->ht[0];
    entry = zmalloc(sizeof(*entry));
    //将新添加的哈希节点放在链表头位置
    entry->next = ht->table[index];
    ht->table[index] = entry;
    ht->used++;

    /* Set the hash entry fields. */
    dictSetKey(d, entry, key);
    return entry;
}
```
## rehash操作
随着操作的不断进行，字典中的哈希表保存的键值对会不断增加或者减少，为了让哈希表的负载因子维持在一个合理的范围内，
当哈希表中的键值对过多或者过少时，需要对哈希表大小调整，进行拓展或者收缩操作。

负载因子通过如下公式计算：
```c
// ht[0] 表示哈希表
load_factor = ht[0].used / ht[0].size;
```
`rehash`步骤如下：
+ 给字典哈希表`ht[1]`分配空间，分配空间大小策略如下：
  + 如果是扩展操作，分配空间大小`size`满足`size >= ht[0].used * 2`，且`size`是`2**n`；
    ```c
    /* Expand the hash table if needed */
    static int _dictExpandIfNeeded(dict *d)
    {
        /* Incremental rehashing already in progress. Return. */
        if (dictIsRehashing(d)) return DICT_OK;
    
        /* If the hash table is empty expand it to the initial size. */
        if (d->ht[0].size == 0) return dictExpand(d, DICT_HT_INITIAL_SIZE);
    
        /* If we reached the 1:1 ratio, and we are allowed to resize the hash
         * table (global setting) or we should avoid it but the ratio between
         * elements/buckets is over the "safe" threshold, we resize doubling
         * the number of buckets. */
        // dict_can_resize: 1  dict_force_resize_ratio: 5
        // 哈希表的负载因子大于 1 或者 5 执行拓展空间分配
        if (d->ht[0].used >= d->ht[0].size &&
            (dict_can_resize ||
             d->ht[0].used/d->ht[0].size > dict_force_resize_ratio))
        {
            // 分配空间大小下限是 d->ht[0].used * 2
            return dictExpand(d, d->ht[0].used*2);
        }
        return DICT_OK;
    }
    ```
    实际的哈希表拓展操作实现`dictExpand`如下：
    ```c
    /* Our hash table capability is a power of two */
    // 获取大于等于 size 值的最小 2 的 n 次方值
    static unsigned long _dictNextPower(unsigned long size)
    {
        unsigned long i = DICT_HT_INITIAL_SIZE;
    
        if (size >= LONG_MAX) return LONG_MAX + 1LU;
        while(1) {
            if (i >= size)
                return i;
            i *= 2;
        }
    }

    /* Expand or create the hash table */
    int dictExpand(dict *d, unsigned long size)
    {
        /* the size is invalid if it is smaller than the number of
         * elements already inside the hash table */
        if (dictIsRehashing(d) || d->ht[0].used > size)
            return DICT_ERR;
    
        dictht n; /* the new hash table */
        // 获取新空间大小
        unsigned long realsize = _dictNextPower(size);
    
        /* Rehashing to the same table size is not useful. */
        if (realsize == d->ht[0].size) return DICT_ERR;
    
        /* Allocate the new hash table and initialize all pointers to NULL */
        n.size = realsize;
        n.sizemask = realsize-1;
        n.table = zcalloc(realsize*sizeof(dictEntry*));
        n.used = 0;
    
        /* Is this the first initialization? If so it's not really a rehashing
         * we just set the first hash table so that it can accept keys. */
        if (d->ht[0].table == NULL) {
            d->ht[0] = n;
            return DICT_OK;
        }
    
        /* Prepare a second hash table for incremental rehashing */
        // 将哈希表 ht[1] 指向新的哈希表
        d->ht[1] = n;
        // 设置 rehashidx = 0，开始 rehash 操作
        d->rehashidx = 0;
        return DICT_OK;
    }
    ```
  + 如果收缩操作，分配空间大小`size`满足`size >= ht[0].used`，且`size`是`2**n`；
    ```c
    /* Resize the table to the minimal size that contains all the elements,
     * but with the invariant of a USED/BUCKETS ratio near to <= 1 */
    int dictResize(dict *d)
    {
        int minimal;
    
        if (!dict_can_resize || dictIsRehashing(d)) return DICT_ERR;
        // 分配空间大小下限是 d->ht[0].used
        minimal = d->ht[0].used;
        if (minimal < DICT_HT_INITIAL_SIZE)
            minimal = DICT_HT_INITIAL_SIZE;
        return dictExpand(d, minimal);
    }
    ```
+ 将`ht[0]`哈希表中保存的键值对`rehash`到新的`ht[1]`上；
+ 当`ht[0]`哈希表中的所有键值对都迁移到新的`ht[1]`哈希表中后，释放旧的`ht[0]`哈希表，
将新的`ht[1]`设置为`ht[0]`，在`ht[1]`新创建一个空的哈希表，给下一次`rehash`做准备；

## 渐进式rehash
由于一次集中地将旧的哈希表`ht[0]`中保存的键值对全部迁移到新的`ht[1]`哈希表可能比较耗时，
导致`redis`服务在此时间内不能提供服务，所以`redis`通过多次，渐进式地将`ht[0]`哈希表中的键值对迁移到`ht[1]`。

渐进`rehash`执行步骤如下：
+ 为`ht[1]`哈希表分配空间，字典同时有`ht[0]`和`ht[1]`两个哈希表；
+ 在字典对象`dict`维护一个`rehashidx`计数器，将其设置为`0`，表示`rehash`开始；
+ 在`rehash`期间，每次对字典执行添加，删除，查找或者更新操作时，程序都会顺带将`ht[0]`哈希表在`rehashidx`索引上的所有键值对都`rehash`到`ht[1]`上，
当前`rehash`操作完成后，将`rehashidx`自增`1`；
+ 随着字典操作不断进行，最终在某个时间点，`ht[0]`上全部的键值对都被`rehash`到`ht[1]`上，
此时将`rehashidx`设置为`-1`，表示`rehash`操作完成；
  ```c
  /* This function performs just a step of rehashing, and only if there are
   * no safe iterators bound to our hash table. When we have iterators in the
   * middle of a rehashing we can't mess with the two hash tables otherwise
   * some element can be missed or duplicated.
   *
   * This function is called by common lookup or update operations in the
   * dictionary so that the hash table automatically migrates from H1 to H2
   * while it is actively used. */
  static void _dictRehashStep(dict *d) {
      if (d->iterators == 0) dictRehash(d,1);
  }

  /* Performs N steps of incremental rehashing. Returns 1 if there are still
   * keys to move from the old to the new hash table, otherwise 0 is returned.
   *
   * Note that a rehashing step consists in moving a bucket (that may have more
   * than one key as we use chaining) from the old to the new hash table, however
   * since part of the hash table may be composed of empty spaces, it is not
   * guaranteed that this function will rehash even a single bucket, since it
   * will visit at max N*10 empty buckets in total, otherwise the amount of
   * work it does would be unbound and the function may block for a long time. */
  int dictRehash(dict *d, int n) {
      int empty_visits = n*10; /* Max number of empty buckets to visit. */
      if (!dictIsRehashing(d)) return 0;
  
      while(n-- && d->ht[0].used != 0) {
          dictEntry *de, *nextde;
  
          /* Note that rehashidx can't overflow as we are sure there are more
           * elements because ht[0].used != 0 */
          assert(d->ht[0].size > (unsigned long)d->rehashidx);
          // 旧的 ht[0] 哈希表在当前索引 d->rehashidx 上没有哈希节点，也就是没有保存健值对
          // 当前调用在旧的 ht[0] 哈希表，最多查看 empty_visits 个空槽位
          while(d->ht[0].table[d->rehashidx] == NULL) {
              d->rehashidx++;
              if (--empty_visits == 0) return 1;
          }
          // 取出旧的 ht[0] 哈希表在 d->rehashidx 索引对应的哈希节点，并将其包括所有
          // 可能存在冲突的链表哈希节点都移动到新的 ht[1] 哈希表。
          de = d->ht[0].table[d->rehashidx];
          /* Move all the keys in this bucket from the old to the new hash HT */
          while(de) {
              uint64_t h;
              // 链表的下一个准备 rehash 的节点 
              nextde = de->next;
              /* Get the index in the new hash table */
              // 计算要 rehash 的哈希节点在新的 ht[1] 哈希表的索引
              h = dictHashKey(d, de->key) & d->ht[1].sizemask;
              // 将新加的哈希节点放在链表头位置
              de->next = d->ht[1].table[h];
              d->ht[1].table[h] = de;
              // 旧的 ht[0] 哈希表哈希节点数减1
              d->ht[0].used--;
              // 新的 ht[1] 哈希表哈希节点数加1
              d->ht[1].used++;
              de = nextde;
          }
          // 更新旧的 ht[0] 哈希表在 d->rehashidx 索引处位空，因为已经 rehash 到新的 ht[1] 哈希表了
          d->ht[0].table[d->rehashidx] = NULL;
          // 更新 d->rehashidx 值，为下次 rehash 做准备
          d->rehashidx++;
      }
  
      /* Check if we already rehashed the whole table... */
      // 检查旧的 ht[0] 哈希表是否都 rehash 完成
      if (d->ht[0].used == 0) {
          // 释放旧的 ht[0] 哈希表
          zfree(d->ht[0].table);
          // 将新的 ht[1] 哈希表设置为 ht[0]
          d->ht[0] = d->ht[1];
          // d->ht[1] 哈希表设置为空
          _dictReset(&d->ht[1]);
          // 将 d->rehashidx 设置为 -1，表示 rehash 完成
          d->rehashidx = -1;
          return 0;
      }
  
      /* More to rehash... */
      return 1;
  }
  ```

通过渐进式操作，将集中`rehash`操作时间开销平摊到对字典的每次操作上。

在`rehash`过程中，字典同时有`ht[0]`和`ht[1]`两个哈希表，所以在字典删除，查找，更新等操作会在两个哈希表进行。
例如，在字典查找一个键，会先在`ht[0]`查找，如果没找到会在`ht[1]`查找。新增加的键值对保存在`ht[1]`哈希表，
在`ht[0]`哈希表不进行任何新增操作。

哈希表添加操作实现如下：
```c
/* Add an element to the target hash table */
int dictAdd(dict *d, void *key, void *val)
{
    dictEntry *entry = dictAddRaw(d,key,NULL);

    if (!entry) return DICT_ERR;
    dictSetVal(d, entry, val);
    return DICT_OK;
}

/* Low level add or find:
 * This function adds the entry but instead of setting a value returns the
 * dictEntry structure to the user, that will make sure to fill the value
 * field as he wishes.
 *
 * This function is also directly exposed to the user API to be called
 * mainly in order to store non-pointers inside the hash value, example:
 *
 * entry = dictAddRaw(dict,mykey,NULL);
 * if (entry != NULL) dictSetSignedIntegerVal(entry,1000);
 *
 * Return values:
 *
 * If key already exists NULL is returned, and "*existing" is populated
 * with the existing entry if existing is not NULL.
 *
 * If key was added, the hash entry is returned to be manipulated by the caller.
 */
dictEntry *dictAddRaw(dict *d, void *key, dictEntry **existing)
{
    long index;
    dictEntry *entry;
    dictht *ht;
    // 如果在 rehash 中，执行一步 rehash 操作（rehash 一个哈希节点，也就是 rehash 一个健值对）
    if (dictIsRehashing(d)) _dictRehashStep(d);

    /* Get the index of the new element, or -1 if
     * the element already exists. */
    // 获取哈希索引：如果在 rehash 中，获取是 ht[1] 哈希表索引，否则是 ht[0] 哈希表索引
    if ((index = _dictKeyIndex(d, key, dictHashKey(d,key), existing)) == -1)
        return NULL;

    /* Allocate the memory and store the new entry.
     * Insert the element in top, with the assumption that in a database
     * system it is more likely that recently added entries are accessed
     * more frequently. */
    // 如果是在 rehash 中，获取 ht[1] 哈希表对象，否则是 ht[0] 哈希表对象
    ht = dictIsRehashing(d) ? &d->ht[1] : &d->ht[0];
    entry = zmalloc(sizeof(*entry));
    // 将新的哈希节点添加到链表头位置
    entry->next = ht->table[index];
    ht->table[index] = entry;
    // 更新哈希表哈希节点数量
    ht->used++;

    /* Set the hash entry fields. */
    dictSetKey(d, entry, key);
    return entry;
}
```
在节点添加之前如果判断当前字典在`rehash`中，会调用`_dictRehashStep`函数，执行一步`rehash`操作（`rehash`一个哈希节点）。
哈希节点的添加有如下两种情况：
+ 如果在 `rehash` 中，会将新节点添加到 `ht[1]` 哈希表；
+ 如果没有在 `rehash` 中，将新节点添加到 `ht[0]` 哈希表；

在哈希表删除操作实现如下：
```c
/* Search and remove an element. This is an helper function for
 * dictDelete() and dictUnlink(), please check the top comment
 * of those functions. */
static dictEntry *dictGenericDelete(dict *d, const void *key, int nofree) {
    uint64_t h, idx;
    dictEntry *he, *prevHe;
    int table;
    // 判断 ht[0] 和 ht[1] 两个哈希表都没有哈希节点，直接返回NULL，表示没有找到
    if (d->ht[0].used == 0 && d->ht[1].used == 0) return NULL;

    // 如果在 rehash 中，执行一步 rehash 操作（rehash 一个哈希节点，也就是 rehash 一个健值对）
    if (dictIsRehashing(d)) _dictRehashStep(d);
    // 计算健 key 的哈希值
    h = dictHashKey(d, key);

    for (table = 0; table <= 1; table++) {
        // 计算当前查找哈希表的索引
        idx = h & d->ht[table].sizemask;
        he = d->ht[table].table[idx];
        prevHe = NULL;
        // 依次查找链表，因为可能存在哈希冲突，在一个索引处有多个哈希节点
        while(he) {
            // 下面的删除操作其实就是从链表中删除一个节点的逻辑
            if (key==he->key || dictCompareKeys(d, key, he->key)) {
                /* Unlink the element from the list */
                if (prevHe)
                    prevHe->next = he->next;
                else
                    // 哈希表索引指向删除元素的下一个哈希节点
                    d->ht[table].table[idx] = he->next;
                if (!nofree) {
                    dictFreeKey(d, he);
                    dictFreeVal(d, he);
                    zfree(he);
                }
                // 更新哈希表哈希节点数量
                d->ht[table].used--;
                return he;
            }
            prevHe = he;
            he = he->next;
        }
        if (!dictIsRehashing(d)) break;
    }
    return NULL; /* not found */
}

/* Remove an element, returning DICT_OK on success or DICT_ERR if the
 * element was not found. */
int dictDelete(dict *ht, const void *key) {
    return dictGenericDelete(ht,key,0) ? DICT_OK : DICT_ERR;
}
```
在节点删除之前如果判断当前字典在`rehash`中，会调用`_dictRehashStep`函数，执行一步`rehash`操作（`rehash`一个哈希节点）。
删除一个哈希节点首先在`ht[0]`哈希表查找，如果在`ht[0]`哈希表没有找到且当前字典在`rehash`中，会继续在`ht[1]`哈希表查找。

在哈希表查找操作如下：
```c
dictEntry *dictFind(dict *d, const void *key)
{
    dictEntry *he;
    uint64_t h, idx, table;

    if (d->ht[0].used + d->ht[1].used == 0) return NULL; /* dict is empty */
    // 如果在 rehash 中，执行一步 rehash 操作（rehash 一个哈希节点，也就是 rehash 一个健值对）
    if (dictIsRehashing(d)) _dictRehashStep(d);
    h = dictHashKey(d, key);
    for (table = 0; table <= 1; table++) {
        idx = h & d->ht[table].sizemask;
        he = d->ht[table].table[idx];
        while(he) {
            if (key==he->key || dictCompareKeys(d, key, he->key))
                return he;
            he = he->next;
        }
        if (!dictIsRehashing(d)) return NULL;
    }
    return NULL;
}
```
在节点查找之前如果判断当前字典在`rehash`中，会调用`_dictRehashStep`函数，执行一步`rehash`操作（`rehash`一个哈希节点）。
查找一个哈希节点首先在`ht[0]`哈希表查找，如果在`ht[0]`哈希表没有找到且当前字典在`rehash`中，会继续在`ht[1]`哈希表查找。


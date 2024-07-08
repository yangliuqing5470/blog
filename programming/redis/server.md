> 基于`redis`源码分支`5.0`
# 服务启动流程
`redis`服务是**事件驱动**模式，基于`IO`多路复用，采样`Reactor`编程模式实现。下面从服务启动的流程来了解`redis`设计思想。
## 数据结构定义
`redis`是`key-value`型数据库，不管是`key`还是`value`，在`redis`中都是`redisObject`对象。`redisObject`对象定义如下：
```c
typedef struct redisObject {
    unsigned type:4;
    unsigned encoding:4;
    unsigned lru:LRU_BITS; /* LRU time (relative to global lru_clock) or
                            * LFU data (least significant 8 bits frequency
                            * and most significant 16 bits access time). */
    int refcount;
    void *ptr;
} robj;
```
+ `type`：表示对象的类型，取值如下：
  ```c
  /* The actual Redis Object */
  #define OBJ_STRING 0    /* String object. */
  #define OBJ_LIST 1      /* List object. */
  #define OBJ_SET 2       /* Set object. */
  #define OBJ_ZSET 3      /* Sorted set object. */
  #define OBJ_HASH 4      /* Hash object. */
  #define OBJ_MODULE 5    /* Module object. */
  #define OBJ_STREAM 6    /* Stream object. */
  ```
+ `encoding`：当前对象底层存储采用的数据结构；对于某种类型对象，在不同的情况下，`redis`使用不同的数据结构，下表给出了`encoding`和`type`之间的关系：
  |encoding取值|数据结构|存储对象类型|
  |------------|--------|------------|
  |`OBJ_ENCODING_RAW`|简单动态字符串(`sds`)|字符串|
  |`OBJ_ENCODING_INT`|整数|字符串|
  |`OBJ_ENCODING_HT`|字典(`dict`)|集合、字典、有序集合|
  |`OBJ_ENCODING_ZIPMAP`|未使用|未使用|
  |`OBJ_ENCODING_LINKEDLIST`|废弃|废弃|
  |`OBJ_ENCODING_ZIPLIST`|压缩列表(`ziplist`)|有序集合、字典|
  |`OBJ_ENCODING_INTSET`|整数集合(`intset`)|集合|
  |`OBJ_ENCODING_SKIPLIST`|跳跃表(`skiplist`)|有序集合|
  |`OBJ_ENCODING_EMBSTR`|简单动态字符串(`sds`)|字符串|
  |`OBJ_ENCODING_QUICKLIST`|快速链表(`quicklist`)|列表|
  |`OBJ_ENCODING_STREAM`|`stream`|`stream`|

  在对象的生命周期内，对象的编码不是固定的。例如集合对象，当集合中元素可用整数表示时，底层数据结构使用整数集合，
  当执行`sadd`命令，会先判断添加的元素能否解析为整数，不能则底层数据结构转为字典：
  ```c
  /* Add the specified value into a set.
   *
   * If the value was already member of the set, nothing is done and 0 is
   * returned, otherwise the new element is added and 1 is returned. */
  int setTypeAdd(robj *subject, sds value) {
      long long llval;
      if (subject->encoding == OBJ_ENCODING_HT) {
          dict *ht = subject->ptr;
          dictEntry *de = dictAddRaw(ht,value,NULL);
          if (de) {
              dictSetKey(ht,de,sdsdup(value));
              dictSetVal(ht,de,NULL);
              return 1;
          }
      } else if (subject->encoding == OBJ_ENCODING_INTSET) {
          if (isSdsRepresentableAsLongLong(value,&llval) == C_OK) {
              uint8_t success = 0;
              subject->ptr = intsetAdd(subject->ptr,llval,&success);
              if (success) {
                  /* Convert to regular set when the intset contains
                   * too many entries. */
                  if (intsetLen(subject->ptr) > server.set_max_intset_entries)
                      setTypeConvert(subject,OBJ_ENCODING_HT);
                  return 1;
              }
          } else {
              /* Failed to get integer from object, convert to regular set. */
              // 编码转换
              setTypeConvert(subject,OBJ_ENCODING_HT);
  
              /* The set *was* an intset and this value is not integer
               * encodable, so dictAdd should always work. */
              serverAssert(dictAdd(subject->ptr,sdsdup(value),NULL) == DICT_OK);
              return 1;
          }
      } else {
          serverPanic("Unknown set encoding");
      }
      return 0;
  }
  ```
  有些对象同时也会使用不同的数据结构存储。例如有序集合对象定义如下：
  ```c
  typedef struct zset {
    dict *dict;
    zskiplist *zsl;
  } zset;
  ```
  同时使用字典和跳跃表存储，字典成员查询时间复杂度为`O(1)`，跳跃表范围查找时间复杂度为`O(logN)`，所以有序集合对象利用了字典和跳跃表的组合优势。
  实际的数据只存储一份，字典和跳跃表存储的都是数据指针，也就是多增加指针开销。
+ `lru`：
+ `refcount`：
+ `ptr`：

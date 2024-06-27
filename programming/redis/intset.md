> 基于`redis`源码分支`5.0`
# 整数集合
整数集合`intset`是集合健的底层实现之一，当一个集合只包含整数值元素，集合的元素数量不多时，`redis`会使用整数集合数据结构作为底层实现。
集合中不会有重复元素。

## 数据结构定义
在`intset.h`中定义了整数集合的数据结构：
```c
typedef struct intset {
    uint32_t encoding;
    uint32_t length;
    int8_t contents[];
} intset;
```
+ `encoding`：编码类型，决定每个元素占用字节数，取值有如下：
  + `INTSET_ENC_INT16`：存储的每个元素都是`int16_t`类型值；
  + `INTSET_ENC_INT32`：存储的每个元素都是`int32_t`类型值；
  + `INTSET_ENC_INT64`：存储的每个元素都是`int64_t`类型值；
+ `length`：存储的元素数量，也就是`contents`数组的长度；
+ `contents`：一个数组，存储元素，根据`encoding`值决定一个元素的数据类型；

## 整数集合创建
创建新的整数集合源码如下：
```c
/* Create an empty intset. */
intset *intsetNew(void) {
    intset *is = zmalloc(sizeof(intset));
    // 根据定义，intrev32ifbe(INTSET_ENC_INT16) 结果是 2
    is->encoding = intrev32ifbe(INTSET_ENC_INT16);
    is->length = 0;
    return is;
}

#define INTSET_ENC_INT16 (sizeof(int16_t))
```
其中`intrev32ifbe`是个宏定义，用于不同平台数据大小端对其。创建整数集合逻辑比较简单，就是分配一个整数集合`intset`对象，
初始化`encoding=2`和`length=0`。

## 整数集合添加
整数集合的添加执行逻辑如下：
+ 判断要添加元素的编码是否大于整数集合的编码`intset->encoding`，如果大于则执行升级流程；
+ 如果插入元素的编码小于整数集合编码`intset->encoding`，则先查找要插入的值是否在集合中已经存在，如果存在不执行插入，操作结束；
+ 如果在整数集合`intset`中不存在要插入的元素，先给整数集合中的数组`contents`分配空间，然后执行插入；

添加元素的源码实现如下：
```c
/* Insert an integer in the intset */
intset *intsetAdd(intset *is, int64_t value, uint8_t *success) {
    // 获取添加元素的编码
    uint8_t valenc = _intsetValueEncoding(value);
    uint32_t pos;
    if (success) *success = 1;

    /* Upgrade encoding if necessary. If we need to upgrade, we know that
     * this value should be either appended (if > 0) or prepended (if < 0),
     * because it lies outside the range of existing values. */
    // 如果添加元素的编码大于整数集合元素的编码，执行升级操作
    if (valenc > intrev32ifbe(is->encoding)) {
        /* This always succeeds, so we don't need to curry *success. */
        return intsetUpgradeAndAdd(is,value);
    } else {
        /* Abort if the value is already present in the set.
         * This call will populate "pos" with the right position to insert
         * the value when it cannot be found. */
        // 先查找要添加元素是否已经在集合中存在，如果存在直接放回
        if (intsetSearch(is,value,&pos)) {
            if (success) *success = 0;
            return is;
        }
        // 给存放元素的数组分配空间
        is = intsetResize(is,intrev32ifbe(is->length)+1);
        if (pos < intrev32ifbe(is->length)) intsetMoveTail(is,pos,pos+1);
    }

    _intsetSet(is,pos,value);
    // 更新集合对象的 length 属性
    is->length = intrev32ifbe(intrev32ifbe(is->length)+1);
    return is;
```
获取元素编码值`_intsetValueEncoding`的实现如下：
```c
/* Return the required encoding for the provided value. */
static uint8_t _intsetValueEncoding(int64_t v) {
    if (v < INT32_MIN || v > INT32_MAX)
        return INTSET_ENC_INT64;
    else if (v < INT16_MIN || v > INT16_MAX)
        return INTSET_ENC_INT32;
    else
        return INTSET_ENC_INT16;
}
```
通过快速判断目标值`v`在哪一个编码范围，并返回对应的编码。

如果插入元素`v`的编码不大于整数集合的编码`encoding`值，则会先查找插入元素`v`是否在整数集合存在，`intsetSearch`的实现如下：
```c
/* Search for the position of "value". Return 1 when the value was found and
 * sets "pos" to the position of the value within the intset. Return 0 when
 * the value is not present in the intset and sets "pos" to the position
 * where "value" can be inserted. */
static uint8_t intsetSearch(intset *is, int64_t value, uint32_t *pos) {
    // min 表示数组 contents 的起始，max 表示数组 contents 的结束
    int min = 0, max = intrev32ifbe(is->length)-1, mid = -1;
    int64_t cur = -1;

    /* The value can never be found when the set is empty */
    // 如何集合为空，也就是元素长度为0，插入位置 pos 值为 0（表示在数组的开始位置插入）
    if (intrev32ifbe(is->length) == 0) {
        if (pos) *pos = 0;
        return 0;
    } else {
        /* Check for the case where we know we cannot find the value,
         * but do know the insert position. */
        // 因为集合是有序的（升序），判断要插入的元素是否在集合范围外，进而快速判断插入位置在开始还是末尾
        if (value > _intsetGet(is,max)) {
            if (pos) *pos = intrev32ifbe(is->length);
            return 0;
        } else if (value < _intsetGet(is,0)) {
            if (pos) *pos = 0;
            return 0;
        }
    }
    // 走到这里说明 contents[min] <= 插入元素值 <= contents[max]
    // 因为 contents 是个有序数组，所以可以通过 二分法查找
    while(max >= min) {
        mid = ((unsigned int)min + (unsigned int)max) >> 1;
        cur = _intsetGet(is,mid);
        if (value > cur) {
            min = mid+1;
        } else if (value < cur) {
            max = mid-1;
        } else {
            break;
        }
    }
    // 在集合中找到了
    if (value == cur) {
        if (pos) *pos = mid;
        return 1;
    } else {
        if (pos) *pos = min;
        return 0;
    }
}
```
因为`contents`是个有序数组，查找使用二分查找。

其中获取整数集合`intset`中某个位置`pos`元素值的实现如下：
```c
/* Return the value at pos, using the configured encoding. */
static int64_t _intsetGet(intset *is, int pos) {
    return _intsetGetEncoded(is,pos,intrev32ifbe(is->encoding));
}

/* Return the value at pos, given an encoding. */
// 获取在位置 pos 处的元素值
static int64_t _intsetGetEncoded(intset *is, int pos, uint8_t enc) {
    int64_t v64;
    int32_t v32;
    int16_t v16;

    if (enc == INTSET_ENC_INT64) {
        memcpy(&v64,((int64_t*)is->contents)+pos,sizeof(v64));
        memrev64ifbe(&v64);
        return v64;
    } else if (enc == INTSET_ENC_INT32) {
        memcpy(&v32,((int32_t*)is->contents)+pos,sizeof(v32));
        memrev32ifbe(&v32);
        return v32;
    } else {
        memcpy(&v16,((int16_t*)is->contents)+pos,sizeof(v16));
        memrev16ifbe(&v16);
        return v16;
    }
}
```
因为`is->contents`数组是个柔性数组，也就是其存储的元素类型不是初始化定义声明的，而是由`is->encoding`指定动态变化的，
所以需要根据不同的`is->encoding`值，从指定内存地址获取元素值。

假如此时`intsetSearch`返回`1`表示集合已经存在要插入的元素，则当前插入操作直接结束。假如`intsetSearch`返回`0`，表示集合不存在要插入的元素，
此时`pos`值就是要在集合中`contents`数组插入的位置。下面流程会给集合中存放元素的数组`contents`分配空间：
```c
is = intsetResize(is,intrev32ifbe(is->length)+1);
```
`intsetResize`的源码如下：
```c
/* Resize the intset */
static intset *intsetResize(intset *is, uint32_t len) {
    uint32_t size = len*intrev32ifbe(is->encoding);
    is = zrealloc(is,sizeof(intset)+size);
    return is;
}
```
通过调用`zrealloc`分配指定大小的内存。

由于整数集合中存放元素的数据结构是数组（`contents`属性是数组）， 空间分配完成后，会判断插入的位置是否小于数组末尾位置。
+ 如果插入的位置小于数组末尾位置，需要将数组中在插入位置以及之后的元素都往后移动一个位置：
  ```c
  if (pos < intrev32ifbe(is->length)) intsetMoveTail(is,pos,pos+1);

  static void intsetMoveTail(intset *is, uint32_t from, uint32_t to) {
    void *src, *dst;
    // bytes 是位置 from 之后（包括 from 位置）元素个数
    uint32_t bytes = intrev32ifbe(is->length)-from;
    uint32_t encoding = intrev32ifbe(is->encoding);

    if (encoding == INTSET_ENC_INT64) {
        src = (int64_t*)is->contents+from;
        dst = (int64_t*)is->contents+to;
        // 计算要移动的字节数
        bytes *= sizeof(int64_t);
    } else if (encoding == INTSET_ENC_INT32) {
        src = (int32_t*)is->contents+from;
        dst = (int32_t*)is->contents+to;
        bytes *= sizeof(int32_t);
    } else {
        src = (int16_t*)is->contents+from;
        dst = (int16_t*)is->contents+to;
        bytes *= sizeof(int16_t);
    }
    memmove(dst,src,bytes);
  }
  ```
  + `src`：表示要移动元素的源地址；
  + `dst`：表示要移动元素的目的地址
  + `bytes`：最后传递给`memmove`的值表示要移动总的字节数；
+ 如果插入的位置在数组的末尾，直接插入即可；

元素的插入实现如下：
```bash
_intsetSet(is,pos,value);

/* Set the value at pos, using the configured encoding. */
static void _intsetSet(intset *is, int pos, int64_t value) {
    uint32_t encoding = intrev32ifbe(is->encoding);

    if (encoding == INTSET_ENC_INT64) {
        ((int64_t*)is->contents)[pos] = value;
        // 统一为小端编码
        memrev64ifbe(((int64_t*)is->contents)+pos);
    } else if (encoding == INTSET_ENC_INT32) {
        ((int32_t*)is->contents)[pos] = value;
        memrev32ifbe(((int32_t*)is->contents)+pos);
    } else {
        ((int16_t*)is->contents)[pos] = value;
        memrev16ifbe(((int16_t*)is->contents)+pos);
    }
}
```

最后我们看下如果插入元素`v`的编码大于整数集合的编码`encoding`值，需要升级的流程：
```c
if (valenc > intrev32ifbe(is->encoding)) {
        /* This always succeeds, so we don't need to curry *success. */
        return intsetUpgradeAndAdd(is,value);
```
如果需要升级，则可以判定插入的元素`v`要么插入在集合中数组的起始位置（`v`是负数），要么插入在集合中数组的末尾（`v`是个正数）。
`intsetUpgradeAndAdd`的源码实现如下：
```c
/* Upgrades the intset to a larger encoding and inserts the given integer. */
static intset *intsetUpgradeAndAdd(intset *is, int64_t value) {
    // 集合的编码值
    uint8_t curenc = intrev32ifbe(is->encoding);
    // 插入值的编码值
    uint8_t newenc = _intsetValueEncoding(value);
    // 集合原有长度
    int length = intrev32ifbe(is->length);
    int prepend = value < 0 ? 1 : 0;

    /* First set new encoding and resize */
    // 更新集合的编码值为插入元素的编码值，向上升级
    is->encoding = intrev32ifbe(newenc);
    // 根据新编码值以及插入后集合元素个数，从新给集合分配空间
    is = intsetResize(is,intrev32ifbe(is->length)+1);

    /* Upgrade back-to-front so we don't overwrite values.
     * Note that the "prepend" variable is used to make sure we have an empty
     * space at either the beginning or the end of the intset. */
    // 将集合中数组原有元素重新根据新的数据类型存放在新分配的数组中
    while(length--)
        _intsetSet(is,length+prepend,_intsetGetEncoded(is,length,curenc));

    /* Set the value at the beginning or the end. */
    // 插入元素放在数组的首或者尾
    if (prepend)
        _intsetSet(is,0,value);
    else
        _intsetSet(is,intrev32ifbe(is->length),value);
    // 更新集合的大小
    is->length = intrev32ifbe(intrev32ifbe(is->length)+1);
    return is;
}
```
升级的流程可以总结如下：
+ 更新集合的编码；
+ 给集合中存放元素的数据根据新的编码（数据类型）及新的集合长度分配空间；
+ 将集合中原有元素根据新的元素类型重新存放到新分配的数组中；
+ 根据新元素是大于`0`还是小于`0`，将新元素存在在数组的尾或者首位置；
+ 更新集合的长度；

## 整数集合查找
整数集合的查找需要满足以下两个条件才可以说明集合中包含要查找的元素：
+ 查找值的编码（数据类型）小于等于集合的编码`encoding`值;
+ 在集合中存在要查找的元素；

查找的源码实现如下：
```c
/* Determine whether a value belongs to this set */
uint8_t intsetFind(intset *is, int64_t value) {
    // 获取查找值的编码
    uint8_t valenc = _intsetValueEncoding(value);
    return valenc <= intrev32ifbe(is->encoding) && intsetSearch(is,value,NULL);
}
```
查找逻辑有个效率优化：先判断查找元素的编码值（数据类型）是否小于等于集合的编码值`encoding`，只有满足此条件才会进行实际的遍历数组查找。
在`intsetSearch`内部（参考上面插入小节介绍）使用二分查找，查找效率高。

## 整数集合删除
删除一个元素的逻辑分为三部分：
+ 查找要删除的元素，没有找到直接返回，找到要删除的元素执行下一步；
+ 将删除元素后面的元素往前移动一个位置，重新分配集合中数组`contents`大小，也就是会释放数组最后的空元素内存；
+ 更新集合的长度；

删除的源码实现如下：
```c
/* Delete integer from intset */
intset *intsetRemove(intset *is, int64_t value, int *success) {
    // 获取删除元素的编码值
    uint8_t valenc = _intsetValueEncoding(value);
    uint32_t pos;
    if (success) *success = 0;
    // 先在集合中查找要删除的元素
    if (valenc <= intrev32ifbe(is->encoding) && intsetSearch(is,value,&pos)) {
        uint32_t len = intrev32ifbe(is->length);

        /* We know we can delete */
        if (success) *success = 1;

        /* Overwrite value with tail and update length */
        // 将删除元素后面的元素往前移动一位
        if (pos < (len-1)) intsetMoveTail(is,pos+1,pos);
        // 释放集合中数组尾部的空闲空间
        is = intsetResize(is,len-1);
        // 更新集合的长度
        is->length = intrev32ifbe(len-1);
    }
    return is;
}
```

> 基于resis源码分支5.0
# 链表
在`adlist.h`中，链表节点的定义如下：
```c
typedef struct listNode {
    struct listNode *prev;
    struct listNode *next;
    void *value;
} listNode;
```
使用多个`listNode`可以组成双端链表。`redis`也定义了如下链表数据结构：
```c
typedef struct list {
    listNode *head;
    listNode *tail;
    void *(*dup)(void *ptr);
    void (*free)(void *ptr);
    int (*match)(void *ptr, void *key);
    unsigned long len;
} list;
```
其中`list`结构各个字段含义如下：
+ `head`：链表的头指针；
+ `tail`：链表的尾指针；
+ `len`：链表的长度，即链表中节点的个数；
+ `dup`：复制链表节点的值；
+ `free`：释放链表节点的值；
+ `match`：对比链表节点值和另一个值是否相等；

其中`dup`、`free`和`match`需要显示设置，`redis`提供了如下的宏定义支持设置`list`结构元素：
```c
/* Functions implemented as macros */
#define listLength(l) ((l)->len)
#define listFirst(l) ((l)->head)
#define listLast(l) ((l)->tail)
#define listPrevNode(n) ((n)->prev)
#define listNextNode(n) ((n)->next)
#define listNodeValue(n) ((n)->value)

#define listSetDupMethod(l,m) ((l)->dup = (m))
#define listSetFreeMethod(l,m) ((l)->free = (m))
#define listSetMatchMethod(l,m) ((l)->match = (m))

#define listGetDupMethod(l) ((l)->dup)
#define listGetFree(l) ((l)->free)
#define listGetMatchMethod(l) ((l)->match)
```
`redis`实现的链表具有如下特点：
+ 双端链表：链表节点有`pre`和`next`指针，可以获取当前节点前置和后置节点，时间复杂度`O(1)`；
+ 无环：`list`的`head`节点的`prev`指针和`tail`节点的`next`指针都是`null`；
+ 链表长度计数器：`list`结构有`len`属性，记录链表节点数，所以可以`O(1)`时间获取链表节点数；
+ 链表头尾指针：`list`结构有`head`和`tail`指针，分别指向链表头节点和尾节点，所以可以`O(1)`时间获取链表头尾指针；
+ 多态值：链表节点的值`value`是`void*`类型，可以保存任意类型数据，并可通过`list`的`dup`、`free`和`match`属性设置每个节点的特定的函数；

`resis`也提供了`listIter`链表迭代器用于遍历链表，结构如下：
```c
typedef struct listIter {
    listNode *next;
    int direction;
} listIter;
```
+ `next`：指向链表中下一个节点的指针；
+ `direction`：迭代器遍历的方向，取值`AL_START_HEAD`表示从链表头开始，取值`AL_START_TAIL`表示从链表尾开始；

下面给出使用迭代器`listNext`实现：
```c
/* Return the next element of an iterator.
 * It's valid to remove the currently returned element using
 * listDelNode(), but not to remove other elements.
 *
 * The function returns a pointer to the next element of the list,
 * or NULL if there are no more elements, so the classical usage patter
 * is:
 *
 * iter = listGetIterator(list,<direction>);
 * while ((node = listNext(iter)) != NULL) {
 *     doSomethingWith(listNodeValue(node));
 * }
 *
 * */
listNode *listNext(listIter *iter)
{   
    // 迭代器当前指向的节点
    listNode *current = iter->next;
    // 更新迭代器指向下一个节点
    if (current != NULL) {
        if (iter->direction == AL_START_HEAD)
            iter->next = current->next;
        else
            iter->next = current->prev;
    }
    return current;
}
```

# yield & send & throw & close
## yield
`yield`用来制造生成器，包含`yield`的函数是生成器；<br>
`yield`语法规则:
- 在`yield`处暂停函数执行；
- 当`next`函数被调用时候，`next`函数返回值是`yield`后面表达式值(默认None)，并
从上次暂停处的`yield`处开始执行，直到遇到下一个`yield`；
- 当不能继续`next`时候，会抛出异常；

```python
>>> def yield_example(n):
...     a, b = 0, 1
...     for _ in range(n):
...         yield b
...         a, b = b, a + b
...
>>> gen = yield_example(5)
>>> gen  # 一个生成器
<generator object yield_example at 0x7f26336bd2e0>
>>> next(gen)
1
>>> next(gen)
1
>>> next(gen)
2
>>> next(gen)
3
>>> next(gen)
5
>>> next(gen)
Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
StopIteration
```
## send
生成器可以调用`send`方法，为内部的`yield`语句发送数据；此时的`yield`语句可以是`var = yield <expression>`形式，
该形式具有如下两个功能:
- 暂停函数执行；
- `send`函数返回值是`yield`后面表达式的值；
- 接收外部`send`方法发送的值，重新激活函数，并将发送的值赋值给 var 变量；

```python
>>> def simple_coroutine():
...     print("Start coroutine ---")
...     y = 10
...     x = yield y
...     print("Coroutine get x value: ", x)
...
>>> my_coro = simple_coroutine()
>>> my_coro
<generator object simple_coroutine at 0x7f7c66b08a50>
>>> ret = next(my_coro)
Start coroutine ---
>>> print(ret)
10
>>> my_coro.send(100)
Coroutine get x value:  100
Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
StopIteration
```
生成器有四个状态，当前状态可以使用`inspect.getgeneratorstate`函数查看
- `GEN_CREATED`: 等待开始执行；
- `GEN_RUNNING`: 正在执行；
- `GEN_SUSPENDED`: 在`yield`处暂停；
- `GEN_CLOSED`: 执行结束;

```python
>>> def simple_coroutine():
...     print("Start coroutine ---")
...     y = 10
...     x = yield y
...     print("Coroutine get x value: ", x)
...
>>> my_coro = simple_coroutine()
>>> import inspect
>>> inspect.getgeneratorstate(my_coro)
'GEN_CREATED'
>>> next(my_coro)
Start coroutine ---
10
>>> inspect.getgeneratorstate(my_coro)
'GEN_SUSPENDED'
>>> my_coro.send(100)
Coroutine get x value:  100
Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
StopIteration
>>> inspect.getgeneratorstate(my_coro)
'GEN_CLOSED'
```
`send`函数方法参数会成为暂停`yield`表达式的值，只有当协程处于暂停状态才可以调用`send`函数；
如果生成器还未被激活(状态是`GEN_CREATED`)，把`None`之外的值发给它，会抛出异常。
```python
>>> def simple_coroutine():
...     print("Start coroutine ---")
...     y = 10
...     x = yield y
...     print("Coroutine get x value: ", x)
...
>>> inspect.getgeneratorstate(my_coro)
'GEN_CLOSED'
>>> my_coro = simple_coroutine()
>>> inspect.getgeneratorstate(my_coro)
'GEN_CREATED'
>>> my_coro.send(10)
Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
TypeError: can't send non-None value to a just-started generator
```
使用生成器之前需要先激活协程，使用`next(my_coro)`或者`my_coro.send(None)`。

## throw
使生成器在暂停的`yield`表达式处抛出指定的异常
- 如果生成器处理了异常，代码会向前执行到下一个`yield`表达式，`yield`后面表达式值为`throw`函数的返回值
- 如果生成器没有处理异常，异常会传递到调用方

```python
# 生成器没有捕获异常
>>> def simple_coroutine():
...     print("Start coroutine ---")
...     y = 10
...     x = yield y
...     print("Coroutine get x value: ", x)
...
>>> my_coro = simple_coroutine()
>>> my_coro.send(None)
Start coroutine ---
10
>>> my_coro.throw(Exception, "Need exit")
Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
  File "<stdin>", line 4, in simple_coroutine
Exception: Need exit

# 生成器捕获异常
>>> def simple_coroutine():
...     print("Start coroutine ---")
...     x = 10
...     try:
...         y = yield x
...     except:
...         y = yield 100
...     print("Start coroutine ---")
...
>>>
>>> my_coro = simple_coroutine()
>>> my_coro
<generator object simple_coroutine at 0x7f7c6563dcf0>
>>> my_coro.send(None)
Start coroutine ---
10
>>> my_coro.throw(Exception, "Need exit")
100
>>> next(my_coro)
Start coroutine ---
Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
StopIteration
```

## close
使生成器在暂停的`yield`处抛出`GeneratorExit`异常
- 如果生成器不捕获此异常或者捕获异常但后面生成器抛出`StopIteration`异常，`close`方法不传递该异常(调用方不会报错)
- `GeneratorExit`异常说明生成器对象生命周期已经结束，因此生成器函数后面语句不能在有`yield`，否则
会产生`RuntimeError`(和throw函数行为不同)
- 对于已经退出的生成器，`close`函数不进行任何操作
- `GeneratorExit`异常只有在生成器对象被激活后才会产生，没有激活的生成器调`close`函数不会触发`GeneratorExit`

```python
# 生成器不捕获异常
>>> def my_gen():
...     print("Start generator ---")
...     yield 1
...     print("Exect first yield success")
...     yield 2
...     print("End genetator ---")
...
>>> g = my_gen()
>>> g
<generator object my_gen at 0x7f7c6565e900>
>>> next(g) # 对已经关闭的生成器调用 next 会抛出 StopIteration
Start generator ---
1
>>> g.close()
>>> next(g)
Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
StopIteration
```
```python
# 生成器捕获异常并自然退出
>>> def my_gen():
...     print("Start ---")
...     try:
...         yield 1
...     except GeneratorExit:
...         print("Get GenneratorExit")
...     print("End ---")
...
>>>
>>> g = my_gen()
>>> g
<generator object my_gen at 0x7f7c65679e40>
>>> next(g)
Start ---
1
>>> g.close()
Get GenneratorExit
End ---
```
```python
# 捕获异常 GeneratorExit 但后面还有 yield 语句
>>> def my_gen():
...     print("Start ---")
...     try:
...         yield 1
...     except GeneratorExit:
...         print("Get GenneratorExit")
...         yield 2  # 异常后还有 yield
...     print("End ---")
...
>>> g = my_gen()
>>> g
<generator object my_gen at 0x7f7c6565e900>
>>> next(g)
Start ---
1
>>> g.close()
Get GenneratorExit
Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
RuntimeError: generator ignored GeneratorExit

# 不抛出异常 RuntimeError 一种写法
>>> def safegen():
...     print("Start ---")
...     closed = False
...     try:
...         yield 1
...     except GeneratorExit:
...         closed = True
...         print("Get GeneratorExit")
...         raise
...     finally:
...         if not closed:
...             yield 2
...
>>> g = safegen()
>>> g
<generator object safegen at 0x7f7c6565e900>
>>> next(g)
Start ---
1
>>> g.close()
Get GeneratorExit
```

# yield from & @asyncio.coroutine
## yield from
`yield from x`对 x 对象做的第一件事是调用`iter(x)`获取迭代器，因此 x 可以是任何可迭代对象；<br>
`yield from`的主要功能是打开双向通道，把最外层的调用方与最内层的子生成器连接起来，二者可以直接发送和
产出值，还可以直接传入异常；相关术语如下：
- 委派生成器：包含`yield from <iterable>`表达式的**生成器函数**
- 子生成器：从表达式`<iterable>`获取的生成器

`yield from`语法功能：
- `yield from <iterable>`会等子生成器(<iterable>)结束，如果子生成器不终止，则`yield from`会永远暂停；
- `yield from`表达式的值是子生成器终止时传给`StopIteration`异常的第一个参数；

**生成器退出时，会触发`StopIteration`异常** <br>
```python
from collections import namedtuple
Result = namedtuple("Result", "count average")

# 子生成器
def average():
    total = 0.0
    count = 0
    average = None
    while True:
        term = yield
        if term is None:
            break
        total += term
        count += 1
        average = total / count
    return Result(count, average)

# 委派生成器
def grouper(result, key):
    while True:
        print("Start one grouper")
        result[key] = yield from average()

# 调用方(驱动方)
def main(data):
    result = {}
    for key, values in data.items():
        group = grouper(result, key)
        next(group)
        for value in values:
            group.send(value)
        group.send(None)  # 重要
    print(result)

data = {
    "boys;kg": [39.0, 40.8, 28.2],
    "girls:kg": [30.2, 26.3, 27.9]
}

if __name__ == "__main__":
    main(data)

----------------------------------
➜  Workspace python3 test_run.py
Start one grouper
Start one grouper
Start one grouper
Start one grouper
{'boys;kg': Result(count=3, average=36.0), 'girls:kg': Result(count=3, average=28.133333333333336)}
# 注释调 main 函数中 group.send(None)
➜  Workspace python3 test_run.py
Start one grouper
Start one grouper
{}
```

`yield from`与异常和终止有关的行为
- 传入委派生成器的异常，除了`GeneratorExit`异常(close函数抛出)，其他都传给子生成器的`throw`函数；如果子生成器调用`throw`抛出`StopIteration`异常(生成器正常退出)，委派生成器
恢复运行，`StopIteration`之外的其它异常会传给委派生成器
- 如果将`GeneratorExit`异常传入委派生成器，或者在委派生成器中调用`close`函数，那么在子生成器上调用`close`函数(如果有的话)，若`close`函数导致异常抛出，则会传给委派生成器；
若子生成器调用`close`函数不抛出异常(被捕获)，那么委派生成器抛出`GeneratorExit`异常

```python
# 子生成器捕获异常并正常退出(抛出 StopIteration 异常) -- 委托生成器恢复运行
from collections import namedtuple

Result = namedtuple("Result", "count average")

# 子生成器--捕获异常
def average():
    total = 0.0
    count = 0
    average = None
    while True:
        # term = yield "test"   # 不捕获异常
        try:
            term = yield "test" # 捕获异常
        except:
            print("Catch throw exception.")
            term = None
        if term is None:
            break
        total += term
        count += 1
        average = total / count
    return Result(count, average)

# 委派生成器
def grouper(result, key):
    while True:
        print("Start one grouper")
        result[key] = yield from average()

# 调用throw抛出异常的驱动方
def main_throw(data):
    result = {}
    for key, _ in data.items():
        group = grouper(result, key)
        next(group)
        res = group.throw(Exception, "Need Exit.")
        print(res)
        break
    print("main end")

data = {
    "boys;kg": [39.0, 40.8, 28.2],
    "girls:kg": [30.2, 26.3, 27.9]
}

if __name__ == "__main__":
    main_throw(data)

-------------------------------------------
➜  Workspace python3 test_run.py
Start one grouper
Catch throw exception.
Start one grouper
test
main end
Catch throw exception.  # 这里是python垃圾回收子生成器输出的
-------------------------------------------

# 子生成器不捕获异常--异常向上传递
➜  Workspace python3 test_run.py
Start one grouper
Traceback (most recent call last):
  File "test_run.py", line 42, in <module>
    main_throw(data)
  File "test_run.py", line 31, in main_throw
    res = group.throw(Exception, "Need Exit.")
  File "test_run.py", line 23, in grouper
    result[key] = yield from average()
  File "test_run.py", line 11, in average
    term = yield "test"
Exception: Need Exit.
```
```python
# 子生成器不捕获close函数抛出的异常
from collections import namedtuple
Result = namedtuple("Result", "count average")

# 子生成器--不捕获异常
def average():
    total = 0.0
    count = 0
    average = None
    while True:
        term = yield "test"
        if term is None:
            break
        total += term
        count += 1
        average = total / count
    return Result(count, average)

# 委派生成器
def grouper(result, key):
    while True:
        print("Start one grouper")
        result[key] = yield from average()

# 调用close抛出异常的驱动方
def main_close(data):
    result = {}
    for key, _ in data.items():
        group = grouper(result, key)
        next(group)
        group.close()  # 传入 GeeneratorExit 异常给委派生成器
        break
    print("main end")

data = {
    "boys;kg": [39.0, 40.8, 28.2],
    "girls:kg": [30.2, 26.3, 27.9]
}

if __name__ == "__main__":
    main_close(data)

----------------------------------------
➜  Workspace python3 test_run.py
Start one grouper
main end
---------------------------------------
# 子生成器捕获close的异常
➜  Workspace python3 test_run.py
Start one grouper
Get GeneratorExit
main end
```

## @asyncio.coroutine
`@asyncio.coroutine`装饰的函数显示被声明是一个协程(本质上是一个生成器对象) <br>
直接调用协程不会执行，而是返回一个协程对象，需要通过外部`send`函数驱动执行 <br>
```python
>>> @asyncio.coroutine
... def fun():
...     print("hello")
... 
<stdin>:2: DeprecationWarning: "@coroutine" decorator is deprecated since Python 3.8, use "async def" instead
>>> a = fun()
>>> a
<generator object fun at 0x7f4646fb8ba0>
>>> a.send(None)
hello
Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
StopIteration
```
**目前介绍的协程相关都是基于生成器实现(`send`, `yield from`用来增强生成器，便于更好实现协程)**

# async & await
`async`代替`@asyncio.coroutine`，`await`代替`yield from`，从语法上与生成器的 `yield` 语法彻底区分开来，从各个方面将协程与生成器进行了区分。
`await`后面对象可以是一个**协程**或者实现`__await__`方法的**可等待对象**。例如 asyncio 库实现的 Future 就是一个可等待对象，
其实现的`__await__`源码如下：
```python
def __await__(self):
    if not self.done():
        self._asyncio_future_blocking = True
        yield self  # This tells Task to wait for completion.
    if not self.done():
        raise RuntimeError("await wasn't used with future")
    return self.result()  # May raise too.
```
通过一个例子看下`async/await`的使用：
```python
import asyncio

async def fun():
    loop = asyncio.get_event_loop()
    # 创建一个 Future 可等待对象
    fut = loop.create_future()
    print("fut: ", fut)
    res = await fut
    # res = await run()
    print("res: ", res)
    return res

async def run():
    # 一个直接 return 的协程
    return "hello"

def main():
    coro = fun()
    print(coro)
    # 开始驱动协程运行
    coro_res = coro.send(None)
    print("coro_res: ", coro_res)
    # 下面三行针对 await fut，如果是 await run 则注释掉
    coro_res.set_result("world")
    # 继续驱动协程运行
    coro_res = coro.send(None)
    print("main end")


if __name__ == "__main__":
    main()
```
执行结果如下：
```bash
# await fut
$ python3 test.py
<coroutine object fun at 0x7fb59c2de840>
fut:  <Future pending>
# 第一次驱动运行结果，返回结果是创建的 Future 对象（根据 Future 实现的 __await__ 源码知，第一次驱动执行到
# yield self， 所以 coro.send(None) 的结果就是 self，也即是创建的  Future 对象）
coro_res:  <Future pending>
# 第二次驱动运行结果
res:  world
Traceback (most recent call last):
  File "test.py", line 27, in <module>
    main()
  File "test.py", line 22, in main
    coro_res = coro.send(None)
StopIteration: world

# await run()
$ python3 test.py
<coroutine object fun at 0x7fa16c2de8c0>
fut:  <Future pending>
# 第一次驱动执行结果，由于协程 run() 直接 return，所以这里就直接结束
res:  hello
Traceback (most recent call last):
  File "test.py", line 27, in <module>
    main()
  File "test.py", line 18, in main
    coro_res = coro.send(None)
StopIteration: hello
```

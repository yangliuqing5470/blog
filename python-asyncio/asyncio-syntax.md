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

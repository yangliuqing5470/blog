# Future

异步编程执行结果通知有多种实现方案，例如:
+ 基于回调参数(Callback argument)
+ 返回一个占位符(Return a placeholder (**Future**))
+ 基于队列(Deliver to a queue)
+ 基于回调注册(Callback registry (e.g. POSIX signals))

`Future` 表示一个未来的结果，在任务刚提交开始执行的时候(主线程的工作)，这个结果是空的，等任务异步(例如通过子线程)执行完后，子线程会将任务执行结果填充这个 `Future`，这样主线程可以通过 `Future` 获取结果。可以将 `Future` 看成是主线程和子线程通信的媒介。

![](https://github.com/yangliuqing5470/blog/tree/master/python-futures/images/python-futures/image-20221007132036991.png)

在 python 中的 concurrent.futures 库中 `Future` 的实现主要包含如下功能

## 查询状态

可以查询 `Future` 对象是否被取消，是否在运行中或者是否已经完成，源码如下

```python
def cancelled(self):
    """Return True if the future was cancelled."""
    with self._condition:  # 获取条件变量的锁
        return self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]

def running(self):
    """Return True if the future is currently executing."""
    with self._condition:
        return self._state == RUNNING

def done(self):
    """Return True of the future was cancelled or finished executing."""
    with self._condition:
        return self._state in [CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED]
```

## 获取结果

获取 `Future` 对象的结果或者异常。如果 `Future` 对象的状态不是终态(已完成或者被取消)，则对方法 `result` 和 `exception` 的调用会阻塞在条件变量上，直到另一个线程唤醒此条件变量或者超时，源码如下

```python
def result(self, timeout=None):
    """Return the result of the call that the future represents.

    Args:
        timeout: The number of seconds to wait for the result if the future
            isn't done. If None, then there is no limit on the wait time.

    Returns:
        The result of the call that the future represents.

    Raises:
        CancelledError: If the future was cancelled.
        TimeoutError: If the future didn't finish executing before the given
            timeout.
        Exception: If the call raised then that exception will be raised.
    """
    with self._condition:
        if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
            raise CancelledError()
        elif self._state == FINISHED:
            return self.__get_result()
        # wait方法: 先释放条件变量底层锁对象，然后等待条件发生，
        # 最后返回(成功或者失败)重新获取条件变量底层锁
        self._condition.wait(timeout)

        if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
            raise CancelledError()
        elif self._state == FINISHED:
            return self.__get_result()
        else:
            raise TimeoutError()

def exception(self, timeout=None):
    """Return the exception raised by the call that the future represents.

    Args:
        timeout: The number of seconds to wait for the exception if the
            future isn't done. If None, then there is no limit on the wait
            time.

    Returns:
        The exception raised by the call that the future represents or None
        if the call completed without raising.

    Raises:
        CancelledError: If the future was cancelled.
        TimeoutError: If the future didn't finish executing before the given
            timeout.
    """

    with self._condition:
        if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
            raise CancelledError()
        elif self._state == FINISHED:
            return self._exception

        self._condition.wait(timeout)

        if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
            raise CancelledError()
        elif self._state == FINISHED:
            return self._exception
        else:
            raise TimeoutError()
```

## 更新结果

填充 `Future` 的结果或者异常，源码如下

```python
def set_result(self, result):
    """Sets the return value of work associated with the future.

    Should only be used by Executor implementations and unit tests.
    """
    with self._condition:
        if self._state in {CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED}:
            raise InvalidStateError('{}: {!r}'.format(self._state, self))
        self._result = result
        self._state = FINISHED
        for waiter in self._waiters:
            waiter.add_result(self)
        # 唤醒等待此条件变量的其他所有线程
        self._condition.notify_all()
    self._invoke_callbacks()

def set_exception(self, exception):
    """Sets the result of the future as being the given exception.

    Should only be used by Executor implementations and unit tests.
    """
    with self._condition:
        if self._state in {CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED}:
            raise InvalidStateError('{}: {!r}'.format(self._state, self))
        self._exception = exception
        self._state = FINISHED
        for waiter in self._waiters:
            waiter.add_exception(self)
        self._condition.notify_all()
    self._invoke_callbacks()
```

## 任务取消

取消一个 `Future`，只是更改 `Future` 的状态，不影响一个子线程已经在运行的任务，这种情况还是会等待此任务执行完，源码如下

```python
def cancel(self):
    """Cancel the future if possible.

    Returns True if the future was cancelled, False otherwise. A future
    cannot be cancelled if it is running or has already completed.
    """
    with self._condition:
        if self._state in [RUNNING, FINISHED]:
            return False

        if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]:
            return True

        self._state = CANCELLED
        self._condition.notify_all()

    self._invoke_callbacks()
    return True
```

## 添加回调

当 `Future` 完成的时候，此添加的回调会被调用，回调函数的参数只有一个，就是 `Future` 实例，源码如下

```python
def add_done_callback(self, fn):
    """Attaches a callable that will be called when the future finishes.

    Args:
        fn: A callable that will be called with this future as its only
            argument when the future completes or is cancelled. The callable
            will always be called by a thread in the same process in which
            it was added. If the future has already completed or been
            cancelled then the callable will be called immediately. These
            callables are called in the order that they were added.
    """
    with self._condition:
        if self._state not in [CANCELLED, CANCELLED_AND_NOTIFIED, FINISHED]:
            self._done_callbacks.append(fn)
            return
    try:
        fn(self)
    except Exception:
        LOGGER.exception('exception calling callback for %r', self)
```

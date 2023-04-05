# 相关知识

## Python序列化与反序列化

序列化的时候方法`__getstate__`方法被调用(可以记录哪些信息需要序列化，把不能序列化的属性排除掉)，反序列化的时候`__setstate__`被调用(参数是`__getstate__`方法的返回值)。

```python
import multiprocessing as mp
import threading
import time
import os


class MyQueue():
    def __init__(self):
        self.queue = []
        self.lock = threading.Lock() # 不可序列化
        self.test = 2

    def put(self, obj):
        self.queue.append(obj)

    def get(self):
        return self.queue.pop(0)

    def __getstate__(self):
        return self.queue, self.test

    def __setstate__(self, state):
        self.queue, self.test = state


def child_fun(arg):
    print("Child process get attribute {0} with pid {1}".format(arg.__dict__, os.getpid()))
    arg.put("Value from child process")
    print("Child put value success with queue len ", len(arg.queue))

def main():
    my_queue = MyQueue()
    p = mp.Process(target=child_fun, args=(my_queue,))
    p.start()
    my_queue.put("Value2 from parent process.")
    time.sleep(1)
    print("Parent process get value: {0}".format(my_queue.get()))

if __name__ == "__main__":
    main()
    
-------------------------------------------------------------------------------
# 参数通过序列化传给子进程，由于重写了序列化的两个方法，所以拿到的参数对象属性只有两个，没有lock对象.
Child process get attribute {'queue': [], 'test': 2} with pid 42099
Child put value success with queue len  1
Parent process get value: Value2 from parent process.
```

默认对象不实现`__setstate__`和`__getstate__`方法的时候，序列化的时候，自动保存和加载对象的`__dict__`属性字典。在上面的例子中，也就是

```python
my_queue = MyQueue()
print(my_queue.__dict__)
----------------------------------------------------------------------------------
{'queue': [], 'lock': <unlocked _thread.lock object at 0x7fc871bca150>, 'test': 2}
```

由于有lock属性存在，默认情况 MyQueue 是不可序列化的；如果需要对象 MyQueue 可序列化，需要重写`__setstate__`和`__getstate__`方法，排出掉不可序列化的 lock 属性。

## 多进程共享安全队列

`Multiprocessing.Queue`实现原理如下

<img src="../images/python-futures/image-20221019224239247.png" alt="image-20221019224239247" style="zoom:50%;" />

实现源码如下

```python
class Queue(object):

    def __init__(self, maxsize=0, *, ctx):
        if maxsize <= 0:
            # Can raise ImportError (see issues #3770 and #23400)
            from .synchronize import SEM_VALUE_MAX as maxsize
        self._maxsize = maxsize
        self._reader, self._writer = connection.Pipe(duplex=False)
        self._rlock = ctx.Lock()
        self._opid = os.getpid()
        if sys.platform == 'win32':
            self._wlock = None
        else:
            self._wlock = ctx.Lock()
        self._sem = ctx.BoundedSemaphore(maxsize)
        # For use by concurrent.futures
        self._ignore_epipe = False

        self._after_fork()

        if sys.platform != 'win32':
            register_after_fork(self, Queue._after_fork)

    def __getstate__(self):
        context.assert_spawning(self)
        return (self._ignore_epipe, self._maxsize, self._reader, self._writer,
                self._rlock, self._wlock, self._sem, self._opid)

    def __setstate__(self, state):
        (self._ignore_epipe, self._maxsize, self._reader, self._writer,
         self._rlock, self._wlock, self._sem, self._opid) = state
        self._after_fork()

    def _after_fork(self):
        debug('Queue._after_fork()')
        self._notempty = threading.Condition(threading.Lock())
        self._buffer = collections.deque()
        self._thread = None
        self._jointhread = None
        self._joincancelled = False
        self._closed = False
        self._close = None
        self._send_bytes = self._writer.send_bytes
        self._recv_bytes = self._reader.recv_bytes
        self._poll = self._reader.poll

    def put(self, obj, block=True, timeout=None):
        if self._closed:
            raise ValueError(f"Queue {self!r} is closed")
        if not self._sem.acquire(block, timeout):
            raise Full

        with self._notempty:
            if self._thread is None:
                self._start_thread()
            self._buffer.append(obj)
            self._notempty.notify()

    def get(self, block=True, timeout=None):
        if self._closed:
            raise ValueError(f"Queue {self!r} is closed")
        if block and timeout is None:
            with self._rlock:
                res = self._recv_bytes()
            self._sem.release()
        else:
            if block:
                deadline = time.monotonic() + timeout
            if not self._rlock.acquire(block, timeout):
                raise Empty
            try:
                if block:
                    timeout = deadline - time.monotonic()
                    if not self._poll(timeout):
                        raise Empty
                elif not self._poll():
                    raise Empty
                res = self._recv_bytes()
                self._sem.release()
            finally:
                self._rlock.release()
        # unserialize the data after having released the lock
        return _ForkingPickler.loads(res)

    def qsize(self):
        # Raises NotImplementedError on Mac OSX because of broken sem_getvalue()
        return self._maxsize - self._sem._semlock._get_value()

    def empty(self):
        return not self._poll()

    def full(self):
        return self._sem._semlock._is_zero()

    def get_nowait(self):
        return self.get(False)

    def put_nowait(self, obj):
        return self.put(obj, False)

    def close(self):
        self._closed = True
        try:
            self._reader.close()
        finally:
            close = self._close
            if close:
                self._close = None
                close()

    def join_thread(self):
        debug('Queue.join_thread()')
        assert self._closed, "Queue {0!r} not closed".format(self)
        if self._jointhread:
            self._jointhread()

    def cancel_join_thread(self):
        debug('Queue.cancel_join_thread()')
        self._joincancelled = True
        try:
            self._jointhread.cancel()
        except AttributeError:
            pass

    def _start_thread(self):
        debug('Queue._start_thread()')

        # Start thread which transfers data from buffer to pipe
        self._buffer.clear()
        self._thread = threading.Thread(
            target=Queue._feed,
            args=(self._buffer, self._notempty, self._send_bytes,
                  self._wlock, self._writer.close, self._ignore_epipe,
                  self._on_queue_feeder_error, self._sem),
            name='QueueFeederThread'
        )
        self._thread.daemon = True

        debug('doing self._thread.start()')
        self._thread.start()
        debug('... done self._thread.start()')

        if not self._joincancelled:
            self._jointhread = Finalize(
                self._thread, Queue._finalize_join,
                [weakref.ref(self._thread)],
                exitpriority=-5
                )

        # Send sentinel to the thread queue object when garbage collected
        self._close = Finalize(
            self, Queue._finalize_close,
            [self._buffer, self._notempty],
            exitpriority=10
            )

    @staticmethod
    def _finalize_join(twr):
        debug('joining queue thread')
        thread = twr()
        if thread is not None:
            thread.join()
            debug('... queue thread joined')
        else:
            debug('... queue thread already dead')

    @staticmethod
    def _finalize_close(buffer, notempty):
        debug('telling queue thread to quit')
        with notempty:
            buffer.append(_sentinel)
            notempty.notify()

    @staticmethod
    def _feed(buffer, notempty, send_bytes, writelock, close, ignore_epipe,
              onerror, queue_sem):
        debug('starting thread to feed data to pipe')
        nacquire = notempty.acquire
        nrelease = notempty.release
        nwait = notempty.wait
        bpopleft = buffer.popleft
        sentinel = _sentinel
        if sys.platform != 'win32':
            wacquire = writelock.acquire
            wrelease = writelock.release
        else:
            wacquire = None

        while 1:
            try:
                nacquire()
                try:
                    if not buffer:
                        nwait()
                finally:
                    nrelease()
                try:
                    while 1:
                        obj = bpopleft()
                        if obj is sentinel:
                            debug('feeder thread got sentinel -- exiting')
                            close()
                            return

                        # serialize the data before acquiring the lock
                        obj = _ForkingPickler.dumps(obj)
                        if wacquire is None:
                            send_bytes(obj)
                        else:
                            wacquire()
                            try:
                                send_bytes(obj)
                            finally:
                                wrelease()
                except IndexError:
                    pass
            except Exception as e:
                if ignore_epipe and getattr(e, 'errno', 0) == errno.EPIPE:
                    return
                # Since this runs in a daemon thread the resources it uses
                # may be become unusable while the process is cleaning up.
                # We ignore errors which happen after the process has
                # started to cleanup.
                if is_exiting():
                    info('error in queue thread: %s', e)
                    return
                else:
                    # Since the object has not been sent in the queue, we need
                    # to decrease the size of the queue. The error acts as
                    # if the object had been silently removed from the queue
                    # and this step is necessary to have a properly working
                    # queue.
                    queue_sem.release()
                    onerror(e, obj)

    @staticmethod
    def _on_queue_feeder_error(e, obj):
        """
        Private API hook called when feeding data in the background thread
        raises an exception.  For overriding by concurrent.futures.
        """
        import traceback
        traceback.print_exc()


_sentinel = object()
```



## 弱引用weaker.ref用法

函数原型如下

```python
weakref.ref(object[, callback])
```

返回一个对象的弱引用(不增加对象的引用计数)；可以调用此返回的弱引用来访问原始对象(此时增加对象的引用计数)，如果引用的原始对象不存在了，则调用返回None；如果传了callback参数(一个回调函数)，则当原始对象不存在(引用计数为0的时候)，此回调函数会被调用。

测试样例如下:

```python
import weakref
import sys


class TestClass():
    def __init__(self, a=1):
        self.value = a

    def get_value(self):
        return self.value


def callback(ref_object):
    print("callback is called with .", ref_object)

def main():
    instance = TestClass(a=10)
    print("原始对象初始引用计数: ", sys.getrefcount(instance))
    weakref_obj = weakref.ref(instance, callback)
    print("增加弱引用后原始对象的引用计数: ", sys.getrefcount(instance))
    # 调用弱引用对象--通过弱引用对象访问原始对象
    weakref_instance = weakref_obj()
    print("调用弱引用获取的对象是不是和原始对象一样: ", weakref_instance is instance)
    print("通过弱引用对象访问原始对象后，原始对象的引用计数: ", sys.getrefcount(instance))
    # 删除原始对象的所有引用，使得原始对象被gc回收
    del instance 
    del weakref_instance
    # 加个死循环，不让python解析器退出来，因为python解析器退出会使得所有对象被销毁，callback会被调用
    while True:
        pass 

if __name__ == "__main__":
    main()

------------------------------------------------------------------------------------------
原始对象初始引用计数:  2
增加弱引用后原始对象的引用计数:  2
调用弱引用获取的对象是不是和原始对象一样:  True
通过弱引用对象访问原始对象后，原始对象的引用计数:  3
# 删除原始对象的所有引用，使得原始对象被gc回收
callback is called with . <weakref at 0x7fbf92ad9f90; dead>
```

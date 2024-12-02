# 线程池
举个现实中购物的样例作为切入点：现实中有一个**快递公司**，**客户**通过快递公司提供的入口下单一个**商品**，并得到一个**快递单号**。
客户可以通过快递单号查询商品状态。快递公司内部分配一个**快递员**对商品进行配送，快递成功送达或者异常意味任务结束。

类比上述快递样例，线程池的工作机制实现需要有以下几个要素：
+ **线程池执行器**（快递公司）：负责管理所有的子线程（快递员）以及提供任务提交入口（商品下单）。 
+ **工作项**（商品）：提交的具体任务的抽象。
+ **工作线程入口函数**（快递员）：处理提交的任务。
+ **`Future`对象**（快递单号）：用于存储任务执行结果，及不同线程间结果同步。

下面一张图总结来线程池的工作原理：

![线程池工作原理](./images/threadpool.png)

**工作项`_WorkItem`** 是任务的静态抽象。工作项有如下功能：
+ 定义任务应该如何运行。
+ 任务运行结果应该存储在哪里。

工作项的具体实现如下：
```python
class _WorkItem:
    def __init__(self, future, fn, args, kwargs):
        self.future = future
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        if not self.future.set_running_or_notify_cancel():
            return

        try:
            result = self.fn(*self.args, **self.kwargs)
        except BaseException as exc:
            self.future.set_exception(exc)
            # Break a reference cycle with the exception 'exc'
            self = None
        else:
            self.future.set_result(result)
```
`_WorkItem`对象定义了一个`run`方法，用于执行任务，并将执行结果更新到`Future`对象。在开始运行任务前，会调用`Future`的`set_running_or_notify_cancel`方法，
以更新`Future`对象的状态机为`RUNNING`。

**工作线程入口函数`_worker`** 会不断从工作项队列取出一个工作项`_WorkItem`，并执行`_WorkItem.run()`。其工作流程可以总结如下：

![worker流程](./images/threadpool_worker.png)

工作线程的入口函数相关实现如下：
```python
def _worker(executor_reference, work_queue, initializer, initargs):
    if initializer is not None:
        try:
            initializer(*initargs)
        except BaseException:
            _base.LOGGER.critical('Exception in initializer:', exc_info=True)
            executor = executor_reference()
            if executor is not None:
                # 线程池不可用，所有后续操作抛出异常，已提交任务的Future都设置异常
                executor._initializer_failed()
            return
    try:
        while True:
            try:
                work_item = work_queue.get_nowait()
            except queue.Empty:
                executor = executor_reference()
                if executor is not None:
                    # 队列为空，通知线程池有一个空闲的工作线程
                    executor._idle_semaphore.release()
                del executor
                # 工作线程挂起，直到队列有数据
                work_item = work_queue.get(block=True)

            if work_item is not None:
                work_item.run()
                # Delete references to object. See GH-60488
                del work_item
                continue

            executor = executor_reference()
            # Exit if:
            #   - The interpreter is shutting down OR
            #   - The executor that owns the worker has been collected OR
            #   - The executor that owns the worker has been shutdown.
            if _shutdown or executor is None or executor._shutdown:
                # Flag the executor as shutting down as early as possible if it
                # is not gc-ed yet.
                if executor is not None:
                    executor._shutdown = True
                # Notice other workers
                work_queue.put(None)
                return
            del executor
    except BaseException:
        _base.LOGGER.critical('Exception in worker', exc_info=True)
```
重点解释下工作线程退出的场景，也就是工作线程获取的工作项是`None`。退出有两种触发场景：
+ 线程池主动调用`shutdown`方法。这时候`executor._shutdown=True`，所以工作线程在退出之前会往工作项队列`put`一个`None`，
以通知其他工作线程退出。
+ 因为异常原因，`python`解释器退出或者线程执行器实例被垃圾回收。这时候工作线程在退出之前会往工作项队列`put`一个`None`，
以通知其他工作线程退出。

**线程池控制器**的工作流程可以简化如下：接收用户提交的任务，将任务包装成一个线程池内部的工作项，将工作项放到内部工作项队列，
调整线程池中的子线程，使得工作项可以尽快被执行，最后返回给用户一个`Future`对象。线程池控制器应该具有如下属性：
+ 子线程管理相关：
  + `_max_workers`：定义线程池最大子线程数，默认值`min(32, (os.process_cpu_count() or 1) + 4)`。
  + `_idle_semaphore`：一个信号量对象，用于记录线程池中空闲的子线程数。
  + `_threads`：一个集合对象，存放线程池中每一个子线程对象，用于`shutdown`的优雅退出。
+ 工作项队列`_work_queue`：一个无边界限制的`FIFO`队列，存放工作项。
+ 线程池关闭：
  + `_shutdown`：一个`bool`值，表示线程池是否正在关闭，调用`shutdown`方法时被设置。
  + `_shutdown_lock`：一个不可重入锁对象，用于多线程间安全。
+ 其他属性：
  + `_broken`：一个字符串对象，记录线程池异常信息，在子线程初始化失败时候被设置。
  + `_initializer`：用于子线程初始化函数。
  + `_initargs`：子线程初始化函数的参数。
  + `_thread_name_prefix`：子线程名字前缀，默认`("ThreadPoolExecutor-%d" % self._counter()))`。

线程池控制器的定义如下：
```python
class ThreadPoolExecutor(_base.Executor):

    # Used to assign unique thread names when thread_name_prefix is not supplied.
    _counter = itertools.count().__next__

    def __init__(self, max_workers=None, thread_name_prefix='',
                 initializer=None, initargs=()):
        """Initializes a new ThreadPoolExecutor instance.

        """
        if max_workers is None:
            # ThreadPoolExecutor is often used to:
            # * CPU bound task which releases GIL
            # * I/O bound task (which releases GIL, of course)
            #
            # We use process_cpu_count + 4 for both types of tasks.
            # But we limit it to 32 to avoid consuming surprisingly large resource
            # on many core machine.
            max_workers = min(32, (os.process_cpu_count() or 1) + 4)
        if max_workers <= 0:
            raise ValueError("max_workers must be greater than 0")

        if initializer is not None and not callable(initializer):
            raise TypeError("initializer must be a callable")

        self._max_workers = max_workers
        self._work_queue = queue.SimpleQueue()
        self._idle_semaphore = threading.Semaphore(0)
        self._threads = set()
        self._broken = False
        self._shutdown = False
        self._shutdown_lock = threading.Lock()
        self._thread_name_prefix = (thread_name_prefix or ("ThreadPoolExecutor-%d" % self._counter()))
        self._initializer = initializer
        self._initargs = initargs
```
提交任务的入口函数`submit`实现如下：
```python
def submit(self, fn, /, *args, **kwargs):
    with self._shutdown_lock, _global_shutdown_lock:
        if self._broken:
            raise BrokenThreadPool(self._broken)

        if self._shutdown:
            raise RuntimeError('cannot schedule new futures after shutdown')
        if _shutdown:
            raise RuntimeError('cannot schedule new futures after '
                               'interpreter shutdown')
        # 创建一个 `Future` 对象，存放子线程执行的结果
        f = _base.Future()
        # 将提交的任务包装成线程池内部的 work_item
        w = _WorkItem(f, fn, args, kwargs)
        # 将 work_item 放到线程池队列 work_queue 供子线程消费
        self._work_queue.put(w)
        # 调整线程池子线程
        self._adjust_thread_count()
        # 将 Future 对象返回给用户
        return f
```
`submit`方法内首先会尝试获取线程池`shutdown`相关的锁，避免线程池在`shutdown`期间接收新的任务。只有线程池没有异常，且没有`shutdown`时，
线程池才会接收新的任务。`submit`完成提交任务的包装（`_WorkItem`），入队（`work_queue`）后，在返回结果`Future`前，
会调整线程池内部的子线程数，相关`_adjust_thread_count`方法实现如下：
```python
def _adjust_thread_count(self):
    # if idle threads are available, don't spin new threads
    if self._idle_semaphore.acquire(timeout=0):
        return

    # When the executor gets lost, the weakref callback will wake up
    # the worker threads.
    def weakref_cb(_, q=self._work_queue):
        # 通知子线程退出
        q.put(None)

    num_threads = len(self._threads)
    if num_threads < self._max_workers:
        thread_name = '%s_%d' % (self._thread_name_prefix or self,
                                 num_threads)
        t = threading.Thread(name=thread_name, target=_worker,
                             args=(weakref.ref(self, weakref_cb),
                                   self._work_queue,
                                   self._initializer,
                                   self._initargs))
        t.start()
        # 记录创建的子线程对象
        self._threads.add(t)
        # _threads_queues 是一个弱引用字典对象，记录子线程和其管理的工作项队列，用于解释器优雅退出
        _threads_queues[t] = self._work_queue
```
`_adjust_thread_count`方法首先会判断线程池内是否有空闲子线程（信号量`_idle_semaphore`值表示空闲子线程数）。如果没有空闲子线程，
会创建一个新子线程。当然，线程池中子线程数不会超过设置的最大值。注意到，在创建子线程参数中使用了线程控制器对象本身的弱引用对象`weakref.ref(self, weakref_cb)`。
目的是：当因为异常导致线程控制器对象丢失（例如被垃圾回收），会调用`weakref_cb`方法，进而通知子线程退出。
> 弱引用`weaker.ref`用法。函数原型如下
> ```python
> weakref.ref(object[, callback])
> ```
> 返回一个对象的弱引用(不增加对象的引用计数)；可以调用此返回的弱引用来访问原始对象(此时增加对象的引用计数)，如果引用的原始对象不存在了，则调用返回None；如果传了callback参数(一个回调函数)，则当原始对象不存在(引用计数为0的时候)，此回调函数会被调用。
> 
> 测试样例如下:
> 
> ```python
> import weakref
> import sys
> 
> 
> class TestClass():
>     def __init__(self, a=1):
>         self.value = a
> 
>     def get_value(self):
>         return self.value
> 
> 
> def callback(ref_object):
>     print("callback is called with .", ref_object)
> 
> def main():
>     instance = TestClass(a=10)
>     print("原始对象初始引用计数: ", sys.getrefcount(instance))
>     weakref_obj = weakref.ref(instance, callback)
>     print("增加弱引用后原始对象的引用计数: ", sys.getrefcount(instance))
>     # 调用弱引用对象--通过弱引用对象访问原始对象
>     weakref_instance = weakref_obj()
>     print("调用弱引用获取的对象是不是和原始对象一样: ", weakref_instance is instance)
>     print("通过弱引用对象访问原始对象后，原始对象的引用计数: ", sys.getrefcount(instance))
>     # 删除原始对象的所有引用，使得原始对象被gc回收
>     del instance 
>     del weakref_instance
>     # 加个死循环，不让python解析器退出来，因为python解析器退出会使得所有对象被销毁，callback会被调用
>     while True:
>         pass 
> 
> if __name__ == "__main__":
>     main()
> 
> ------------------------------------------------------------------------------------------
> 原始对象初始引用计数:  2
> 增加弱引用后原始对象的引用计数:  2
> 调用弱引用获取的对象是不是和原始对象一样:  True
> 通过弱引用对象访问原始对象后，原始对象的引用计数:  3
> # 删除原始对象的所有引用，使得原始对象被gc回收
> callback is called with . <weakref at 0x7fbf92ad9f90; dead>
> ```
线程池控制器提供了子线程初始化失败调用的内部`_initializer_failed`方法，用以设置线程池控制器异常。相关实现如下：
```python
def _initializer_failed(self):
    with self._shutdown_lock:
        self._broken = ('A thread initializer failed, the thread pool '
                        'is not usable anymore')
        # Drain work queue and mark pending futures failed
        while True:
            try:
                work_item = self._work_queue.get_nowait()
            except queue.Empty:
                break
            if work_item is not None:
                work_item.future.set_exception(BrokenThreadPool(self._broken))
```
`_initializer_failed`方法是线程安全的，会尝试获取`_shutdown_lock`，避免线程池`shutdown`时候执行。在其内部会设置`_broken`属性，
同时会将工作项队列中的所以工作项结果设置为异常。

最后看下线程池控制器如何优雅地关闭。关闭这个动作有两种场景：**主动关闭**和**异常关闭**。优雅关闭是指：线程池管理的子线程也要退出。

线程池主动关闭，也就是线程池控制器提供的`shutdown`方法相关实现如下：
```python
def shutdown(self, wait=True, *, cancel_futures=False):
    with self._shutdown_lock:
        # 设置线程池退出标志位
        self._shutdown = True
        if cancel_futures:
            # Drain all work items from the queue, and then cancel their
            # associated futures.
            while True:
                try:
                    work_item = self._work_queue.get_nowait()
                except queue.Empty:
                    break
                if work_item is not None:
                    work_item.future.cancel()

        # Send a wake-up to prevent threads calling
        # _work_queue.get(block=True) from permanently blocking.
        self._work_queue.put(None)
    if wait:
        for t in self._threads:
            t.join()
```
`shutdown`方法的核心是`self._work_queue.put(None)`语句，用于通知子线程退出。可选地，可以取消工作项队列中所有的任务。

对于线程池异常关闭线程池控制器优雅退出的实现如下：
```python
_threads_queues = weakref.WeakKeyDictionary()
_shutdown = False
# Lock that ensures that new workers are not created while the interpreter is
# shutting down. Must be held while mutating _threads_queues and _shutdown.
_global_shutdown_lock = threading.Lock()

def _python_exit():
    global _shutdown
    with _global_shutdown_lock:
        _shutdown = True
    items = list(_threads_queues.items())
    for t, q in items:
        q.put(None)
    for t, q in items:
        t.join()
# 注册解析器退出前执行的方法
threading._register_atexit(_python_exit)
```
`python`解析器在退出前会执行`_python_exit`方法。在`_python_exit`方法中设置`_shutdown`全局标志，表示解析器正在退出。
然后通过往每个线程关联的工作项队列入队`None`项以通知子线程退出。

[Future对象详细介绍](./futures.md)

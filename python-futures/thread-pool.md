# 线程池

主线程和子线程的交互分为两部分，第一个部分是主线程如何将任务提交给子线程，第二部分是子线程如何将任务执行结果传递给主线程；其中第二部分是通过 `Future` 对象实现，第一部分则通过任务队列实现。

<img src="../images/python-futures/image-20221007154407377.png" alt="image-20221007154407377" style="zoom:50%;" />

需要注意的是，此任务队列没有上限，也就是任务队列长度可以无限增加，最终可能导致 OOM。

## 线程执行器

```python
class ThreadPoolExecutor(_base.Executor):
    # Used to assign unique thread names when thread_name_prefix is not supplied.
    _counter = itertools.count().__next__

    def __init__(self, max_workers=None, thread_name_prefix='',
                 initializer=None, initargs=()):
        """Initializes a new ThreadPoolExecutor instance.

        Args:
            max_workers: The maximum number of threads that can be used to
                execute the given calls.
            thread_name_prefix: An optional name prefix to give our threads.
            initializer: A callable used to initialize worker threads.
            initargs: A tuple of arguments to pass to the initializer.
        """
        if max_workers is None:
            # ThreadPoolExecutor is often used to:
            # * CPU bound task which releases GIL
            # * I/O bound task (which releases GIL, of course)
            #
            # We use cpu_count + 4 for both types of tasks.
            # But we limit it to 32 to avoid consuming surprisingly large resource
            # on many core machine.
            max_workers = min(32, (os.cpu_count() or 1) + 4)
        if max_workers <= 0:
            raise ValueError("max_workers must be greater than 0")

        if initializer is not None and not callable(initializer):
            raise TypeError("initializer must be a callable")

        # 线程池允许的最大线程数
        self._max_workers = max_workers
        # 一个队列，存放每一个任务项，子线程会从此队列消费任务
        self._work_queue = queue.SimpleQueue()
        # 信号量，表示空闲线程的数目
        self._idle_semaphore = threading.Semaphore(0)
        # 集合，记录线程池中已有的线程
        self._threads = set()
        self._broken = False
        self._shutdown = False
        self._shutdown_lock = threading.Lock()
        self._thread_name_prefix = (thread_name_prefix or
                                    ("ThreadPoolExecutor-%d" % self._counter()))
        self._initializer = initializer
        self._initargs = initargs

    def submit(self, fn, /, *args, **kwargs):
        # 提交一个工作项任务，called by user
        with self._shutdown_lock, _global_shutdown_lock:
            if self._broken:
                raise BrokenThreadPool(self._broken)

            if self._shutdown:
                raise RuntimeError('cannot schedule new futures after shutdown')
            if _shutdown:
                raise RuntimeError('cannot schedule new futures after '
                                   'interpreter shutdown')

            # 一个Future对象，存放工作项的结果，在子线程中会更新此Future
            f = _base.Future()
            w = _WorkItem(f, fn, args, kwargs)
            # 将工作项放入队列
            self._work_queue.put(w)
            # 根据线程池当前状态，调整线程池线程数(是否增加)
            self._adjust_thread_count()
            # 返回一个任务的Future
            return f
    submit.__doc__ = _base.Executor.submit.__doc__

    def _adjust_thread_count(self):
        # 根据线程池是否有空闲线程以及线程池线程数目是否达到最大值来判断是否需要新增加线程
        # if idle threads are available, don't spin new threads
        if self._idle_semaphore.acquire(timeout=0):
            return

        # When the executor gets lost, the weakref callback will wake up
        # the worker threads.
        # 被引用的对象的所有引用都没有了，次回调函数会被调用
        def weakref_cb(_, q=self._work_queue):
            q.put(None)

        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = '%s_%d' % (self._thread_name_prefix or self,
                                     num_threads)
            t = threading.Thread(name=thread_name, target=_worker,
                                 # 子线程需要访问线程池某些对象，传一个弱引用对象，不增加对象引用计数
                                 args=(weakref.ref(self, weakref_cb),
                                       self._work_queue,
                                       self._initializer,
                                       self._initargs))
            t.start()
            self._threads.add(t)
            # 一个全局变量，python解析器退出的时候调用的函数会使用此对象，执行优雅退出
            _threads_queues[t] = self._work_queue

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

    def shutdown(self, wait=True, *, cancel_futures=False):
        # 关闭进程池，called by user
        with self._shutdown_lock:
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
    shutdown.__doc__ = _base.Executor.shutdown.__doc__
```

## 线程函数

```python
def _worker(executor_reference, work_queue, initializer, initargs):
    if initializer is not None:
        try:
            initializer(*initargs)
        except BaseException:
            _base.LOGGER.critical('Exception in initializer:', exc_info=True)
            executor = executor_reference()
            if executor is not None:
                executor._initializer_failed()
            return
    try:
        while True:
            work_item = work_queue.get(block=True)
            if work_item is not None:
                work_item.run()
                # Delete references to object. See issue16284
                del work_item

                # attempt to increment idle count
                # 通过弱引用对象获取实际引用的对象，此操作会使得实际对象引用计数加1
                # 如果实际引用对象不存在了，则此调用返回None.
                executor = executor_reference()
                if executor is not None:
                    executor._idle_semaphore.release()
                # 实际对象引用计数减1
                del executor
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

## 工作项

```python
class _WorkItem(object):
    def __init__(self, future, fn, args, kwargs):
        # 存放result
        self.future = future
        # 需要执行的任务
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        # 将Future状态设置为running，返回True，或者如果Future被取消，返回False
        if not self.future.set_running_or_notify_cancel():
            return
        try:
            result = self.fn(*self.args, **self.kwargs)
        except BaseException as exc:
            self.future.set_exception(exc)
            # Break a reference cycle with the exception 'exc'
            self = None
        else:
            # 填充Future的结果
            self.future.set_result(result)

    __class_getitem__ = classmethod(types.GenericAlias)
```

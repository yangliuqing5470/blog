# 问题背景
线上有一个服务以`Pod`的方式启动运行。此`Pod`存在`OOM`现象。观察监控，发现有内存泄漏存在。进入`Pod`内查看进程使用内存情况：
```bash
>ps aux
USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
www            1  0.0  0.0 9360492 79204 ?       Ssl  Mar15   0:08 python3 /code/htdocs/vr_framework/app.py
www           10  0.6  0.0 17497568 237748 ?     Sl   Mar15  16:04 python3 /code/htdocs/vr_framework/app.py
www         8459  0.0  0.1 14906308 567116 ?     Sl   Mar15   0:12 python3 /code/htdocs/vr_framework/app.py
www        15427  0.0  0.0 15332244 132672 ?     Sl   Mar15   0:02 python3 /code/htdocs/vr_framework/app.py
www        19191  0.0  0.0 15300304 119156 ?     S    Mar15   0:06 python3 /code/htdocs/vr_framework/app.py
www        24695  0.0  0.0 15332464 118924 ?     Sl   Mar15   0:14 python3 /code/htdocs/vr_framework/app.py
www        24697  0.0  0.0 15332464 118924 ?     Sl   Mar15   0:18 python3 /code/htdocs/vr_framework/app.py
www        33607  0.0  0.0 15332208 133972 ?     Sl   Mar15   0:03 python3 /code/htdocs/vr_framework/app.py
www        34395  0.0  0.0 15430876 124620 ?     Sl   Mar15   0:03 python3 /code/htdocs/vr_framework/app.py
www        43208  0.0  0.0 15332184 131568 ?     Sl   Mar16   0:03 python3 /code/htdocs/vr_framework/app.py
www       198636  0.0  0.0 15791012 146840 ?     Sl   Mar16   0:03 python3 /code/htdocs/vr_framework/app.py
www       309195  0.0  0.0 17167204 182632 ?     Sl   Mar16   0:02 python3 /code/htdocs/vr_framework/app.py
www       328050  0.0  0.1 17441900 714492 ?     S    Mar16   0:03 python3 /code/htdocs/vr_framework/app.py
www       331033  0.0  0.0 17167232 156128 ?     Sl   Mar16   0:04 python3 /code/htdocs/vr_framework/app.py
www       331035  0.0  0.0 17167232 156128 ?     Sl   Mar16   0:03 python3 /code/htdocs/vr_framework/app.py
www       333481  0.0  0.0 17167212 156168 ?     Sl   Mar16   0:03 python3 /code/htdocs/vr_framework/app.py
www       338952  0.0  0.0 17167220 156944 ?     Sl   Mar16   0:03 python3 /code/htdocs/vr_framework/app.py
www       346384  0.0  0.0 17167184 164520 ?     Sl   Mar16   0:02 python3 /code/htdocs/vr_framework/app.py
www       346793  0.0  0.0 17167208 160712 ?     Sl   Mar16   0:06 python3 /code/htdocs/vr_framework/app.py
www       350366  0.0  0.0 17167196 165248 ?     Sl   Mar16   0:11 python3 /code/htdocs/vr_framework/app.py
www       351195  0.0  0.0 17167224 160176 ?     Sl   Mar16   0:04 python3 /code/htdocs/vr_framework/app.py
www       351610  0.0  0.1 17429656 590524 ?     S    Mar16   0:04 python3 /code/htdocs/vr_framework/app.py
www       351611  0.0  0.0 17167224 158680 ?     Sl   Mar16   0:07 python3 /code/htdocs/vr_framework/app.py
www       353624  0.0  0.0 17216696 160100 ?     Sl   Mar16   0:03 python3 /code/htdocs/vr_framework/app.py
www       354040  0.0  0.0 17167524 160932 ?     Sl   Mar16   0:03 python3 /code/htdocs/vr_framework/app.py
www       364133  0.0  0.0 18366528 140452 ?     S    Mar16   0:07 python3 /code/htdocs/vr_framework/app.py
www       394098  0.0  0.0 18628272 182096 ?     Sl   06:04   0:05 python3 /code/htdocs/vr_framework/app.py
www       550532  0.0  0.0 115424  3428 pts/0    Ss   12:04   0:00 bash
www       550538  0.0  0.0 155316  4008 pts/0    R+   12:04   0:00 ps aux
```
发现有很多业务进程存在，**正常情况应该只有两个业务进程**（不跑任务情况下）：
```bash
bash-5.1$ ps aux
USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
www            1  0.0  0.0 427364 80900 ?        Ssl  11:34   0:00 python3 /code/htdocs/vr_framework/app.py
www            7  0.1  0.0 3943948 99812 ?       Sl   11:34   0:02 python3 /code/htdocs/vr_framework/app.py
www          162  0.0  0.0   4456  3776 pts/0    Ss   12:07   0:00 bash
www          168  0.0  0.0   7176  3132 pts/0    R+   12:07   0:00 ps aux
```
初步判断有**进程泄漏**存在。观察业务代码逻辑，环境使用如下：
+ `python`版本是`3.6.3`。
+ 业务代码中使用了进程池`ProcessPoolExecutor`。
  ```python
  # 任务开始
  self.process_pool = concurrent.futures.ProcessPoolExecutor(max_workers=4)
  ...
  # 任务结束
  self.process_pool.shutdown()
  ```
  使用方式是每次跑任务开始前初始化进程池，任务跑完后会调用`shutdown`关闭进程池。

# 问题剖析
根据背景中的初步现象，可以确定是因为进程池中的进程在**某些场景下没有正常关闭**导致的进程泄漏，进而引起了`OOM`的发生。
因为每天此服务任务量比较多，如果每次都稳定泄漏`max_workers=4`个进程，则泄漏的进程就不会是问题背景中那么少了。

可以确定在某些场景下`shutdown`方法并没有使得进程池正常释放资源。查看线上服务错误日志情况：
```bash
# 错误日志1，出现的概率稍微多点
Task failed, errmsg <A process in the process pool was terminated abruptly while the future was running or pending.>
# 错误日志2，出现的概率低
download 0.432s
Exception in thread Thread-141949:
Traceback (most recent call last):
  File "/usr/lib64/python3.6/threading.py", line 916, in _bootstrap_inner
    self.run()
  File "/usr/lib64/python3.6/threading.py", line 864, in run
    self._target(*self._args, **self._kwargs)
  File "/usr/lib64/python3.6/concurrent/futures/process.py", line 295, in _queue_management_worker
    shutdown_worker()
  File "/usr/lib64/python3.6/concurrent/futures/process.py", line 253, in shutdown_worker
    call_queue.put_nowait(None)
  File "/usr/lib64/python3.6/multiprocessing/queues.py", line 129, in put_nowait
    return self.put(obj, False)
  File "/usr/lib64/python3.6/multiprocessing/queues.py", line 83, in put
    raise Full
queue.Full
```
先看下错误日志`1`的原因。查看`python3.6.3`版本的`ProcessPoolExecutor`实现源码。在进程池内部有一个后台管理线程，
用于主线程和子进程间的通信以及管理子进程。当进程池有子进程意外被终止，进程池会退出，并被设置为`broken`状态。
```python
# 后台管理线程 _queue_management_worker 内部逻辑
sentinels = [p.sentinel for p in processes.values()]
ready = wait([reader] + sentinels)
if reader in ready:
    result_item = reader.recv()
else:
    # 进程池有子进程意外被终止
    ...
    for work_id, work_item in pending_work_items.items():
        work_item.future.set_exception(
            BrokenProcessPool(
                "A process in the process pool was "
                "terminated abruptly while the future was "
                "running or pending."
            ))
        # Delete references to object. See issue16284
        del work_item
    pending_work_items.clear()
    # Terminate remaining workers forcibly: the queues or their
    # locks may be in a dirty state and block forever.
    for p in processes.values():
        p.terminate()
    shutdown_worker()
    return
```
可以看到，错误日志`1`表示进程池内部有子进程被意外终止，其实不难发现是因为`OOM`导致子进程被系统终止。
接下来会对每一个子进程调用`terminate()`方法终止子进程，然后调用`shutdown_worker`释放进程池资源。
```python
def shutdown_worker():
   # This is an upper bound
   nb_children_alive = sum(p.is_alive() for p in processes.values())
   for i in range(0, nb_children_alive):
        # 这里目的是通知子进程退出
       call_queue.put_nowait(None)
   # Release the queue's resources as soon as possible.
   call_queue.close()
   # If .join() is not called on the created processes then
   # some multiprocessing.Queue methods may deadlock on Mac OS X.
   for p in processes.values():
       p.join()
```
到这里可以发现，错误日志`1`正常情况不会导致子进程泄漏。即使子进程`hang`死，那么调用`shutdown_worker`也会阻塞在`join`处。
进而`self.process_pool.shutdown()`也会卡住，不会处理新任务，但实际情况是服务并没有出现卡死，可以正常处理新任务。

到这里有两个问题需要解决。问题`1`：为啥调用了`terminate()`还会出现子进程没有被终止的情况？问题`2`：即使调用`terminate()`子进程没有被终止，
在`shutdown_worker`里面也会通知子进程退出，为啥还会出现子进程没被终止，且没有阻塞在`join`处？

接着查看`terminate()`的实现原理。在`linux`系统上，`terminate()`内部是执行`os.kill(pid, SIGTERM)`以发送`SIGTERM`信号终止进程。
因为此业务相关的算法服务是被包装在部门内部自研的`framework`下以作为一个自定义的`python`模块被`framework`调用。
`framework`在启动时候会注册`SIGTERM`和`SIGINT`信号处理函数以实现优雅退出。**由于在`linux`系统上，创建子进程默认使用`fork`方式，
所以父进程注册的`SIGTERM`信号处理函数会被复制到子进程中，使得子进程默认注册了`SIGTERM`信号处理函数，导致`terminate()`发送的`SIGTERM`被捕获，
不会走默认的终止进程流程**。

继续剖析问题`2`。查看错误日志`2`，发现在调用`shutdown_worker`时候在`call_queue.put_nowait(None)`抛出队列满的异常。
所以导致`shutdown_worker`后面的代码不会执行，而此后台管理线程因为此异常退出。这里最终导致子进程没有被成功终止。
`call_queue`队列的初始化如下：
```python
# EXTRA_QUEUED_CALLS = 1
self._call_queue = multiprocessing.Queue(self._max_workers + EXTRA_QUEUED_CALLS)
```
当队列还有任务没被子进程取走消费，此时`shutdown_worker`调用`call_queue.put_nowait(None)`可能会导致队列元素超过`5`，
使得队列满异常发生。

此时，梳理了`ProcessPoolExecutor`出现的子进程泄漏的根本原因。

**解决方案**：
+ 升级`python`版本，因为高版本的`python`已经修复了问题`2`，也就是在`shutdown_worker`因为队列满抛出异常的情况。
+ 高版本的`python`的`ProcessPoolExecutor`初始化支持`initializer`和`mp_context`参数。可以实现在子进程初始化的时候执行自定义逻辑，
如复位`SIGTERM`信号处理。`mp_context`指定创建子进程使用`spwan`方式。

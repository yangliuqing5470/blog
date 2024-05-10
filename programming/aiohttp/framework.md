# 引言
我们以一个简单的 http server 样例来窥探 aiohttp 框架的实现原理，下面是样例代码：
```python
from aiohttp import web

async def hello(request):
    return web.Response(text="Hello, world")

app = web.Application()
app.add_routes([web.get('/', hello)])

web.run_app(app)
```
样例代码可知，基于 aiohttp 实现的 http server 主要分三部分：
+ `Application` 对象构建（[Application实现原理](./application.md)）；
  ```python
  app = web.Application()
  ```
+ 添加路由规则，创建路由表（[Application实现原理](./application.md)）；
  ```python
  app.add_routes([web.get("/", hello)])
  ```
+ 启动服务运行；
  ```python
  web.run_app(app)
  ```
本节我们重点看下服务的启动运行。

# 运行框架
![aiohttp框架](./images/aiohtt框架.png)
aiohttp 底层基于[`asyncio`的`Transports&Protocols`编程实现](../python-asyncio/asyncio-networking.md)。
aiohttp 整个运行大体框架如上图所示，可以分为**服务启动**部分和**请求处理**部分。
处理请求主要分四个步骤：
+ [请求解析](./http_request_parser.md)
+ [请求对象构建](./http_request_build.md)
+ 处理请求
+ [返回响应](./http_response.md)

下面介绍**服务启动**和**处理请求**实现原理。

## 服务启动
服务启动的入口为`web.run_app`，其源码实现如下：
```python
def run_app(
    app: Union[Application, Awaitable[Application]],
    *,
    debug: bool = False,
    host: Optional[Union[str, HostSequence]] = None,
    port: Optional[int] = None,
    path: Union[PathLike, TypingIterable[PathLike], None] = None,
    sock: Optional[Union[socket.socket, TypingIterable[socket.socket]]] = None,
    shutdown_timeout: float = 60.0,
    keepalive_timeout: float = 75.0,
    ssl_context: Optional[SSLContext] = None,
    print: Optional[Callable[..., None]] = print,
    backlog: int = 128,
    access_log_class: Type[AbstractAccessLogger] = AccessLogger,
    access_log_format: str = AccessLogger.LOG_FORMAT,
    access_log: Optional[logging.Logger] = access_logger,
    handle_signals: bool = True,
    reuse_address: Optional[bool] = None,
    reuse_port: Optional[bool] = None,
    handler_cancellation: bool = False,
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> None:
    """Run an app locally"""
    if loop is None:
        loop = asyncio.new_event_loop()
    loop.set_debug(debug)

    # Configure if and only if in debugging mode and using the default logger
    if loop.get_debug() and access_log and access_log.name == "aiohttp.access":
        if access_log.level == logging.NOTSET:
            access_log.setLevel(logging.DEBUG)
        if not access_log.hasHandlers():
            access_log.addHandler(logging.StreamHandler())
    # 封装一个任务对象
    main_task = loop.create_task(
        _run_app(
            app,
            host=host,
            port=port,
            path=path,
            sock=sock,
            shutdown_timeout=shutdown_timeout,
            keepalive_timeout=keepalive_timeout,
            ssl_context=ssl_context,
            print=print,
            backlog=backlog,
            access_log_class=access_log_class,
            access_log_format=access_log_format,
            access_log=access_log,
            handle_signals=handle_signals,
            reuse_address=reuse_address,
            reuse_port=reuse_port,
            handler_cancellation=handler_cancellation,
        )
    )

    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main_task)
    except (GracefulExit, KeyboardInterrupt):  # pragma: no cover
        pass
    finally:
        # 优雅退出
        _cancel_tasks({main_task}, loop)
        _cancel_tasks(asyncio.all_tasks(loop), loop)
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        asyncio.set_event_loop(None)

def _cancel_tasks(
    to_cancel: Set["asyncio.Task[Any]"], loop: asyncio.AbstractEventLoop
) -> None:
    if not to_cancel:
        return

    for task in to_cancel:
        task.cancel()

    loop.run_until_complete(asyncio.gather(*to_cancel, return_exceptions=True))

    for task in to_cancel:
        if task.cancelled():
            continue
        if task.exception() is not None:
            loop.call_exception_handler(
                {
                    "message": "unhandled exception during asyncio.run() shutdown",
                    "exception": task.exception(),
                    "task": task,
                }
            )
```
> `web.run_app`的实现类似于`asyncio.run`方法，其中 main_task 就是 asyncio.run 的参数

`web.run_app`中的核心是执行协程`_run_app`，其实现源码如下：
```python
async def _run_app(
    app: Union[Application, Awaitable[Application]],
    *,
    host: Optional[Union[str, HostSequence]] = None,
    port: Optional[int] = None,
    path: Union[PathLike, TypingIterable[PathLike], None] = None,
    sock: Optional[Union[socket.socket, TypingIterable[socket.socket]]] = None,
    shutdown_timeout: float = 60.0,
    keepalive_timeout: float = 75.0,
    ssl_context: Optional[SSLContext] = None,
    print: Optional[Callable[..., None]] = print,
    backlog: int = 128,
    access_log_class: Type[AbstractAccessLogger] = AccessLogger,
    access_log_format: str = AccessLogger.LOG_FORMAT,
    access_log: Optional[logging.Logger] = access_logger,
    handle_signals: bool = True,
    reuse_address: Optional[bool] = None,
    reuse_port: Optional[bool] = None,
    handler_cancellation: bool = False,
) -> None:
    # 等待当前事件循环中所有的任务结束，用于优雅退出
    async def wait(
        starting_tasks: "WeakSet[asyncio.Task[object]]", shutdown_timeout: float
    ) -> None:
        # Wait for pending tasks for a given time limit.
        t = asyncio.current_task()
        assert t is not None
        starting_tasks.add(t)
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(_wait(starting_tasks), timeout=shutdown_timeout)

    async def _wait(exclude: "WeakSet[asyncio.Task[object]]") -> None:
        t = asyncio.current_task()
        assert t is not None
        exclude.add(t)
        while tasks := asyncio.all_tasks().difference(exclude):
            await asyncio.wait(tasks)

    # An internal function to actually do all dirty job for application running
    if asyncio.iscoroutine(app):
        app = await app

    app = cast(Application, app)

    runner = AppRunner(
        app,
        handle_signals=handle_signals,
        access_log_class=access_log_class,
        access_log_format=access_log_format,
        access_log=access_log,
        keepalive_timeout=keepalive_timeout,
        shutdown_timeout=shutdown_timeout,
        handler_cancellation=handler_cancellation,
    )

    await runner.setup()
    # On shutdown we want to avoid waiting on tasks which run forever.
    # It's very likely that all tasks which run forever will have been created by
    # the time we have completed the application startup (in runner.setup()),
    # so we just record all running tasks here and exclude them later.
    starting_tasks: "WeakSet[asyncio.Task[object]]" = WeakSet(asyncio.all_tasks())
    # 更新 AppRunner.shutdown_callback 属性，用于 AppRunner.cleanup 执行
    runner.shutdown_callback = partial(wait, starting_tasks, shutdown_timeout)

    sites: List[BaseSite] = []

    try:
        if host is not None:
            if isinstance(host, (str, bytes, bytearray, memoryview)):
                sites.append(
                    TCPSite(
                        runner,
                        host,
                        port,
                        ssl_context=ssl_context,
                        backlog=backlog,
                        reuse_address=reuse_address,
                        reuse_port=reuse_port,
                    )
                )
            else:
                for h in host:
                    sites.append(
                        TCPSite(
                            runner,
                            h,
                            port,
                            ssl_context=ssl_context,
                            backlog=backlog,
                            reuse_address=reuse_address,
                            reuse_port=reuse_port,
                        )
                    )
        elif path is None and sock is None or port is not None:
            sites.append(
                TCPSite(
                    runner,
                    port=port,
                    ssl_context=ssl_context,
                    backlog=backlog,
                    reuse_address=reuse_address,
                    reuse_port=reuse_port,
                )
            )
        ...

        for site in sites:
            await site.start()

        if print:  # pragma: no branch
            names = sorted(str(s.name) for s in runner.sites)
            print(
                "======== Running on {} ========\n"
                "(Press CTRL+C to quit)".format(", ".join(names))
            )

        # sleep forever by 1 hour intervals,
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()
```
源码中省略了`UnixSite`和`SockSite`部分。从源码可知，服务启动流程如下：
+ 将`Application`对象封装为`AppRunner`对象，执行 setup 阶段，也即执行 `await runner.setup()`；
+ 将`AppRunner`对象进一步包装为`xxxSite`对象，例如`TCPSite`对象，并启动服务，也即执行`await site.start()`；

### AppRunner
`AppRunner`初始化源码如下（省略了部分参数类型检查代码）：
```python
class AppRunner(BaseRunner):
    """Web Application runner"""
    def __init__(
        self,
        app: Application,
        *,
        handle_signals: bool = False,
        access_log_class: Type[AbstractAccessLogger] = AccessLogger,
        **kwargs: Any,
    ) -> None:
        ...
        kwargs["access_log_class"] = access_log_class
        # Application 对象构建参数 handler_args，用于更新请求处理协议 RequestHandler 某些关键字参数
        if app._handler_args:
            for k, v in app._handler_args.items():
                kwargs[k] = v

        ...
        super().__init__(handle_signals=handle_signals, **kwargs)
        self._app = app

class BaseRunner(ABC):
    def __init__(
        self,
        *,
        handle_signals: bool = False,
        shutdown_timeout: float = 60.0,
        **kwargs: Any,
    ) -> None:
        # 优雅停服回调方法，在 web.run_app 中设置
        self.shutdown_callback: Optional[Callable[[], Awaitable[None]]] = None
        self._handle_signals = handle_signals
        # 传递给请求处理协议 RequestHandler 的关键字参数
        self._kwargs = kwargs
        # Server 实例
        self._server: Optional[Server] = None
        # 存放所有 xxxSite 实例，每一个元素（理解为网站）对应一个服务
        self._sites: List[BaseSite] = []
        self._shutdown_timeout = shutdown_timeout
```
`AppRunner`对象提供了如下的方法和属性：
+ `server`：一个`Server`对象，`Server`对象是可调用对象，返回一个`RequestHandler`协议对象，
用于`asyncio Transports&Protocols`方式编程；
  ```python
  @property
  def server(self) -> Optional[Server]:
      return self._server
  ```
+ `addresses`：返回一个 list，每个元素都是一个元组，表示一个 socket 的地址；
  ```python
  @property
  def addresses(self) -> List[Any]:
      ret: List[Any] = []
      for site in self._sites:
          server = site._server
          if server is not None:
              sockets = server.sockets  # type: ignore[attr-defined]
              if sockets is not None:
                  for sock in sockets:
                      ret.append(sock.getsockname())
      return ret
  # socket.getsockname() 返回结果样例：('127.0.0.1', 8080)
  ```
+ `sites`：一个集合 set，每一个元素是`xxxSite`实例；
  ```python
  @property
  def sites(self) -> Set[BaseSite]:
      return set(self._sites)
  ```
+ `app`：绑定的 Application 实例；
  ```python
  @property
  def app(self) -> Application:
      return self._app
  ```
+ 注册，检查，删除`xxxSite`实例；
  ```python
  def _reg_site(self, site: BaseSite) -> None:
      if site in self._sites:
          raise RuntimeError(f"Site {site} is already registered in runner {self}")
      self._sites.append(site)

  def _check_site(self, site: BaseSite) -> None:
      if site not in self._sites:
          raise RuntimeError(f"Site {site} is not registered in runner {self}")

  def _unreg_site(self, site: BaseSite) -> None:
      if site not in self._sites:
          raise RuntimeError(f"Site {site} is not registered in runner {self}")
      self._sites.remove(site)
  ```
`AppRunner`提供了`setup`方法用于初始化，`setup`需要在`xxxSite`实例添加之前调用，其相关源码如下：
```python
async def setup(self) -> None:
    loop = asyncio.get_event_loop()

    if self._handle_signals:
        try:
            # 注册信号处理
            loop.add_signal_handler(signal.SIGINT, _raise_graceful_exit)
            loop.add_signal_handler(signal.SIGTERM, _raise_graceful_exit)
        except NotImplementedError:  # pragma: no cover
            # add_signal_handler is not implemented on Windows
            pass

    self._server = await self._make_server()

class GracefulExit(SystemExit):
    code = 1

def _raise_graceful_exit() -> None:
    raise GracefulExit()
```
根据源码可知，`setup`主要完成以下工作：
+ 注册`SIGINT`和`SIGTERM`处理函数，抛出`GracefulExit`异常，此异常会被`web.run_app`捕获，什么都不做；
+ 调用`self._make_server`方法，创建一个`Server`对象，`Server`对象扮演的角色是`asyncio Transports&Protocols`编程中的
`Protocols`角色；
+ 在`self._make_server`内部会触发`app`的`on_startup`信号，使得添加的相关方法被执行；

`self._make_server`的源码实现如下：
```python
async def _make_server(self) -> Server:
    self._app.on_startup.freeze()
    # 触发 app 的 on_startup 信号
    await self._app.startup()
    self._app.freeze()
    # 返回一个 Server 对象
    return Server(
        self._app._handle,  # type: ignore[arg-type]
        request_factory=self._make_request,
        **self._kwargs,
    )
# 构建请求对象的工厂函数
def _make_request(
    self,
    message: RawRequestMessage,
    payload: StreamReader,
    protocol: RequestHandler,
    writer: AbstractStreamWriter,
    task: "asyncio.Task[None]",
    _cls: Type[Request] = Request,
) -> Request:
    loop = asyncio.get_running_loop()
    return _cls(
        message,
        payload,
        protocol,
        writer,
        task,
        loop,
        client_max_size=self.app._client_max_size,
    )
```
`AppRunner`提供了`cleanup`方法用于优雅退出，`cleanup`源码实现如下：
```python
async def cleanup(self) -> None:
    # The loop over sites is intentional, an exception on gather()
    # leaves self._sites in unpredictable state.
    # The loop guarantees that a site is either deleted on success or
    # still present on failure
    # 关闭底层服务，不监听新的连接
    for site in list(self._sites):
        await site.stop()
    # 关闭 Server 对象，也就是底层协议对象，例如会关闭已经建立的连接等
    if self._server:  # If setup succeeded
        # Yield to event loop to ensure incoming requests prior to stopping the sites
        # have all started to be handled before we proceed to close idle connections.
        await asyncio.sleep(0)
        self._server.pre_shutdown()
        # 触发 app.on_shutdown 信号
        await self.shutdown()
        # 等待事件循环中所有任务执行完
        if self.shutdown_callback:
            await self.shutdown_callback()
        await self._server.shutdown(self._shutdown_timeout)
    # 触发 app.on_cleanup 信号
    await self._cleanup_server()
    # 删除注册的信号
    self._server = None
    if self._handle_signals:
        loop = asyncio.get_running_loop()
        try:
            loop.remove_signal_handler(signal.SIGINT)
            loop.remove_signal_handler(signal.SIGTERM)
        except NotImplementedError:  # pragma: no cover
            # remove_signal_handler is not implemented on Windows
            pass

async def shutdown(self) -> None:
    # 触发 app.on_shutdown 信号
    await self._app.shutdown()

async def _cleanup_server(self) -> None:
    # 触发 app.on_cleanup 信号
    await self._app.cleanup()
```
由源码可知，`cleanup`执行流程如下：
+ 关闭底层的 socket 服务，使其不接收新的客户端连接；
+ 关闭`Server`对象，也就是关闭底层协议对象，进而会关闭已经建立的连接；
  > 源码中 `await asyncio.sleep(0)`作用是把控制权交给事件循环，
  以处理在服务退出过程中有连接请求没有处理的情况。
+ 执行`self.shutdown_callback`等待当前事件循环中的任务执行完；
+ 触发`app.on_shutdown`信号；
+ 触发`app.on_cleanup`信号；
+ 删除已经注册的信号处理；

### Server
`Server`可以看作一个容器，记录管理所有连接请求的协议实例。每一个新的连接建立，`asyncio`底层都会初始化一个`RequestHandler`协议对象，
`Server`就会记录这些协议对象，当连接关闭，记录对应的`RequestHandler`实例也会删除。

`Server`对象的初始化源码如下：
```python
class Server:
    def __init__(
        self,
        handler: _RequestHandler,
        *,
        request_factory: Optional[_RequestFactory] = None,
        debug: Optional[bool] = None,
        handler_cancellation: bool = False,
        **kwargs: Any,
    ) -> None:
        ...
        self._loop = asyncio.get_running_loop()
        # 一个字典，记录所有的连接使用的协议 RequestHandler 对象实例
        self._connections: Dict[RequestHandler, asyncio.Transport] = {}
        # 用于初始化协议 RequestHandler 对象的关键字参数
        self._kwargs = kwargs
        # 连接数
        self.requests_count = 0
        # 处理请求方法，也就是用户自定义处理请求的路由方法
        self.request_handler = handler
        # 构建请求对象的工厂函数
        self.request_factory = request_factory or self._make_request
        self.handler_cancellation = handler_cancellation

    # 构建请求对象默认工厂函数，如果不指定就使用
    def _make_request(
        self,
        message: RawRequestMessage,
        payload: StreamReader,
        protocol: RequestHandler,
        writer: AbstractStreamWriter,
        task: "asyncio.Task[None]",
    ) -> BaseRequest:
        return BaseRequest(message, payload, protocol, writer, task, self._loop)
```
`Server`对象提供了如下的属性或方法，用于记录或删除每个连接使用的协议对象`RequestHandler`：
+ `connections`：获取所有连接使用的协议对象`RequestHandler`，返回一个列表；
  ```python
  @property
  def connections(self) -> List[RequestHandler]:
      return list(self._connections.keys())
  ```
+ `connection_made`：添加新的连接协议对象`RequestHandler`，在连接建立的时候调用；
  ```python
  def connection_made(
      self, handler: RequestHandler, transport: asyncio.Transport
  ) -> None:
      self._connections[handler] = transport
  ```
+ `connection_lost`：删除连接对应的协议对象，在连接关闭的时候调用；
  ```python
  def connection_lost(
      self, handler: RequestHandler, exc: Optional[BaseException] = None
  ) -> None:
      if handler in self._connections:
          del self._connections[handler]
  ```
`Server`对象是个可调用对象，用于初始化一个`Protocols`对象`RequestHandler`，实现源码如下：
```python
def __call__(self) -> RequestHandler:
    try:
        return RequestHandler(self, loop=self._loop, **self._kwargs)
    except TypeError:
        # Failsafe creation: remove all custom handler_args
        kwargs = {
            k: v
            for k, v in self._kwargs.items()
            if k in ["debug", "access_log_class"]
        }
        return RequestHandler(self, loop=self._loop, **kwargs)
```
`RequestHandler`对象在*处理请求*小结详细介绍。

`Server`对象优雅停服的相关实现如下：
```python
def pre_shutdown(self) -> None:
    # 调用 RequestHandler.close 方法
    for conn in self._connections:
        conn.close()

async def shutdown(self, timeout: Optional[float] = None) -> None:
    # 调用 RequestHandler.shutdown 方法
    coros = (conn.shutdown(timeout) for conn in self._connections)
    await asyncio.gather(*coros)
    self._connections.clear()
```

### TCPSite
`TCPSite`基于 TCP socket 服务`AppRunner`对象，`TCPSite`是对`AppRunner`的进一步封装，可以看成一个网站服务的角色。

`TCPSite`初始化源码如下：
```python
class TCPSite(BaseSite):
    def __init__(
        self,
        runner: "BaseRunner",
        host: Optional[str] = None,
        port: Optional[int] = None,
        *,
        ssl_context: Optional[SSLContext] = None,
        backlog: int = 128,
        reuse_address: Optional[bool] = None,
        reuse_port: Optional[bool] = None,
    ) -> None:
        super().__init__(
            runner,
            ssl_context=ssl_context,
            backlog=backlog,
        )
        self._host = host
        # 设置默认port，http是8080，https是8443
        if port is None:
            port = 8443 if self._ssl_context else 8080
        self._port = port
        self._reuse_address = reuse_address
        self._reuse_port = reuse_port

class BaseSite(ABC):
    def __init__(
        self,
        runner: "BaseRunner",
        *,
        ssl_context: Optional[SSLContext] = None,
        backlog: int = 128,
    ) -> None:
        # 确保 runner.setup 已经被调用
        if runner.server is None:
            raise RuntimeError("Call runner.setup() before making a site")
        self._runner = runner
        self._ssl_context = ssl_context
        self._backlog = backlog
        # 基于tcp socket 的服务对象
        self._server: Optional[asyncio.AbstractServer] = None
```
`TCPSite`启动`start`方法源码如下：
```python
# 子类
async def start(self) -> None:
    await super().start()
    loop = asyncio.get_event_loop()
    # 当一个协议对象使用，在 loop.create_server 内部建立连接会初始化
    server = self._runner.server
    assert server is not None
    self._server = await loop.create_server(
        server,
        self._host,
        self._port,
        ssl=self._ssl_context,
        backlog=self._backlog,
        reuse_address=self._reuse_address,
        reuse_port=self._reuse_port,
    )

# 父类
async def start(self) -> None:
    self._runner._reg_site(self)
```
`start`方法主要完成以下工作：
+ 调用`runner._reg_site`注册当前的`TCPSite`实例到`AppRunner`实例中；
+ 调用`asyncio`中`loop.create_server`开始服务，此时可以接收新的客户端连接；

`TCPSite`停服`stop`方法源码实现如下：
```python
async def stop(self) -> None:
    self._runner._check_site(self)
    if self._server is not None:  # Maybe not started yet
        self._server.close()

    self._runner._unreg_site(self)
```
`stop`方法主要完成以下工作：
+ 底层 tcp socket 服务停服；
+ 删除`AppRunner`实例注册的`TCPSite`实例；

`TCPSite`也提供了以下属性：
+ `name`：返回一个字符串 url，只包含 scheme、host、port 部分；
  ```python
  @property
  def name(self) -> str:
      scheme = "https" if self._ssl_context else "http"
      host = "0.0.0.0" if self._host is None else self._host
      return str(URL.build(scheme=scheme, host=host, port=self._port))
  ```

## 处理请求
aiohttp 底层基于[`asyncio`的`Transports&Protocols`编程实现](../python-asyncio/asyncio-networking.md)。
在处理新的连接时，使用的协议是`RequestHandler`，`RequestHandler`初始化源码如下：
```python
class RequestHandler(BaseProtocol):
    KEEPALIVE_RESCHEDULE_DELAY = 1
    def __init__(
        self,
        manager: "Server",
        *,
        loop: asyncio.AbstractEventLoop,
        keepalive_timeout: float = 75.0,  # NGINX default is 75 secs
        tcp_keepalive: bool = True,
        logger: Logger = server_logger,
        access_log_class: _AnyAbstractAccessLogger = AccessLogger,
        access_log: Optional[Logger] = access_logger,
        access_log_format: str = AccessLogger.LOG_FORMAT,
        max_line_size: int = 8190,
        max_field_size: int = 8190,
        lingering_time: float = 10.0,
        read_bufsize: int = 2**16,
        auto_decompress: bool = True,
        timeout_ceil_threshold: float = 5,
    ):
        super().__init__(loop)

        self._request_count = 0
        # 是否保持长连接
        self._keepalive = False
        # 记录当前构建的请求对象，也就是下面请求工厂函数构建的对象
        self._current_request: Optional[BaseRequest] = None
        # Server 对象，管理每一个连接
        self._manager: Optional[Server] = manager
        # 处理请求的方法，也就是用户自定义的路由方法
        self._request_handler: Optional[_RequestHandler] = manager.request_handler
        # 构建请求对象的工厂函数
        self._request_factory: Optional[_RequestFactory] = manager.request_factory
        # 是否开启 socket.SO_KEEPALIVE socket 选项
        self._tcp_keepalive = tcp_keepalive
        # placeholder to be replaced on keepalive timeout setup
        self._keepalive_time = 0.0
        self._keepalive_handle: Optional[asyncio.Handle] = None
        self._keepalive_timeout = keepalive_timeout
        self._lingering_time = float(lingering_time)

        # 缓存buffer 存储接收的数据，用于后面 start 方法消费(流式编程思想)
        self._messages: Deque[_MsgType] = deque()
        self._message_tail = b""
        # 数据同步对象，缓存buffer没有数据，消费者都会等待直到缓存有数据
        self._waiter: Optional[asyncio.Future[None]] = None
        # 处理请求数据的任务 执行 start 方法的任务
        self._task_handler: Optional[asyncio.Task[None]] = None

        self._upgrade = False
        # 请求体解析对象
        self._payload_parser: Any = None
        # 请求解析对象
        self._request_parser: Optional[HttpRequestParser] = HttpRequestParser(
            self,
            loop,
            read_bufsize,
            max_line_size=max_line_size,
            max_field_size=max_field_size,
            payload_exception=RequestPayloadError,
            auto_decompress=auto_decompress,
        )

        self._timeout_ceil_threshold: float = 5
        try:
            self._timeout_ceil_threshold = float(timeout_ceil_threshold)
        except (TypeError, ValueError):
            pass

        self.logger = logger
        self.access_log = access_log
        if access_log:
            if issubclass(access_log_class, AbstractAsyncAccessLogger):
                self.access_logger: Optional[AbstractAsyncAccessLogger] = (
                    access_log_class()
                )
            else:
                access_logger = access_log_class(access_log, access_log_format)
                self.access_logger = AccessLoggerWrapper(
                    access_logger,
                    self._loop,
                )
        else:
            self.access_logger = None

        self._close = False
        self._force_close = False
```
初始化各个变量的含义见注释说明。协议方法连接建立`connection_made`和连接丢失`connection_lost`方法源码实现如下：
```python
def connection_made(self, transport: asyncio.BaseTransport) -> None:
    # 调 asyncio.BaseTransport 的 connection_made 方法
    super().connection_made(transport)

    real_transport = cast(asyncio.Transport, transport)
    if self._tcp_keepalive:
        # sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        tcp_keepalive(real_transport)
    # 创建一个任务供事件循环调度，运行 start 方法
    self._task_handler = self._loop.create_task(self.start())
    assert self._manager is not None
    # 向管理对象 Server 注册自身
    self._manager.connection_made(self, real_transport)

def connection_lost(self, exc: Optional[BaseException]) -> None:
    if self._manager is None:
        return
    # 管理对象删除自身
    self._manager.connection_lost(self, exc)

    super().connection_lost(exc)

    # Grab value before setting _manager to None.
    handler_cancellation = self._manager.handler_cancellation

    self._manager = None
    # 设置强制关闭
    self._force_close = True
    self._request_factory = None
    self._request_handler = None
    self._request_parser = None
    # 管理长连接任务取消
    if self._keepalive_handle is not None:
        self._keepalive_handle.cancel()
    # 通知所有等待连接关闭的对象请求取消
    if self._current_request is not None:
        if exc is None:
            exc = ConnectionResetError("Connection lost")
        self._current_request._cancel(exc)
    # 取消数据同步对象
    if self._waiter is not None:
        self._waiter.cancel()
    # 取消处理请求任务，执行start任务
    if handler_cancellation and self._task_handler is not None:
        self._task_handler.cancel()

    self._task_handler = None
    # 通知负载解析结束
    if self._payload_parser is not None:
        # 设置流式读结束
        self._payload_parser.feed_eof()
        self._payload_parser = None
```
`connection_made`中会启动一个任务执行`start`方法，`start`方法源码如下：
```python
async def start(self) -> None:
    loop = self._loop
    handler = self._task_handler
    assert handler is not None
    # 管理对象 Server 对象
    manager = self._manager
    assert manager is not None
    # 用于控制长连接的超时时间
    keepalive_timeout = self._keepalive_timeout
    resp = None
    assert self._request_factory is not None
    assert self._request_handler is not None

    while not self._force_close:
        if not self._messages:
            # 缓存 buffer 中没有数据，一直等待数据到来
            try:
                # wait for next request
                self._waiter = loop.create_future()
                await self._waiter
            except asyncio.CancelledError:
                break
            finally:
                self._waiter = None
        # self._messages 中的每一项都对应一个完整的请求数据
        # 请求体数据通过 StreamReader 获取，如果没有数据内部会等待
        message, payload = self._messages.popleft()

        start = loop.time()
        # 更新请求数
        manager.requests_count += 1
        # 用于响应报文的流式写对象
        writer = StreamWriter(self, loop)
        # http 数据解析异常
        if isinstance(message, _ErrInfo):
            # make request_factory work
            request_handler = self._make_error_handler(message)
            message = ERROR
        else:
            request_handler = self._request_handler
        # 构建请求体 Request 对象
        request = self._request_factory(message, payload, self, writer, handler)
        try:
            # a new task is used for copy context vars (#3406)
            task = self._loop.create_task(
                self._handle_request(request, start, request_handler)
            )
            try:
                # 等待请求处理结束，resp 表示响应对象，reset 表示响应发送结果是否失败，
                # True 表示失败，False 表示成功
                resp, reset = await task
            except (asyncio.CancelledError, ConnectionError):
                # start 任务取消
                self.log_debug("Ignored premature client disconnection")
                break

            # Drop the processed task from asyncio.Task.all_tasks() early
            del task
            # https://github.com/python/mypy/issues/14309
            if reset:  # type: ignore[possibly-undefined]
                self.log_debug("Ignored premature client disconnection 2")
                break

            # notify server about keep-alive
            self._keepalive = bool(resp.keep_alive)

            # check payload
            # 清理工作，请求体数据没接收完情况，例如在发送请求数据过程中处理请求任务返回结束
            if not payload.is_eof():
                lingering_time = self._lingering_time
                # Could be force closed while awaiting above tasks.
                if not self._force_close and lingering_time:  # type: ignore[redundant-expr]
                    self.log_debug(
                        "Start lingering close timer for %s sec.", lingering_time
                    )

                    now = loop.time()
                    end_t = now + lingering_time

                    with suppress(asyncio.TimeoutError, asyncio.CancelledError):
                        while not payload.is_eof() and now < end_t:
                            async with ceil_timeout(end_t - now):
                                # read and ignore
                                await payload.readany()
                            now = loop.time()

                # if payload still uncompleted
                if not payload.is_eof() and not self._force_close:
                    self.log_debug("Uncompleted request.")
                    self.close()

            set_exception(payload, PayloadAccessError())

        except asyncio.CancelledError:
            self.log_debug("Ignored premature client disconnection ")
            break
        except RuntimeError as exc:
            if self._loop.get_debug():
                self.log_exception("Unhandled runtime exception", exc_info=exc)
            self.force_close()
        except Exception as exc:
            self.log_exception("Unhandled exception", exc_info=exc)
            self.force_close()
        finally:
            if self.transport is None and resp is not None:
                self.log_debug("Ignored premature client disconnection.")
            elif not self._force_close:
                # 处理完请求数据，开始管理空闲状态的长连接，超过超时时间就关闭了
                if self._keepalive and not self._close:
                    # start keep-alive timer
                    if keepalive_timeout is not None:
                        now = self._loop.time()
                        self._keepalive_time = now
                        if self._keepalive_handle is None:
                            self._keepalive_handle = loop.call_at(
                                now + keepalive_timeout, self._process_keepalive
                            )
                else:
                    break

    # remove handler, close transport if no handlers left
    if not self._force_close:
        self._task_handler = None
        if self.transport is not None:
            self.transport.close()
```
在`start`源码中，处理完当前请求后，如果指定长连接模式且设置长连接超时时间，则会添加一个空闲连接管理的任务`self._payload_parser`，
相关源码实现如下：
```python
def _process_keepalive(self) -> None:
    if self._force_close or not self._keepalive:
        return

    next = self._keepalive_time + self._keepalive_timeout

    # handler in idle state
    if self._waiter:
        if self._loop.time() > next:
            # 空闲状态超过超时时间，强制关闭
            self.force_close()
            return

    # not all request handlers are done,
    # reschedule itself to next second
    self._keepalive_handle = self._loop.call_later(
        self.KEEPALIVE_RESCHEDULE_DELAY,
        self._process_keepalive,
    )
```
`start`中会创建一个新的任务`self._handle_request`处理请求，其相关源码如下：
```python
async def _handle_request(
    self,
    request: BaseRequest,
    start_time: float,
    request_handler: Callable[[BaseRequest], Awaitable[StreamResponse]],
) -> Tuple[StreamResponse, bool]:
    assert self._request_handler is not None
    try:
        try:
            # 更新当前请求对象，用于优雅退出
            self._current_request = request
            # 等待请求处理完成
            resp = await request_handler(request)
        finally:
            self._current_request = None
    except HTTPException as exc:
        resp = Response(
            status=exc.status, reason=exc.reason, text=exc.text, headers=exc.headers
        )
        resp._cookies = exc._cookies
        reset = await self.finish_response(request, resp, start_time)
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError as exc:
        self.log_debug("Request handler timed out.", exc_info=exc)
        resp = self.handle_error(request, 504)
        reset = await self.finish_response(request, resp, start_time)
    except Exception as exc:
        resp = self.handle_error(request, 500, exc)
        reset = await self.finish_response(request, resp, start_time)
    else:
        reset = await self.finish_response(request, resp, start_time)

    return resp, reset
```
在`_handle_request`内，请求处理完后，会将返回的响应`Response`对象实例`resp`传递给`self.finish_response`以完成响应发送，
`self.finish_response`源码实现如下：
```python
async def finish_response(
    self, request: BaseRequest, resp: StreamResponse, start_time: float
) -> bool:
    # 通知调用 Request.wait_for_disconnection() 地方，请求结束
    request._finish()
    if self._request_parser is not None:
        self._request_parser.set_upgraded(False)
        self._upgrade = False
        if self._message_tail:
            self._request_parser.feed_data(self._message_tail)
            self._message_tail = b""
    try:
        prepare_meth = resp.prepare
    except AttributeError:
        if resp is None:
            raise RuntimeError("Missing return " "statement on request handler")
        else:
            raise RuntimeError(
                "Web-handler should return "
                "a response instance, "
                "got {!r}".format(resp)
            )
    try:
        # 等待 Response.prepare 方法执行完
        await prepare_meth(request)
        # 发送响应体数据，如果有的话
        await resp.write_eof()
    except ConnectionError:
        await self.log_access(request, resp, start_time)
        return True
    else:
        await self.log_access(request, resp, start_time)
        # 响应成功
        return False
```
接收数据`data_received`和`eof_received`相关源码实现如下：
```python
def eof_received(self) -> None:
    pass

def data_received(self, data: bytes) -> None:
    if self._force_close or self._close:
        return
    # parse http messages
    messages: Sequence[_MsgType]
    if self._payload_parser is None and not self._upgrade:
        # 非请求体数据
        assert self._request_parser is not None
        try:
            # messages 是请求行和请求头信息
            messages, upgraded, tail = self._request_parser.feed_data(data)
        except HttpProcessingError as exc:
            messages = [
                (_ErrInfo(status=400, exc=exc, message=exc.message), EMPTY_PAYLOAD)
            ]
            upgraded = False
            tail = b""

        for msg, payload in messages or ():
            # 增加请求数
            self._request_count += 1
            # 将请求数据写到缓存 self._messages 中
            self._messages.append((msg, payload))

        waiter = self._waiter
        if messages and waiter is not None and not waiter.done():
            # don't set result twice
            # 通知缓存 self._messages 可读
            waiter.set_result(None)

        self._upgrade = upgraded
        if upgraded and tail:
            self._message_tail = tail

    # no parser, just store
    elif self._payload_parser is None and self._upgrade and data:
        self._message_tail += data

    # feed payload
    elif data:
        # 请求体数据只写到 StreamReader 对象中即可
        # 走到这里说明 set_parser 被调用，指定了 self._payload_parser 对象
        # 请求体数据接收完毕，关闭连接（会先等当前请求处理完）
        eof, tail = self._payload_parser.feed_data(data)
        if eof:
            self.close()
```
`eof_received`在客户端未连接时（关闭或丢失）被调用，根据底层`asyncio._SelectorSocketTransport`部分源码可知，
`eof_received`返回 None 会调用`transport.close`方法，会移除服务监听 socket，最终`self.connection_lost`会被调用。

关闭停止涉及`close`、`force_close`和`shutdown`方法，相关的源码如下：
```python
def close(self) -> None:
    """Close connection.

    Stop accepting new pipelining messages and close
    connection when handlers done processing messages.
    """
    self._close = True
    if self._waiter:
        self._waiter.cancel()

def force_close(self) -> None:
    """Forcefully close connection."""
    self._force_close = True
    if self._waiter:
        self._waiter.cancel()
    # 关闭底层的 transport
    if self.transport is not None:
        self.transport.close()
        self.transport = None

async def shutdown(self, timeout: Optional[float] = 15.0) -> None:
    """Do worker process exit preparations.

    We need to clean up everything and stop accepting requests.
    It is especially important for keep-alive connections.
    """
    self._force_close = True

    if self._keepalive_handle is not None:
        self._keepalive_handle.cancel()

    if self._waiter:
        self._waiter.cancel()

    # wait for handlers
    with suppress(asyncio.CancelledError, asyncio.TimeoutError):
        async with ceil_timeout(timeout):
            if self._current_request is not None:
                self._current_request._cancel(asyncio.CancelledError())

            if self._task_handler is not None and not self._task_handler.done():
                await self._task_handler

    # force-close non-idle handler
    if self._task_handler is not None:
        self._task_handler.cancel()
    # 关闭底层的 transport
    if self.transport is not None:
        self.transport.close()
        self.transport = None
```

# 优雅停服

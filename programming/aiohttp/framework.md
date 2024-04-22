

## Application
`Application`的初始化如下：
```python
class Application(MutableMapping[Union[str, AppKey[Any]], Any]):
    def __init__(
        self,
        *,
        logger: logging.Logger = web_logger,
        middlewares: Iterable[Middleware] = (),
        handler_args: Optional[Mapping[str, Any]] = None,
        client_max_size: int = 1024**2,
        debug: Any = ...,  # mypy doesn't support ellipsis
    ) -> None:
        ...
        # 路由调度器实例
        self._router = UrlDispatcher()
        # 传递给 RequestHandler 的字典参数
        self._handler_args = handler_args
        self.logger = logger

        self._middlewares: _Middlewares = FrozenList(middlewares)

        # initialized on freezing
        self._middlewares_handlers: _MiddlewaresHandlers = tuple()
        # initialized on freezing
        self._run_middlewares: Optional[bool] = None
        # 存储应用配置变量
        self._state: Dict[Union[AppKey[Any], str], object] = {}
        self._frozen = False
        self._pre_frozen = False
        self._subapps: _Subapps = []
        # 下面是信号机制相关，在执行过程中被调用，附加额外功能
        self._on_response_prepare: _RespPrepareSignal = Signal(self)
        self._on_startup: _AppSignal = Signal(self)
        self._on_shutdown: _AppSignal = Signal(self)
        self._on_cleanup: _AppSignal = Signal(self)
        self._cleanup_ctx = CleanupContext()
        self._on_startup.append(self._cleanup_ctx._on_startup)
        self._on_cleanup.append(self._cleanup_ctx._on_cleanup)
        # 客户端请求的最大大小
        self._client_max_size = client_max_size
```
`Application`可以方便地存储和读取类似全局变量的`Application`配置，使用样例如下：
```python
my_private_key = web.AppKey("my_private_key", str)
app[my_private_key] = data

async def handler(request: web.Request):
    data = request.app[my_private_key]
    # reveal_type(data) -> str
```
存储和读取变量的底层数据结构是`self._state = {}`，源码如下：
```python
@overload  # type: ignore[override]
def __getitem__(self, key: AppKey[_T]) -> _T: ...

@overload
def __getitem__(self, key: str) -> Any: ...

def __getitem__(self, key: Union[str, AppKey[_T]]) -> Any:
    return self._state[key]

def _check_frozen(self) -> None:
    if self._frozen:
        raise RuntimeError(
            "Changing state of started or joined " "application is forbidden"
        )

@overload  # type: ignore[override]
def __setitem__(self, key: AppKey[_T], value: _T) -> None: ...

@overload
def __setitem__(self, key: str, value: Any) -> None: ...

def __setitem__(self, key: Union[str, AppKey[_T]], value: Any) -> None:
    self._check_frozen()
    ...
    self._state[key] = value

def __delitem__(self, key: Union[str, AppKey[_T]]) -> None:
    self._check_frozen()
    del self._state[key]

@overload  # type: ignore[override]
def get(self, key: AppKey[_T], default: None = ...) -> Optional[_T]: ...

@overload
def get(self, key: AppKey[_T], default: _U) -> Union[_T, _U]: ...

@overload
def get(self, key: str, default: Any = ...) -> Any: ...

def get(self, key: Union[str, AppKey[_T]], default: Any = None) -> Any:
    return self._state.get(key, default)
```
`Application`支持中间件机制，中间件有如下作用或特点：
+ 自定义`handler`的行为。
+ 中间件是一个协程，可以用以修改请求或者响应。
+ 中间件接收两个参数：`request`和`handler`，返回一个`response`。
+ 如果传递多个中间件，则中间件的调用链在`handler()`之后按逆序，在`handler()` 之前按顺序。

使用样例如下（如果`aiohttp`版本`>= 4`，则下面的装饰器`@web.middleware`可以去掉）：
```python
from aiohttp import web

async def test(request):
    print('Handler function called')
    return web.Response(text="Hello")

@web.middleware
async def middleware1(request, handler):
    print('Middleware 1 called')
    response = await handler(request)
    print('Middleware 1 finished')
    return response

@web.middleware
async def middleware2(request, handler):
    print('Middleware 2 called')
    response = await handler(request)
    print('Middleware 2 finished')
    return response


app = web.Application(middlewares=[middleware1, middleware2])
app.router.add_get('/', test)
web.run_app(app)
```
例中`test`是用户定义的`handler`，`middleware1`和`middleware2`是中间件，运行结果如下：
```bash
======== Running on http://0.0.0.0:8080 ========
(Press CTRL+C to quit)
Middleware 1 called
Middleware 2 called
Handler function called
Middleware 2 finished
Middleware 1 finished
```
中间件的相关源码如下：
```python
def _fix_request_current_app(app: "Application") -> Middleware:
    async def impl(request: Request, handler: Handler) -> StreamResponse:
        with request.match_info.set_current_app(app):
            return await handler(request)
    return impl

def _prepare_middleware(self) -> Iterator[Middleware]:
    yield from reversed(self._middlewares)
    # 增加一个中间件 (https://github.com/aio-libs/aiohttp/pull/2550)
    # TODO: 等后面请求模块梳理完了，在补充解释这个bug
    yield _fix_request_current_app(self)

async def _handle(self, request: Request) -> StreamResponse:
    match_info = await self._router.resolve(request)
    match_info.add_app(self)
    match_info.freeze()
    resp = None
    request._match_info = match_info
    expect = request.headers.get(hdrs.EXPECT)
    if expect:
        resp = await match_info.expect_handler(request)
        await request.writer.drain()
    if resp is None:
        handler = match_info.handler
        if self._run_middlewares:
            for app in match_info.apps[::-1]:
                assert app.pre_frozen, "middleware handlers are not ready"
                for m in app._middlewares_handlers:
                    # 更新 partial(m, handler=handler) 方法一些属性，使其像 handler一样，
                    # 返回更新后的 partial(m, handler=handler) 方法
                    handler = update_wrapper(partial(m, handler=handler), handler)
        # 如果有中间件，这里的 handler 是最终更新后的 partial(m ,handler) 方法
        resp = await handler(request)
    return resp

def pre_freeze(self) -> None:
    ...
    self._middlewares_handlers = tuple(self._prepare_middleware())
    self._run_middlewares = True if self.middlewares else False
    for subapp in self._subapps:
        subapp.pre_freeze()
        self._run_middlewares = self._run_middlewares or subapp._run_middlewares
```
根据源码可知，中间件机制的执行流程如下：
+ 初始化时候调用`pre_freeze`方法，其中会完成`self._middlewares_handlers`和`self._run_middlewares`变量的更新。
用以更新`self._middlewares_handlers`变量的`self._prepare_middleware`方法是一个生成器，按照参数`self._middlewares`
的逆序生成中间件调用链。
+ 当有客户端发送的请求时，会调用`self._handle`方法处理。如果有中间件，则按初始化阶段构造的顺序，包装生成一个新的
`handler`用以处理请求。

除了中间件机制外，`Application`也提供了如下的信号机制：
+ `on_response_prepare`：在`response`准备阶段被调用，具体来说就是在准备完`headers`和发送`headers`之前调用。
+ `on_startup`：在应用的启动阶段也就是`setup`阶段被调用。
+ `on_cleanup`：在服务关闭阶段被调用。
+ `on_shutdown`：在服务关闭阶段被调用，但需要在`on_cleanup`之前执行。

信号`on_response_prepare`使用样例如下：
```python
async def on_prepare(request, response):
    response.headers['My-Header'] = 'value'

app.on_response_prepare.append(on_prepare)
```
由于`on_startup`和`on_cleanup`信号对有陷阱，例如在`on_startup`信号中注册有`[create_pg, create_redis]`，
在`on_cleanup`信号中注册有`[dispose_pg, dispose_redis]`，如果`create_pg(app)`执行失败，则`create_redis(app)`不会被执行，
但在服务关闭阶段执行`on_cleanup`信号注册的方法时候，`[dispose_pg, dispose_redis]`都会被执行，这时候就会出错。
解决办法就是`Application`提供了一种新的信号：
+ `cleanup_ctx`：此信号注册的方法确保了只有在 `startup` 阶段执行成功的方法，才会在`cleanup`阶段执行。

信号机制相关的源码如下：
```python
@property
def on_response_prepare(self) -> _RespPrepareSignal:
    return self._on_response_prepare

@property
def on_startup(self) -> _AppSignal:
    return self._on_startup

@property
def on_shutdown(self) -> _AppSignal:
    return self._on_shutdown

@property
def on_cleanup(self) -> _AppSignal:
    return self._on_cleanup

@property
def cleanup_ctx(self) -> "CleanupContext":
    return self._cleanup_ctx

async def startup(self) -> None:
    """Causes on_startup signal

    Should be called in the event loop along with the request handler.
    """
    await self.on_startup.send(self)

async def shutdown(self) -> None:
    """Causes on_shutdown signal

    Should be called before cleanup()
    """
    await self.on_shutdown.send(self)

async def cleanup(self) -> None:
    """Causes on_cleanup signal

    Should be called after shutdown()
    """
    if self.on_cleanup.frozen:
        await self.on_cleanup.send(self)
    else:
        # If an exception occurs in startup, ensure cleanup contexts are completed.
        await self._cleanup_ctx._on_cleanup(self)
```
根据源码和初始化部分可知，每一种信号都是`aiosignal.Signal`类，其源码如下：
```python
class Signal(FrozenList):
    """Coroutine-based signal implementation.

    To connect a callback to a signal, use any list method.

    Signals are fired using the send() coroutine, which takes named
    arguments.
    """

    __slots__ = ("_owner",)

    def __init__(self, owner):
        super().__init__()
        self._owner = owner

    ...

    async def send(self, *args, **kwargs):
        """
        Sends data to all registered receivers.
        """
        if not self.frozen:
            raise RuntimeError("Cannot send non-frozen signal.")

        for receiver in self:
            await receiver(*args, **kwargs)  # type: ignore
```
在初始化阶段有如下设置：
```python
self._on_startup.append(self._cleanup_ctx._on_startup)
self._on_cleanup.append(self._cleanup_ctx._on_cleanup)
```
上述代码确保了在`cleanup_ctx`信号注册的方法在`start`和`cleanup`阶段被正常执行。`CleanupContext`的源码如下：
```python
class CleanupContext(_CleanupContextBase):
    def __init__(self) -> None:
        super().__init__()
        self._exits: List[AsyncIterator[None]] = []

    async def _on_startup(self, app: Application) -> None:
        for cb in self:
            it = cb(app).__aiter__()
            await it.__anext__()
            self._exits.append(it)

    async def _on_cleanup(self, app: Application) -> None:
        errors = []
        for it in reversed(self._exits):
            try:
                await it.__anext__()
            except StopAsyncIteration:
                pass
            except Exception as exc:
                errors.append(exc)
            else:
                errors.append(RuntimeError(f"{it!r} has more than one 'yield'"))
        if errors:
            if len(errors) == 1:
                raise errors[0]
            else:
                raise CleanupError("Multiple errors on cleanup stage", errors)
```
最后`Application`也提供了嵌套应用的机制。

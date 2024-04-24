# Application
![应用框架](./images/application.png)
上图显示了`Application`对象的大体结构，下面将分别介绍`application`、**路由调度器**、
**资源**和**资源路由**对象。
## application
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
### 变量存储与获取
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
### 中间件机制
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

### 信号机制
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
根据`CleanupContext`源码可知，被注册的方法必须是只有一个`yield`表达式的异步生成器。**异步生成器**是指：
使用`async def`定义一个函数，并在函数内部使用`yield`语句来产生值，其允许在生成值的过程中进行异步操作。样例如下：
```python
async def pg_engine(app: web.Application):
    # 异步操作
    app[pg_engine] = await create_async_engine(
        "postgresql+asyncpg://postgre:@localhost:5432/postgre"
    )
    # 生成值
    yield
    await app[pg_engine].dispose()

app.cleanup_ctx.append(pg_engine)
```
源码中`__aiter__()`会返回一个异步生成器对象，`__anext__()`方法会开始异常生成器的执行，一直到`yield`处暂停，
如果没有`yield`表达式，则抛出`StopAsyncIteration`异常。<br>

### 应用嵌套
`Application`也提供了嵌套应用的机制。样例如下：
```python
admin = web.Application()
admin.add_routes([web.get('/resource', handler, name='name')])

app.add_subapp('/admin/', admin)

url = admin.router['name'].url_for()
# URL('/admin/resource')
```
和嵌套应用相关的源码如下：
```python
def _reg_subapp_signals(self, subapp: "Application") -> None:
    def reg_handler(signame: str) -> None:
        subsig = getattr(subapp, signame)

        async def handler(app: "Application") -> None:
            await subsig.send(subapp)

        appsig = getattr(self, signame)
        appsig.append(handler)

    reg_handler("on_startup")
    reg_handler("on_shutdown")
    reg_handler("on_cleanup")

def add_subapp(self, prefix: str, subapp: "Application") -> AbstractResource:
    if not isinstance(prefix, str):
        raise TypeError("Prefix must be str")
    prefix = prefix.rstrip("/")
    if not prefix:
        raise ValueError("Prefix cannot be empty")
    factory = partial(PrefixedSubAppResource, prefix, subapp)
    return self._add_subapp(factory, subapp)

def _add_subapp(
    self, resource_factory: Callable[[], AbstractResource], subapp: "Application"
) -> AbstractResource:
    if self.frozen:
        raise RuntimeError("Cannot add sub application to frozen application")
    if subapp.frozen:
        raise RuntimeError("Cannot add frozen application"
    resource = resource_factory()
    self.router.register_resource(resource)
    self._reg_subapp_signals(subapp)
    self._subapps.append(subapp)
    subapp.pre_freeze()
    return resource

def add_domain(self, domain: str, subapp: "Application") -> AbstractResource:
    if not isinstance(domain, str):
        raise TypeError("Domain must be str")
    elif "*" in domain:
        rule: Domain = MaskDomain(domain)
    else:
        rule = Domain(domain)
    factory = partial(MatchedSubAppResource, rule, subapp)
    return self._add_subapp(factory, subapp)
```
TODO 等下面的资源梳理完来，在解释嵌套应用的实现原理

### 路由调度器对象
`Application`提供路由调度器实例属性，相关源码如下：
```python
self._router = UrlDispatcher()

def add_routes(self, routes: Iterable[AbstractRouteDef]) -> List[AbstractRoute]:
    return self.router.add_routes(routes)

@property
def router(self) -> UrlDispatcher:
    return self._router
```
路由调度器完成路由表的建立与查询。

## 路由调度器
路由调度器`UrlDispatcher`初始化源码如下：
```python
class UrlDispatcher(AbstractRouter, Mapping[str, AbstractResource]):
    NAME_SPLIT_RE = re.compile(r"[.:-]")
    HTTP_NOT_FOUND = HTTPNotFound()

    def __init__(self) -> None:
        super().__init__()
        # 用于存储所有的路由表项
        self._resources: List[AbstractResource] = []
        # 只存储具名的路由表项
        self._named_resources: Dict[str, AbstractResource] = {}
        # 建立路由索引和路由表项关系映射，用于后续的路由选择
        self._resource_index: dict[str, list[AbstractResource]] = {}
        # 存储子app相关的路由表项
        self._matched_sub_app_resources: List[MatchedSubAppResource] = []
```
初始化阶段主要完成用于存储注册的路由表项的数据结构（注册添加的每一项路由规则都对应一个资源，也即一个路由表项）。
### 路由表建立
路由调度器`UrlDispatcher`提供来三种不同的路由项注册能力：http 请求方法路由项、静态资源路由项和基于类视图路由项。<br>

用于 http 请求方法路由项注册的样例如下：
```python
async def hello(request):
    return web.Response(text="Hello, world")

app.router.add_get('/', hello) # 注册一个路由项，也即注册一个资源
```
相关源码实现如下：
```python
def add_head(self, path: str, handler: Handler, **kwargs: Any) -> AbstractRoute:
        """Shortcut for add_route with method HEAD."""
        return self.add_route(hdrs.METH_HEAD, path, handler, **kwargs)

def add_options(self, path: str, handler: Handler, **kwargs: Any) -> AbstractRoute:
    """Shortcut for add_route with method OPTIONS."""
    return self.add_route(hdrs.METH_OPTIONS, path, handler, **kwargs)

def add_get(
    self,
    path: str,
    handler: Handler,
    *,
    name: Optional[str] = None,
    allow_head: bool = True,
    **kwargs: Any,
) -> AbstractRoute:
    """Shortcut for add_route with method GET.

    If allow_head is true, another
    route is added allowing head requests to the same endpoint.
    """
    resource = self.add_resource(path, name=name)
    if allow_head:
        resource.add_route(hdrs.METH_HEAD, handler, **kwargs)
    return resource.add_route(hdrs.METH_GET, handler, **kwargs)

def add_post(self, path: str, handler: Handler, **kwargs: Any) -> AbstractRoute:
    """Shortcut for add_route with method POST."""
    return self.add_route(hdrs.METH_POST, path, handler, **kwargs)

def add_put(self, path: str, handler: Handler, **kwargs: Any) -> AbstractRoute:
    """Shortcut for add_route with method PUT."""
    return self.add_route(hdrs.METH_PUT, path, handler, **kwargs)

def add_patch(self, path: str, handler: Handler, **kwargs: Any) -> AbstractRoute:
    """Shortcut for add_route with method PATCH."""
    return self.add_route(hdrs.METH_PATCH, path, handler, **kwargs)

def add_delete(self, path: str, handler: Handler, **kwargs: Any) -> AbstractRoute:
    """Shortcut for add_route with method DELETE."""
    return self.add_route(hdrs.METH_DELETE, path, handler, **kwargs)
```
从源码可知，`add_xxx`方法内部会调用`self.add_route`方法（`self.add_get`调用逻辑其实就是`self.add_route`方法内部逻辑），
`self.add_route`源码如下：
```python
def add_route(
    self,
    method: str,
    path: str,
    handler: Union[Handler, Type[AbstractView]],
    *,
    name: Optional[str] = None,
    expect_handler: Optional[_ExpectHandler] = None,
) -> AbstractRoute:
    resource = self.add_resource(path, name=name)
    return resource.add_route(method, handler, expect_handler=expect_handler)

def add_resource(self, path: str, *, name: Optional[str] = None) -> Resource:
    if path and not path.startswith("/"):
        raise ValueError("path should be started with / or be empty")
    # Reuse last added resource if path and name are the same
    # 如果连续两次注册路由表项是同一个 name 和同一个 path，只是方法不同，
    # 例如: app.router.add_get("/run", get), app.router.add_post("/run", post)，
    # 则共用一个资源（路由表项）
    if self._resources:
        resource = self._resources[-1]
        if resource.name == name and resource.raw_match(path):
            return cast(Resource, resource)
    if not ("{" in path or "}" in path or ROUTE_RE.search(path)):
        resource = PlainResource(_requote_path(path), name=name)
        self.register_resource(resource)
        return resource
    # 注册的 path 有 {}，例如 "/run/{name}"
    resource = DynamicResource(path, name=name)
    self.register_resource(resource)
    return resource

def register_resource(self, resource: AbstractResource) -> None:
    ...
    name = resource.name

    if name is not None:
        ...
        if name in self._named_resources:
            raise ValueError(
                "Duplicate {!r}, "
                "already handled by {!r}".format(name, self._named_resources[name])
            )
        # 记录具名资源（路由表项）
        self._named_resources[name] = resource
    # 记录资源（路由表项）
    self._resources.append(resource)
    if isinstance(resource, MatchedSubAppResource):
        # We cannot index match sub-app resources because they have match rules
        # 记录子 app 资源（路由表项）
        self._matched_sub_app_resources.append(resource)
    else:
        # 记录路由索引和路由表项（资源）关系
        self.index_resource(resource)

def _get_resource_index_key(self, resource: AbstractResource) -> str:
    """Return a key to index the resource in the resource index."""
    # strip at the first { to allow for variables
    # 提取固定路径，例如 "/run/{name}" 则得到 "/run"作为索引
    return resource.canonical.partition("{")[0].rstrip("/") or "/"

def index_resource(self, resource: AbstractResource) -> None:
    """Add a resource to the resource index."""
    resource_key = self._get_resource_index_key(resource)
    # There may be multiple resources for a canonical path
    # so we keep them in a list to ensure that registration
    # order is respected.
    self._resource_index.setdefault(resource_key, []).append(resource)
```
由源码可知，注册的每一个路由项，在内部都作为一个资源，例如`PlainResource`、
`DynamicResource`、`MatchedSubAppResource`等资源。资源的内部是如何实现的，
我们在下一小节进行介绍。`self.add_route`注册完资源后，接下来会调用`resource.add_route`方法将具体请求方法、
`handler`等信息和资源绑定。

下面看下用于类视图路由项注册。使用样例如下：
```python
class MyView(web.View):
    async def get(self):
        return await get_resp(self.request)

    async def post(self):
        return await post_resp(self.request)
# Example will process GET and POST requests for /path/to
# but raise 405 Method not allowed exception for unimplemented HTTP methods
web.view('/path/to', MyView)
```
相关源码实现如下：
```python
def add_view(
    self, path: str, handler: Type[AbstractView], **kwargs: Any
) -> AbstractRoute:
    """Shortcut for add_route with ANY methods for a class-based view."""
    return self.add_route(hdrs.METH_ANY, path, handler, **kwargs)
```
`self.add_view`内部也是调用`self.add_route`，请求方法是所有的方法。`web.View`实现如下：
```python
class AbstractView(ABC):
    """Abstract class based view."""

    def __init__(self, request: Request) -> None:
        # 被调用也就是被实例化时候，接收一个 request 参数
        self._request = request

    @property
    def request(self) -> Request:
        """Request instance."""
        return self._request

    @abstractmethod
    def __await__(self) -> Generator[Any, None, StreamResponse]:
        """Execute the view handler."""

class View(AbstractView):
    async def _iter(self) -> StreamResponse:
        if self.request.method not in hdrs.METH_ALL:
            self._raise_allowed_methods()
        # 获取和请求方法同名的 handle 属性，例如 MyView.get
        method: Optional[Callable[[], Awaitable[StreamResponse]]] = getattr(
            self, self.request.method.lower(), None
        )
        if method is None:
            self._raise_allowed_methods()
        return await method()

    def __await__(self) -> Generator[Any, None, StreamResponse]:
        return self._iter().__await__()

    def _raise_allowed_methods(self) -> NoReturn:
        allowed_methods = {m for m in hdrs.METH_ALL if hasattr(self, m.lower())}
        raise HTTPMethodNotAllowed(self.request.method, allowed_methods)
```
最后看一下用于静态资源路由项注册。使用样例如下：
```python
router.add_static("/static", path_to_static_folder)
```
源码实现如下：
```python
def add_static(
    self,
    prefix: str,
    path: PathLike,
    *,
    name: Optional[str] = None,
    expect_handler: Optional[_ExpectHandler] = None,
    chunk_size: int = 256 * 1024,
    show_index: bool = False,
    follow_symlinks: bool = False,
    append_version: bool = False,
) -> AbstractResource:
    """Add static files view.

    prefix - url prefix
    path - folder with files

    """
    assert prefix.startswith("/")
    if prefix.endswith("/"):
        prefix = prefix[:-1]
    resource = StaticResource(
        prefix,
        path,
        name=name,
        expect_handler=expect_handler,
        chunk_size=chunk_size,
        show_index=show_index,
        follow_symlinks=follow_symlinks,
        append_version=append_version,
    )
    self.register_resource(resource)
    return resource
```
从源码可知，`add_static`主要使用`StaticResource`资源，将在下一小节介绍，
最后将资源添加到路由表中。

路由调度器`UrlDispatcher`也提供了批量注册路由项的接口，源码如下：
```python
def add_routes(self, routes: Iterable[AbstractRouteDef]) -> List[AbstractRoute]:
    """Append routes to route table.

    Parameter should be a sequence of RouteDef objects.

    Returns a list of registered AbstractRoute instances.
    """
    registered_routes = []
    for route_def in routes:
        registered_routes.extend(route_def.register(self))
    return registered_routes
```
使用样例如下：
```python
app.add_routes([web.get('/path1', get_1),
                web.post('/path1', post_1),
                web.get('/path2', get_2),
                web.post('/path2', post_2)]
```

### 路由表检索
路由表检索就是根据请求的`path`从路由表中找到最佳的匹配资源（路由项），
进而找到注册的处理请求`handler`。相关源码如下：
```python
async def resolve(self, request: Request) -> UrlMappingMatchInfo:
    resource_index = self._resource_index
    allowed_methods: Set[str] = set()

    # Walk the url parts looking for candidates. We walk the url backwards
    # to ensure the most explicit match is found first. If there are multiple
    # candidates for a given url part because there are multiple resources
    # registered for the same canonical path, we resolve them in a linear
    # fashion to ensure registration order is respected.
    url_part = request.rel_url.raw_path
    while url_part:
        for candidate in resource_index.get(url_part, ()):
            match_dict, allowed = await candidate.resolve(request)
            if match_dict is not None:
                return match_dict
            else:
                allowed_methods |= allowed
        if url_part == "/":
            break
        url_part = url_part.rpartition("/")[0] or "/"

    #
    # We didn't find any candidates, so we'll try the matched sub-app
    # resources which we have to walk in a linear fashion because they
    # have regex/wildcard match rules and we cannot index them.
    #
    # For most cases we do not expect there to be many of these since
    # currently they are only added by `add_domain`
    #
    for resource in self._matched_sub_app_resources:
        match_dict, allowed = await resource.resolve(request)
        if match_dict is not None:
            return match_dict
        else:
            allowed_methods |= allowed

    if allowed_methods:
        return MatchInfoError(HTTPMethodNotAllowed(request.method, allowed_methods))

    return MatchInfoError(self.HTTP_NOT_FOUND)
```

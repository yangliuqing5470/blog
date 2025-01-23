# 引言
我们以一个简单的`http server`样例来窥探`aiohttp`服务端框架的实现原理，下面是样例代码：
```python
from aiohttp import web

async def hello(request):
    return web.Response(text="Hello, world")

app = web.Application()
app.add_routes([web.get('/', hello)])

web.run_app(app)
```
样例代码可知，基于`aiohttp`实现的`http server`主要分三部分：
+ `Application` 对象构建；
  ```python
  app = web.Application()
  ```
+ 添加路由规则，创建路由表；
  ```python
  app.add_routes([web.get("/", hello)])
  ```
+ 启动服务运行；
  ```python
  web.run_app(app)
  ```
# Web-Server 框架
一个`web server`的核心对象是`Application`对象。`Application`对象通常实现了如下能力：
+ 路由表：定义`URL`路径与处理函数的映射。
+ 中间件：在请求和响应之间执行额外的逻辑，比如身份验证、日志记录。
+ 全局配置：存储应用级别的配置，如数据库连接、`API`密钥等。
+ 资源生命周期管理：管理应用的启动和关闭时需要初始化或清理的资源，如连接池。

`AppRunner`用于管理`Application`对象的启动、运行和停止。为`Application`创建一个服务端的运行环境。
+ `aiohttp`是**基于`asyncio`的`transports`和`protocols`模式**实现。
+ `AppRunner`核心是构建一个`protocol`。实现了类似`connection_made`、`connection_lost`等协议方法。
这些协议方法用于驱动`Application`对象的启动，运行和停止。

`TCPSite`、`UnixSite`和`SockSite`负责绑定监听指定的`IP`地址和端口。为`Application`提供了网络访问能力。

下面给出`Application`、`AppRunner`和`TCPSite`样例代码：
```python
from aiohttp import web

async def handle(request):
    return web.Response(text="Hello, TCPSite!")

# 创建 Application 对象
app = web.Application()
app.router.add_get("/", handle) # 添加路由

# 创建 AppRunner 对象
runner = web.AppRunner(app)
await runner.setup()            # 启动 runner

# 创建 TCPSite，绑定到 localhost:8080
site = web.TCPSite(runner, "localhost", 8080)
await site.start()              # 启动监听
```

## Application
`Application`对象需要实现如下能力：
+ 路由表：定义`URL`路径与处理函数的映射。
+ 中间件：在请求和响应之间执行额外的逻辑，比如身份验证、日志记录。
+ 全局配置：存储应用级别的配置，如数据库连接、`API`密钥等。
+ 资源生命周期管理：管理应用的启动和关闭时需要初始化或清理的资源，如连接池。

### 全局配置
`Application`对象可以方便管理应用级别的相关配置变量。使用样例如下：
```python
# 声明全局变量名
my_private_key = web.AppKey("my_private_key", str)
# 存储全局变量
app[my_private_key] = data

async def handler(request: web.Request):
    # 读取全局变量
    data = request.app[my_private_key]
```
其中`my_private_key`变量是一个应用的全局配置变量。变量名可以是`str`类型或者`web.AppKey`类型。在底层实现中，
`Application`内部有一个字典变量用于存储所有的全局变量：
```python
self._state: Dict[Union[AppKey[Any], str], object] = {}
```
`Application`通过实现如下的方法，实现变量的存储，读取和删除等操作。
```python
def __getitem__(self, key: Union[str, AppKey[_T]]) -> Any:
    return self._state[key]

def __setitem__(self, key: Union[str, AppKey[_T]], value: Any) -> None:
    ...
    self._state[key] = value

def __delitem__(self, key: Union[str, AppKey[_T]]) -> None:
    ...
    del self._state[key]
```
### 中间件
`Middleware`是处理请求和响应的钩子，可以用来**在请求处理之前或响应处理之后执行一些通用逻辑**。
+ `Middleware`是协程函数，接收两个参数`request`和`handler`，返回一个修改后的`Response`对象。
  ```python
  @middleware
  async def middleware(request, handler):
      resp = await handler(request)
      # 修改响应
      resp.text = resp.text + ' wink'
      return resp

  # request：客户端发来的 HTTP 请求，可以通过 request 修改或提取请求信息。
  # handler：自定义的路由处理函数，一个协程。
  ```
+ 传递多个`Middleware`，则中间件的调用链在`handler`之后按逆序，在`handler`之前按顺序。
  ```python
  from aiohttp import web
  
  async def handler(request):
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
  app.router.add_get('/', handler)
  web.run_app(app)

  ------------------------执行结果-------------------------------
  ======== Running on http://0.0.0.0:8080 ========
  (Press CTRL+C to quit)
  Middleware 1 called
  Middleware 2 called
  Handler function called
  Middleware 2 finished
  Middleware 1 finished
  ```

中间件的工作原理总结如下：

![middleware工作原理](./images/middlewares原理.png)

上述中的`1`和`2`步是`Application`启动初始化阶段。`3`和`4`步是处理客户端请求阶段。关注下**固定添加**的内部中间件 `_fix_request_current_app`实现如下：
```python
# 将请求中匹配的`app`对象强制设置为当前app
def _fix_request_current_app(app: "Application") -> Middleware:
    @middleware
    async def impl(request: Request, handler: Handler) -> StreamResponse:
        match_info = request.match_info
        prev = match_info.current_app
        match_info.current_app = app
        try:
            return await handler(request)
        finally:
            match_info.current_app = prev

    return impl
```
如果当前`app`有`subapp`，且路由匹配到`subapp`。因为默认的`request.match_info.current_app`是`subapp`，
这时候`app`中的中间件看到的`request.match_info.app`是`subapp`而不是`app`，所以增加一个额外的中间件，放在构建顺序后末尾，
用于设置`request.match_info.current_app`为`app`。**每一个`app`的中间件看到的`app`不应该是其它`app`**。

第`3`步中包装最终要执行的`handler`实现如下：
```python
# subapp 到 app 执行顺序
for app in match_info.apps[::-1]:
    # 处理每一个 app 的所有中间件
    for m, new_style in app._middlewares_handlers:
        if new_style:
            # update_wrapper 方法将 handler 对象属性都设置到 partial(m, handler=handler) 对象中，
            # 使得 partial(m, handler=handler) 对象看起来像 handler 对象。
            # 可以保持可读性和调试信息。

            # partial 函数返回一个新的函数，这个函数会把预先绑定的参数传递给原函数，
            # 调用这个新函数时，会将剩余的参数与预绑定的参数合并后调用原函数。
            # 例如正常调中间件 m(request, handler)。a = partial(m, handler=handler)，
            # 则 a(request) 等效 m(request, handler=handler)
            handler = update_wrapper(partial(m, handler=handler), handler)
        else:
            # 老版本的中间件，参数是app和handler
            handler = await m(app, handler)
```
所以在上述多个中间件样例中，如果参数`middlewares=[middleware1, middleware2]`，则可以将最终要执行的 `handler(request)`等效为：
```python
# 下面考虑内部的 _fix_request_current_app 中间件。
async def handler(request):
    async def inner1(request):
        return await middleware2(request, handler=route_handler)

    async def inner2(request):
        return await middleware1(request, handler=inner1)

    async def inner3(request):
        return await _fix_request_current_app(app)(request, handler=inner2)

    return await inner3(request)
```
这里就解释了多个中间件的调用链在`handler`之后按逆序，在`handler`之前按顺序。

当然，如果每次处理请求`request`都实时包装最终处理的`handler`比较耗时。`aiohttp`对一个`Application`包装的最终`handler`使用了`LRU`缓存，
这样不需要每次都实时包装，而是直接从缓存取第一次包装好的`handler`。
```python
# 每次尝试从缓存获取包装的 handler
handler = _cached_build_middleware(handler, match_info.apps)

_cached_build_middleware = lru_cache(maxsize=1024)(_build_middlewares)
def _build_middlewares(
    handler: Handler, apps: Tuple["Application", ...]
) -> Callable[[Request], Awaitable[StreamResponse]]:
    """Apply middlewares to handler."""
    for app in apps[::-1]:
        for m, _ in app._middlewares_handlers:  # type: ignore[union-attr]
            handler = update_wrapper(partial(m, handler=handler), handler)  # type: ignore[misc]
    return handler
```
其中缓存中的`key`是`_build_middlewares`函数的输入参数。

### 资源生命周期管理
为了管理`Application`启动和关闭时需要初始化或清理的资源，`aiohttp`提供了**信号机制**。如下所示：
+ `on_response_prepare`：在`Response`准备阶段被调用，具体来说是在准备完`headers`和发送`headers`之前调用。
+ `on_startup`：在`Application`的启动阶段，也就是`AppRunner.setup`阶段被调用。
+ `on_cleanup`：在服务关闭阶段被调用。
+ `on_shutdown`：在服务关闭阶段被调用，但需要在`on_cleanup`之前执行。
+ `cleanup_ctx`：此信号注册的方法确保了只有在`startup`阶段执行成功的方法，才会在`cleanup`阶段执行。
  > `on_startup`和`on_cleanup`信号对有缺陷。例如，在`on_startup`信号中注册`[create_pg, create_redis]`，
  在`on_cleanup`信号中注册`[dispose_pg, dispose_redis]`。若`create_pg`执行失败，则 `create_redis`不会被执行，
  但在服务关闭阶段执行`on_cleanup`信号注册的方法时，`[dispose_pg, dispose_redis]`都会被执行，这时候就会出错。
  信号`cleanup_ctx`就是为解决这个问题。

添加使用自定义信号样例如下：
```python
async def on_prepare(request, response):
    response.headers['My-Header'] = 'value'
# 注册 on_response_prepare 信号
app.on_response_prepare.append(on_prepare)

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
pg_engine = web.AppKey("pg_engine", AsyncEngine)
async def create_pg(app):
    app[pg_engine] = await create_async_engine(
        "postgresql+asyncpg://postgre:@localhost:5432/postgre"
    )
async def dispose_pg(app):
    await app[pg_engine].dispose()
# 注册 on_startup 信号
app.on_startup.append(create_pg)
# 注册 on_cleanup 信号
app.on_cleanup.append(dispose_pg)

async def pg_engine(app: web.Application):
    app[pg_engine] = await create_async_engine(
        "postgresql+asyncpg://postgre:@localhost:5432/postgre"
    )
    yield
    await app[pg_engine].dispose()
# 注册 cleanup_ctx 信号
app.cleanup_ctx.append(pg_engine)
```
每一个注册的信号方法都是一个异步函数，不同信号的接口定义如下：
```python
# on_response_prepare 信号，参数是 Request 和 Response 对象
async def on_prepare(request, response):
    pass
# on_startup 信号，参数是 Application 对象
async def on_startup(app):
    pass
# on_cleanup 信号，参数是 Application 对象
async def on_cleanup(app):
    pass
# on_shutdown 信号，参数是 Application 对象
async def on_shutdown(app):
    pass
# cleanup_ctx 信号，参数是 Application 对象
async def cleanup_ctx(app):
    pass
```
信号机制工作的本质就是：**框架给用户提供接口以在服务运行的适当时机执行自定义的逻辑**。

在`Application`的实现中，除了`cleanup_ctx`信号，其它所有信号都是`aiosignal`库的`Signal`类。其源码如下：
```python
# 只列出核心的 send 方法。send 方法用来执行注册的所有方法
class Signal(FrozenList):
    def __init__(self, owner):
        super().__init__()
        self._owner = owner

    async def send(self, *args, **kwargs):
        """
        Sends data to all registered receivers.
        """
        if not self.frozen:
            raise RuntimeError("Cannot send non-frozen signal.")

        for receiver in self:
            await receiver(*args, **kwargs)  # type: ignore
```
`Signal`类是`FrozenList`的子类，所以信号的注册其实就是往列表添加相关方法。信号方法的实际执行其实就是调用`Signal.send`方法。
```python
# Application 实现的执行 startup 信号方法
async def startup(self) -> None:
    """Causes on_startup signal

    Should be called in the event loop along with the request handler.
    """
    await self.on_startup.send(self)
```
比较特殊的是`cleanup_ctx`信号，其内部实现是一个`CleanupContext`类，相关实现如下：
```python
# CleanupContext 也是 FrozenList 的子类
class CleanupContext(_CleanupContextBase):
    def __init__(self) -> None:
        super().__init__()
        self._exits: List[AsyncIterator[None]] = []
    # 在 Application 初始化时候，被添加到 on_startup 信号中
    async def _on_startup(self, app: Application) -> None:
        for cb in self:                   # 顺序执行
            it = cb(app).__aiter__()
            await it.__anext__()
            self._exits.append(it)
    # 在 Application 初始化时候，被添加到 on_cleanup 信号中
    async def _on_cleanup(self, app: Application) -> None:
        errors = []
        for it in reversed(self._exits):  # 逆序执行
            try:
                await it.__anext__()
            except StopAsyncIteration:
                pass
            except (Exception, asyncio.CancelledError) as exc:
                errors.append(exc)
            else:
                errors.append(RuntimeError(f"{it!r} has more than one 'yield'"))
        if errors:
            if len(errors) == 1:
                raise errors[0]
            else:
                raise CleanupError("Multiple errors on cleanup stage", errors)
```
`cleanup_ctx`信号的**核心逻辑**就是确保注册的所有`cleanup_ctx`信号方法，只有在`cleanup_ctx._on_startup`方法执行成功才会在`cleanup_ctx._on_cleanup`中被执行。

需要注意的是，`cleanup_ctx`信号方法必须是一个异步生成器，而且内部必须且只能有一个`yield`关键字。类似上述介绍的样例：
```python
# 一个异步生成器：async def 定义，内部只有一个 yield 的函数
async def pg_engine(app: web.Application):
    app[pg_engine] = await create_async_engine(
        "postgresql+asyncpg://postgre:@localhost:5432/postgre"
    )
    yield  # 在 asyncio 的 Task 中，yield 语句返回 None，则当前的协程任务会交出控制权给事件循环。
           # 事件循环会很快继续执行此协程任务，也就是 CleanupContext._on_startup 任务，直到完成。
           # 最终现象：CleanupContext._on_startup 只会执行 yield 之前的逻辑就结束。yield 之后的逻辑
           # 由 CleanupContext._on_cleanup 继续执行。
    await app[pg_engine].dispose()

app.cleanup_ctx.append(pg_engine)
```
在`yield`之前的逻辑在`startup`阶段执行，在`yield`之后的逻辑在`cleanup`阶段执行。

### 路由表
如前所述，路由表的作用是定义`URL`路径与处理函数的映射。路由表的核心是**路由表建立**和**路由表查询**。

在`Application`初始化的时候会实例化一个路由表对象：
```python
# Application 的路由表对象
router = UrlDispatcher()
```
下面是`Application`对象路由表数据存储和路由表建立大体流程：

![路由表结构及建立](./images/aiohttp-路由表结构.png)

路由表数据结构有四种：
+ `resources`：一个列表对象。每一个元素是一个路由项，也即一个`resource`。存放所有注册的`resource`。
+ `named_resources`：一个字典对象。存放以`name`为键，`resource`为值的映射。其中`name`是用户调用添加路由指定的。
可以通过`app.router[name]`获取对应的`resource`以反向构建`URL`。
  ```python
  @routes.get('/root', name='root')
  async def handler(request):
      ...
  # 构建 URL
  url = request.app.router['root'].url_for().with_query({"a": "b", "c": "d"})
  assert url == URL('/root?a=b&c=d')
  ```
+ `resource_index`：一个字典对象。存放以`path`固定前缀为键，`resource`为值的映射。其中值是一个列表，可以存放多个`resource`。
因为相同的`path`前缀可能注册多个路由项。
  ```bash
  例如`path="/run"`和`path="/run/{name}"`有相同的固定前缀`"/run`。
  ```
  用于路由表的快速检索。
+ `matched_sub_app_resources`：一个列表对象。存放匹配`subapp`的资源，也即`subapp`的路由项。

对于不同的`HTTP`请求方法，`app.router`路由对象提供了不同的路由注册方法。方法接口如下：
```python
# 参数 path 是指定的 uri。参数 handler 是 path 映射的请求处理函数。关键字参数 name 和 expect_handler
def add_head(self, path: str, handler: Handler, **kwargs: Any) -> AbstractRoute:
    pass

# 参数 path 是指定的 uri。参数 handler 是 path 映射的请求处理函数。关键字参数 name 和 expect_handler
def add_options(self, path: str, handler: Handler, **kwargs: Any) -> AbstractRoute:
    pass

def add_get(self, path: str, handler: Handler, *, name: Optional[str] = None, allow_head: bool = True, **kwargs: Any) -> AbstractRoute:
    pass

# 参数 path 是指定的 uri。参数 handler 是 path 映射的请求处理函数。关键字参数 name 和 expect_handler
def add_post(self, path: str, handler: Handler, **kwargs: Any) -> AbstractRoute:
    pass

# 参数 path 是指定的 uri。参数 handler 是 path 映射的请求处理函数。关键字参数 name 和 expect_handler
def add_put(self, path: str, handler: Handler, **kwargs: Any) -> AbstractRoute:
    pass

# 参数 path 是指定的 uri。参数 handler 是 path 映射的请求处理函数。关键字参数 name 和 expect_handler
def add_patch(self, path: str, handler: Handler, **kwargs: Any) -> AbstractRoute:
    pass

# 参数 path 是指定的 uri。参数 handler 是 path 映射的请求处理函数。关键字参数 name 和 expect_handler
def add_delete(self, path: str, handler: Handler, **kwargs: Any) -> AbstractRoute:
    pass
```
注册的每一个路由项（`resource`）根据指定的不同`path`有不同的实现：
+ `path`是固定路径，也就是不包含`{}`，例如`path="/run"`。对应的路由项是`PlainResource`类。
+ `path`包含变量，也就是含有`{}`，例如`path="/run/aaa{name}`。对应的路由项是`DynamicResource`类。

每一个`path`都会对应一个`resource`，除非通过`name`显示指定不同的值。一个`resource`可以注册多个不同的`HTTP`请求方法。
也就是说，一个`path`可以注册多个不同的`HTTP`请求方法。`resource`对象的数据结构如下：

![resource数据结构](./images/aiohttp-resource.png)

一个`resource`对象，包括子类`PlainResource`和`DynamicResource`等都会提供如下属性或方法：
```python
# 获取资源的规范化表示。返回一个用于反向生成 URL 的路径模板。
# 对于 PlainResource 返回 path。对于 DynamicResource，返回 URL 模版。
# 例如，若 path= "/run"，返回 "/run"。若 path = "/run/{name}/aaa"，返回 ”/run/{name}/aaa“。
# 若 path = "/run/{name:.*}/aaa"，返回 "/run/{name}/aaa"。
@property
def canonical(self) -> str:
    pass
# 给 path 的值添加前缀 prefix
def add_prefix(self, prefix: str) -> None:
    pass
# 比较参数 path 和注册使用的 path 是否相等
def raw_match(self, path: str) -> bool:
    pass
# 返回一个字典，表示资源的信息
# PlainResource 返回 {"path": self._path}
# DynamicResource 返回 return {"formatter": self._formatter, "pattern": self._pattern}
def get_info(self) -> _InfoDict:
    pass
# 构建 URL 对象并返回，会替换 path 中变量部分为具体值
def url_for(self, **parts: str) -> URL:
    pass
```
上面是路由表`app.router`对象的建立过程。下面介绍另一个核心功能**路由表检索**。

路由表检索的入口函数如下：
```python
# app.router 的方法
async def resolve(self, request: Request) -> UrlMappingMatchInfo:
    pass
```
路由检索的流程总结如下：

![路由检索流程](./images/aiohttp-路由检索.png)

如果请求`request`的路由检索成功，会返回`UrlMappingMatchInfo`对象。此对象是一个`dict`子类，可以像使用字典一样使用。
`UrlMappingMatchInfo`部分初始化如下：
```python
# 参数 match_dict 是 resource 成功匹配返回值。`PlainResource`资源返回 {}。`DynamicResource`资源返回字典
#    中的 key 是 path 中变量的名字，value 是变量具体的值。例，path = "/run/{name}"，
#    request.path = "/run/jack"，则返回 {"name": "jack"}
# 参数 route 是 resource 中对应注册方法的 route 对象，包含具体的请求处理方法等属性。
def __init__(self, match_dict: Dict[str, str], route: AbstractRoute) -> None:
    super().__init__(match_dict)
    ...
```
除此之外，`UrlMappingMatchInfo`还提供以下额外属性或方法：
+ 属性`handler`：返回匹配`route`对应的`handler`，也就是注册的请求处理函数。
+ 属性`route`：返回匹配的`route`对象。
+ 属性`expect_handler`：返回匹配的`route`对象的`handle_expect_header`方法。
+ 属性`http_exception`：`UrlMappingMatchInfo`对象返回`None`。`MatchInfoError`对象返回参数传递的 `http_exception`方法。
+ 属性`apps`：返回当前`UrlMappingMatchInfo`对象绑定的`Application`对象，返回结果是一个列表。
+ 属性`current_app`：读属性。返回当前`UrlMappingMatchInfo`对象绑定的**当前**`Application`对象。
+ 属性`current_app`：写属性。**设置**当前`UrlMappingMatchInfo`对象绑定的**当前**`Application`对象。
+ 方法`get_info`：返回匹配`route`对象的`get_info`方法返回值，返回一个字典对象，也即`resource`信息。
+ 方法`add_app`：注册`Application`对象，完成`UrlMappingMatchInfo`和`Application`的绑定。

除了上述介绍的常规的路由表建立和检索之外，`app.route`对象也提供了**语法糖基于类视图**方法添加路由。
```python
# 在 MyView 类中，需要实现 get、post、put 等 http 请求方法。
# 处理请求时，会根据请求方法，自动选择对应的请求处理函数
class MyView(web.View):
    async def get(self):
        return await get_resp(self.request)

    async def post(self):
        return await post_resp(self.request)
# Example will process GET and POST requests for /path/to
# but raise 405 Method not allowed exception for unimplemented HTTP methods
web.view('/path/to', MyView)
```

除了`HTTP`请求路由，`app.route`还支持处理**静态资源路由**，使用样例如下：
```python
from aiohttp import web

app = web.Application()

# 添加静态路由
app.router.add_static(
    prefix='/static/',  # URL 前缀
    path='/path/to/static/files',  # 静态文件所在目录
    name='static'  # 可选名称
)

web.run_app(app)
--------------------------------------------------------------------------------
# 访问路径 http://localhost:8080/static/example.css 会返回 example.css 文件内容
```
### 应用嵌套
`Application`对象还支持应用嵌套，也就是当前`app`可以有`subapp`。通过两个接口实现：
```python
# Application 对象
# 基于路径前缀
def add_subapp(self, prefix: str, subapp: "Application") -> PrefixedSubAppResource:
    pass
# 基于域名
def add_domain(self, domain: str, subapp: "Application") -> MatchedSubAppResource:
    pass
```
其中基于路径前缀的样例说明如下：
```python
# admin 是 subapp
admin = web.Application()
#注册资源（路由项）
admin.add_routes([web.get('/resource', handler, name='name')])
# 注册子app
app.add_subapp('/admin/', admin)

url = admin.router['name'].url_for()
# URL('/admin/resource')
```
基于域名的样例说明如下：
```python
# 定义子应用
subapp = web.Application()
# 定义主应用
app = web.Application()

# 将子应用挂载到特定域名
app.add_domain('sub.example.com', subapp)

web.run_app(app)
-------------------------------------------------------
# 通过访问特点的域名，可以访问子应用
```
## AppRunner
`AppRunner`对象在设计哲学上是用于管理`Application`对象的启动、运行和停止。为`Application`创建一个服务端的运行环境。

`AppRunner`管理的对象是`Application`。`AppRunner`的工作原理总结如下：

![AppRunner工作原理](./images/aiohttp-apprunner.png)

`AppRunner`管理`Application`主要分两个阶段。**启动阶段**`apprunner.setup`和**停止阶段**`apprunner.cleanup`。

在启动阶段会构建一个`Application`的服务端运行环境对象`Server`。`Server`对象是一个可调用对象，本质上返回一个`protocol`的`RequestHandler`对象。
也就是说，在`AppRunner`的启动阶段，会构建一个`protocol`类，用于`aiohttp`基于`transports`和`protocol`模式的网络编程。

## Sites
`TCPSite`、`UnixSite`和`SockSite`负责绑定监听指定的`IP`地址和端口。为`Application`提供了网络访问能力。

一个站点会监听一个地址，以接收和处理网络请求。`aiohttp`支持不同的站点：`SockSite`、`NamedPipeSite`、
`UnixSite`和`TCPSite`。以`TCPSite`为例，站点的工作原理比较简单，直接看源码实现：
```python
# TCPSite 的启动方法
async def start(self) -> None:
    # 在父类中，其实就是注册 AppRunner.sites 值
    await super().start()
    loop = asyncio.get_event_loop()
    # 拿到 AppRunner.server 对象，其实是一个 protocol 的工厂类
    server = self._runner.server
    assert server is not None
    # 调用底层 asyncio 的 create_server。基于 transports 和 protocols 编程模式实现
    self._server = await loop.create_server(
        server,
        self._host,
        self._port,
        ssl=self._ssl_context,
        backlog=self._backlog,
        reuse_address=self._reuse_address,
        reuse_port=self._reuse_port,
    )
```
从源码可知，`aiohttp`本质上是**基于`asyncio`的`transports`和`protocols`模式实现**。其中`protocol`是 `AppRunner`对象构建的`Server`对象。

站点的停止逻辑如下：
```python
# 先停止站点启动的服务，然后从`AppRunner.sites`删除此站点
async def stop(self) -> None:
    self._runner._check_site(self)
    if self._server is not None:  # Maybe not started yet
        self._server.close()

    self._runner._unreg_site(self)
```

# 请求数据流
当基于`aiohttp`创建服务端并启动后，就准备接收客户端建立连接及处理和响应客户端请求数据。下面总结了服务端处理请求流的大体流程：

![服务端请求流](./images/aiohttp-服务端请求处理流程.png)

在连接建立阶段，也就是执行`connection_made`协议方法的流程中，涉及`socket`两个网络属性如下：
+ `Nagle`算法是一种优化`TCP`网络传输效率的算法，旨在减少网络中小数据包的数量。工作原理是将小的数据包合并成较大的数据包发送，以减少网络传输中的开销。
套接字上设置`socket.TCP_NODELAY = True`，则意味着禁用`Nagle`算法。效果是每当发送数据时，数据会尽可能立即发送，而不被等待合并成更大的数据包。
+ 通过`socket.SO_KEEPALIVE`属性设置`TCP`保活。在`TCP`连接空闲时，也就是一定时间内，任何一端都没数据交互，则通过周期性发送探测包检测连接是否仍然有效。
如果探测失败，关闭`socket`并返回应用层错误。
  ```bash
  只有应用层调用 socket 的相关操作才会得到错误。例如调用`socket.send`得到`Connection reset by peer`错误。
  ```

为了更好理解上述`HTTP`请求数据处理流程，需要知道`HTTP`请求报文的规范。`HTTP`请求报文由**请求行**，**请求头**，**空行**，**请求体**组成。样例说明如下：
```bash
# GET 请求没有请求体
# 下面一行是请求行
GET /index.html HTTP/1.1
# 下面三行是请求头部
Host: www.example.com
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.99 Safari/537.36
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8
# 下面是个空行，必须有

-------------------------------------------------------------
# POST 请求有请求体
# 下面一行是请求行
POST /submit_form HTTP/1.1
# 下面四行是请求头部
Host: www.example.com
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.99 Safari/537.36
Content-Type: application/x-www-form-urlencoded
Content-Length: 25
# 下面是空行，必须有

# 下面是请求体
username=user1&password=1234
-------------------------------------------------------------
# 分块传输样例
# 下面一行是请求行
HTTP/1.1 200 OK
# 下面两行是请求头部
Content-Type: text/plain
Transfer-Encoding: chunked
# 下面是空行，必须有

# 下面是分块请求体
7\r\n
Hello, \r\n
6\r\n
world!\r\n
0\r\n
\r\n
############################################################
# 分块传输请求体每个块的格式如下
长度\r\n
数据\r\n
# 长度值为 0 表示请求体结束
0\r\n
\r\n
```
在接收到客户端数据并解析`HTTP`请求数据时，也就是在`data_received`流程中，请求行和请求头的解析结果会存放在`RequestHandler`内部的**缓存**中。
`RequestHandler`缓存中的每一个元素是一个`tuple(msg, payload)`对象。

其中`msg`是一个具名元组，每一个属性说明如下：
+ `method`: 请求行方法。例如`GET`。
+ `path`: 请求行中的`path`部分。例如`/index.html`。
+ `version`: 请求行中协议版本号。例如`HttpVersion(1, 1)`。
+ `headers`: 只读的字典。所有的请求头数据。
+ `raw_headers`: 元组。每一个元素是`(bname, bvalue)`。所有请求头数据。`bname`和`bvalue`是字节序列。
+ `should_close`: `http/1.1`默认`False`，`http/1.0`默认`True`。请求头`Connection:keep-alive`设置。
+ `compression`: 请求头中不指定或指定值不在`("gzip", "deflate", "br")`取值`None`。否则按指定值。
+ `upgrade`: `bool`类型，表示是否升级协议。
+ `chunked`: `bool`类型，表示是否是分块传输。
+ `url`: 从`path`构建的一个`yarl.URL`对象。

其中`payload`是`StreamReader`对象，内部使用缓存存储**请求体数据**。`StreamReader`提供了相关读方法从**缓存获取**请求体数据。
如果缓存没数据，则读操作会阻塞。可以参考`asyncio`中介绍的`Stream`模式编程。
```python
# StreamReader 中读方法
# 读最多 n 个字节。如果 n < 0，会一直读直到遇到 EOF。若 n = 0，返回空字节序列
async def read(self, n: int = -1) -> bytes:
    pass
# 会一直读直到遇到 EOF
async def readany(self) -> bytes:
    pass
# 读取一个 chunk 数据。返回的 bool 表示是否是分块的结尾。
async def readchunk(self) -> Tuple[bytes, bool]:
    pass
# 读 n 个字节数据
async def readexactly(self, n: int) -> bytes:
    pass
# 读直到遇到 separator 指定的字符
async def readuntil(self, separator: bytes = b"\n") -> bytes:
    pass
# 读一行数据
async def readline(self) -> bytes:
    return await self.readuntil()
```
上述`StreamReader`对象`payload`在`web.Request`对象中是 **`Request.content`属性值**。正常来说用户不用直接调用`payload`的读方法，
因为`web.Request`对象已经封装了相关的读方法。

在解析完请求，进入实际**请求处理流程中**，会首先根据解析的请求结果构建一个`web.Request`对象。`Request`对象包含了请求的所有信息。
```bash
# 请求 URL 结构
http://user:pass@example.com:8042/over/there?name=ferret#nose
 \__/   \__/ \__/ \_________/ \__/\_________/ \_________/ \__/
  |      |    |        |       |      |           |        |
scheme  user password host    port   path       query   fragment
```
例如`Request.rel_url`属性表示`url`的相对资源路径。也就是只包含`path`、`query`和`fragment`部分。
```python
URL('/over/there?name=ferret#nose')
```
`Request`对象也提供了 **`writer`属性**。其返回一个`StreamWriter`流式写对象（参考`asyncio`的`Stream`编程模式）。
`Request.writer`提供了三个异步写方法：
```python
# 发送 chunk 数据，也就是响应体数据
 async def write(self, chunk: Union[bytes, bytearray, memoryview], *, drain: bool = True, LIMIT: int = 0x10000) -> None:
    pass
# 发送响应头和状态行
async def write_headers(self, status_line: str, headers: "CIMultiDict[str]") -> None:
    pass
# 发送 EOF 表示响应结束
async def write_eof(self, chunk: bytes = b"") -> None:
    pass
```
上述`web.Request.writer`提供的写方法也不需要用户调用，在`web.Response`会封装好。

`Request`对象也提供给**用户读取请求数据**的方法：
```python
# Request 对象提供的读方法。内部其实是调用 StreamReader 对象 payload 提供的读方法

# 读请求体数据，返回是字节序列
async def read(self) -> bytes:
    pass
# 读请求体数据，返回字符串。解码方式默认是 utf-8，但可通过请求头 Content-Type 中 charset 指定
async def text(self) -> str:
    pass
# 读请求体，返回 json 格式数据
async def json(self, *, loads: JSONDecoder = DEFAULT_JSON_DECODER) -> Any:
    pass
# 读取 post 请求体参数字典对象
# 主要适用于 Content-Type: application/x-www-form-urlencoded 或 multipart/form-data 表单数据的请求
async def post(self) -> "MultiDictProxy[Union[str, bytes, FileField]]":
    pass
```
对于`web.Request.post`方法，给出一些样例说明如下：
+ `application/x-www-form-urlencoded`：表单数据编码为键值对形式的数据。用`URL`编码来转义特殊字符。
  ```bash
  POST /submit-form HTTP/1.1
  Host: example.com
  Content-Type: application/x-www-form-urlencoded
  
  name=John+Doe&email=john%40example.com&age=30
  ```
+ `multipart/form-data`：将表单数据以及可能包含文件等二进制数据一起上传。允许在同一个请求中传输多个文件和文本数据，每个部分有自己的`Content-Type`。
  ```bash
  POST /submit-form HTTP/1.1
  Host: example.com
  Content-Type: multipart/form-data; boundary=boundary123
  
  --boundary123
  Content-Disposition: form-data; name="image"; filename="example.jpg"
  Content-Type: image/jpeg
  
  [binary image data here]
  
  --boundary123
  Content-Disposition: form-data; name="name"
  
  John Doe
  --boundary123
  Content-Disposition: form-data; name="age"
  
  30
  --boundary123--

  ----------返回样例----------------------
  {
      "image": [binary image data here],
      "name": John Doe,
      "age": 30
  }
  ```

构建完`web.Request`对象后，会创建一个新的异步任务用于**执行用户定义的请求处理函数及返回响应**。

![请求处理及响应](./images/aiohttp-请求处理及响应.png)

流程中的响应`web.Response`对象需要用户构建，其初始化参数说明如下：
```python
class Response(StreamResponse):
    def __init__(
        self,
        *,
        body: Any = None,                          # 响应体，二进制数据
        status: int = 200,
        reason: Optional[str] = None,
        text: Optional[str] = None,                # 响应体，字符串数据
        headers: Optional[LooseHeaders] = None,
        content_type: Optional[str] = None,
        charset: Optional[str] = None,
        zlib_executor_size: Optional[int] = None,  # zlib 压缩算法参数
        zlib_executor: Optional[Executor] = None,  # zlib 压缩算法执行器
    ) -> None:
```
`aiohttp`也提供了一个**语法糖**用于响应`json`数据的`web.json_response`方法：
```python
# 其中 data 是 json 数据，其它和 Response 初始化参数一样
def json_response(
    data: Any = sentinel,
    *,
    text: Optional[str] = None,
    body: Optional[bytes] = None,
    status: int = 200,
    reason: Optional[str] = None,
    headers: Optional[LooseHeaders] = None,
    content_type: str = "application/json",
    dumps: JSONEncoder = json.dumps,
) -> Response:
    if data is not sentinel:
        if text or body:
            raise ValueError("only one of data, text, or body should be specified")
        else:
            text = dumps(data)
    return Response(
        text=text,
        body=body,
        status=status,
        reason=reason,
        headers=headers,
        content_type=content_type,
    )
```

上面就是完整的从**接收请求**，到**处理请求**，最后**发送响应**的完整数据流。

# 请求对象构建
主要完成对请求对象`Request`构建的相关原理介绍。`Request`对象是一个 http 请求的抽象封装，包含一个 http 请求的所有信息。
`Request`对象的初始化源码实现如下：
```python
class BaseRequest(MutableMapping[str, Any], HeadersMixin):
    POST_METHODS = {
        hdrs.METH_PATCH,
        hdrs.METH_POST,
        hdrs.METH_PUT,
        hdrs.METH_TRACE,
        hdrs.METH_DELETE,
    }
    def __init__(
        self,
        message: RawRequestMessage,
        payload: StreamReader,
        protocol: "RequestHandler",
        payload_writer: AbstractStreamWriter,
        task: "asyncio.Task[None]",
        loop: asyncio.AbstractEventLoop,
        *,
        client_max_size: int = 1024**2,
        state: Optional[Dict[str, Any]] = None,
        scheme: Optional[str] = None,
        host: Optional[str] = None,
        remote: Optional[str] = None,
    ) -> None:
        super().__init__()
        if state is None:
            state = {}
        # 请求行和请求头信息对象
        self._message = message
        self._protocol = protocol
        # 一个流式写对象 StreamWriter
        self._payload_writer = payload_writer
        # 请求体内容对象
        self._payload = payload
        self._headers = message.headers
        self._method = message.method
        self._version = message.version
        self._cache: Dict[str, Any] = {}
        url = message.url
        if url.is_absolute():
            # absolute URL is given,
            # override auto-calculating url, host, and scheme
            # all other properties should be good
            self._cache["url"] = url
            self._cache["host"] = url.host
            self._cache["scheme"] = url.scheme
            self._rel_url = url.relative()
        else:
            self._rel_url = message.url
        self._post: Optional[MultiDictProxy[Union[str, bytes, FileField]]] = None
        self._read_bytes: Optional[bytes] = None
        # 变量的存储与获取
        self._state = state
        self._task = task
        # 请求体大小上限
        self._client_max_size = client_max_size
        self._loop = loop
        self._disconnection_waiters: Set[asyncio.Future[None]] = set()

        transport = self._protocol.transport
        assert transport is not None
        self._transport_sslcontext = transport.get_extra_info("sslcontext")
        self._transport_peername = transport.get_extra_info("peername")

        if scheme is not None:
            self._cache["scheme"] = scheme
        if host is not None:
            self._cache["host"] = host
        if remote is not None:
            self._cache["remote"] = remote

class Request(BaseRequest):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # 路由匹配结果，一个 UrlMappingMatchInfo 对象
        self._match_info: Optional[UrlMappingMatchInfo] = None
```

## 变量的存储与获取
对于只在`Request`对象生命周期内使用的变量可以方便地按照如下方式存储和使用：
```python
request['my_private_key'] = "data"
data = request["my_private_key"]
```
相关的源码实现如下：
```python
def __getitem__(self, key: str) -> Any:
    return self._state[key]

def __setitem__(self, key: str, value: Any) -> None:
    self._state[key] = value

def __delitem__(self, key: str) -> None:
    del self._state[key]

def __len__(self) -> int:
    return len(self._state)

def __iter__(self) -> Iterator[str]:
    return iter(self._state)
```
## 流式写对象 StreamWriter
`StreamWriter`对象用于 http 响应报文发送，是对`asyncio.transports`的封装，其作为`Request`对象的一个属性：
```python
@property
def writer(self) -> AbstractStreamWriter:
    return self._payload_writer
```
`StreamWriter`的初始化如下：
```python
class StreamWriter(AbstractStreamWriter):
    def __init__(
        self,
        protocol: BaseProtocol,
        loop: asyncio.AbstractEventLoop,
        on_chunk_sent: _T_OnChunkSent = None,
        on_headers_sent: _T_OnHeadersSent = None,
    ) -> None:
        self._protocol = protocol

        self.loop = loop
        # 写响应报文的大小
        self.length = None
        # 是否使用分块写
        self.chunked = False
        # 值等于已经发送的报文字节数，用于控制发送的请求报文速率
        self.buffer_size = 0
        # 已经发送报文字节数
        self.output_size = 0

        self._eof = False
        self._compress: Optional[ZLibCompressor] = None
        # 没用到此变量
        self._drain_waiter = None
        # 一个回调方法，用于跟踪发送的响应，在 chunk 发送之前调用
        self._on_chunk_sent: _T_OnChunkSent = on_chunk_sent
        # 一个回调方法，用于跟踪发送的headers，在 headers 发送之前调用
        self._on_headers_sent: _T_OnHeadersSent = on_headers_sent
```
`StreamWriter`提供了如下的属性或者功能开关：
+ `transport`：属性，底层协议使用的 transport 对象；
+ `protocol`：属性，底层使用的协议对象；
+ `enable_chunking`：使能分块传输；
+ `enable_compression`：设置对传输数据压缩；

相关源码如下：
```python
@property
def transport(self) -> Optional[asyncio.Transport]:
    return self._protocol.transport

@property
def protocol(self) -> BaseProtocol:
    return self._protocol

def enable_chunking(self) -> None:
    self.chunked = True

def enable_compression(
    self, encoding: str = "deflate", strategy: int = zlib.Z_DEFAULT_STRATEGY
) -> None:
    self._compress = ZLibCompressor(encoding=encoding, strategy=strategy)
```
对于写数据，`StreamWriter`提供了三个相关异步方法：`write`、`write_headers`和`write_eof`。先看下`write`相关的源码：
```python
async def write(
    self, chunk: bytes, *, drain: bool = True, LIMIT: int = 0x10000
) -> None:
    """Writes chunk of data to a stream.

    write_eof() indicates end of stream.
    writer can't be used after write_eof() method being called.
    write() return drain future.
    """
    # 执行 chunk 数据写回调
    if self._on_chunk_sent is not None:
        await self._on_chunk_sent(chunk)

    if isinstance(chunk, memoryview):
        if chunk.nbytes != len(chunk):
            # just reshape it
            # Cast the memoryview to bytes-like object
            chunk = chunk.cast("c")
    # 执行发送数据压缩
    if self._compress is not None:
        chunk = await self._compress.compress(chunk)
        if not chunk:
            return

    if self.length is not None:
        chunk_len = len(chunk)
        # 已经发送的 chunk 累积大小没超过写响应报文大小，chunk 全部发送
        if self.length >= chunk_len:
            self.length = self.length - chunk_len
        # 已经发送的 chunk 累积大小超过写响应报文大小，chunk 部分发送
        else:
            chunk = chunk[: self.length]
            # 要发送大小的请求报文已经发送完，恢复初始状态 0
            self.length = 0
            if not chunk:
                return

    if chunk:
        # 分块传输，构造一个分块：第一行是发送块大小，第二行是发送的块数据
        if self.chunked:
            chunk_len_pre = ("%x\r\n" % len(chunk)).encode("ascii")
            chunk = chunk_len_pre + chunk + b"\r\n"
        # 将要发送的数据放到底层 transport 的写缓存中
        self._write(chunk)
        # 如果已经放到发送缓存的数据大小超过限制，则暂停往底层写缓存放数据，直到底层恢复写执行
        if self.buffer_size > LIMIT and drain:
            self.buffer_size = 0
            await self.drain()

async def drain(self) -> None:
   """Flush the write buffer.

   The intended use is to write

     await w.write(data)
     await w.drain()
   """
   if self._protocol.transport is not None:
       await self._protocol._drain_helper()
```
根据源码可知，`write`最终会调用`_write`方法执行实际的写操作。`_write`方法的实现源码如下：
```python
def _write(self, chunk: bytes) -> None:
    size = len(chunk)
    self.buffer_size += size
    self.output_size += size
    transport = self.transport
    if not self._protocol.connected or transport is None or transport.is_closing():
        raise ConnectionResetError("Cannot write to closing transport")
    # 最终调用底层 asyncio.transport 的写操作
    transport.write(chunk)
```
下面看下`write_headers`方法的源码实现：
```python
async def write_headers(
    self, status_line: str, headers: "CIMultiDict[str]"
) -> None:
    """Write request/response status and headers."""
    # 执行 headers 数据写回调
    if self._on_headers_sent is not None:
        await self._on_headers_sent(headers)

    # status + headers
    buf = _serialize_headers(status_line, headers)
    self._write(buf)

def _safe_header(string: str) -> str:
    if "\r" in string or "\n" in string:
        raise ValueError(
            "Newline or carriage return detected in headers. "
            "Potential header injection attack."
        )
    return string

def _py_serialize_headers(status_line: str, headers: "CIMultiDict[str]") -> bytes:
    headers_gen = (_safe_header(k) + ": " + _safe_header(v) for k, v in headers.items())
    line = status_line + "\r\n" + "\r\n".join(headers_gen) + "\r\n\r\n"
    return line.encode("utf-8")

_serialize_headers = _py_serialize_headers
```
最后是`write_eof`源码实现：
```python
async def write_eof(self, chunk: bytes = b"") -> None:
    if self._eof:
        return
    # 执行 chunk 数据写回调 
    if chunk and self._on_chunk_sent is not None:
        await self._on_chunk_sent(chunk)
    # chunk 数据压缩
    if self._compress:
        if chunk:
            chunk = await self._compress.compress(chunk)

        chunk += self._compress.flush()
        # 构造分块数据
        if chunk and self.chunked:
            chunk_len = ("%x\r\n" % len(chunk)).encode("ascii")
            chunk = chunk_len + chunk + b"\r\n0\r\n\r\n"
    else:
        # 构造分块数据
        if self.chunked:
            if chunk:
                chunk_len = ("%x\r\n" % len(chunk)).encode("ascii")
                chunk = chunk_len + chunk + b"\r\n0\r\n\r\n"
            else:
                # 分块数据结束
                chunk = b"0\r\n\r\n"

    if chunk:
        self._write(chunk)
    # 暂停写，等待底层恢复写
    await self.drain()
    # 设置写结束标志位
    self._eof = True
```
## 请求体获取
`read`方法返回请求体对象的字节对象，其源码如下：
```python
async def read(self) -> bytes:
    """Read request body if present.

    Returns bytes object with full request content.
    """
    if self._read_bytes is None:
        body = bytearray()
        while True:
            # 如果没有请求体，self._payload.readany() 返回空字节序列 b""
            chunk = await self._payload.readany()
            body.extend(chunk)
            # 请求体大小的最大限制检查
            if self._client_max_size:
                body_size = len(body)
                if body_size > self._client_max_size:
                    raise HTTPRequestEntityTooLarge(
                        max_size=self._client_max_size, actual_size=body_size
                    )
            if not chunk:
                break
        self._read_bytes = bytes(body)
    return self._read_bytes
```
`text`方法返回请求体的文本对象（字符串），源码如下：
```python
async def text(self) -> str:
    """Return BODY as text using encoding from .charset."""
    bytes_body = await self.read()
    encoding = self.charset or "utf-8"
    try:
        return bytes_body.decode(encoding)
    except LookupError:
        raise HTTPUnsupportedMediaType()
```
`json`方法返回请求体的 json 对象，源码如下：
```python
async def json(
    self,
    *,
    loads: JSONDecoder = DEFAULT_JSON_DECODER,
    content_type: Optional[str] = "application/json",
) -> Any:
    """Return BODY as JSON."""
    body = await self.text()
    if content_type:
        if not is_expected_content_type(self.content_type, content_type):
            raise HTTPBadRequest(
                text=(
                    "Attempt to decode JSON with "
                    "unexpected mimetype: %s" % self.content_type
                )
            )
    # DEFAULT_JSON_DECODER = json.loads
    return loads(body)

def is_expected_content_type(
    response_content_type: str, expected_content_type: str
) -> bool:
    """Checks if received content type is processable as an expected one.

    Both arguments should be given without parameters.
    """
    if expected_content_type == "application/json":
        return json_re.match(response_content_type) is not None
    return expected_content_type in response_content_type
```
`post`方法返回 post 请求体参数的字典对象，源码如下：
```python
async def multipart(self) -> MultipartReader:
    """Return async iterator to process BODY as multipart."""
    return MultipartReader(self._headers, self._payload)

async def post(self) -> "MultiDictProxy[Union[str, bytes, FileField]]":
    """Return POST parameters."""
    if self._post is not None:
        return self._post
    if self._method not in self.POST_METHODS:
        self._post = MultiDictProxy(MultiDict())
        return self._post

    content_type = self.content_type
    # application/x-www-form-urlencoded: 键值对的形式
    # multipart/form-data: 表单数据
    if content_type not in (
        "",
        "application/x-www-form-urlencoded",
        "multipart/form-data",
    ):
        self._post = MultiDictProxy(MultiDict())
        return self._post

    out: MultiDict[Union[str, bytes, FileField]] = MultiDict()
    # 处理表单数据
    if content_type == "multipart/form-data":
        multipart = await self.multipart()
        max_size = self._client_max_size
        # 一个 part 内容
        field = await multipart.next()
        while field is not None:
            size = 0
            field_ct = field.headers.get(hdrs.CONTENT_TYPE)

            if isinstance(field, BodyPartReader):
                assert field.name is not None

                # Note that according to RFC 7578, the Content-Type header
                # is optional, even for files, so we can't assume it's
                # present.
                # https://tools.ietf.org/html/rfc7578#section-4.4
                if field.filename:
                    # store file in temp file
                    tmp = await self._loop.run_in_executor(
                        None, tempfile.TemporaryFile
                    )
                    chunk = await field.read_chunk(size=2**16)
                    while chunk:
                        chunk = field.decode(chunk)
                        await self._loop.run_in_executor(None, tmp.write, chunk)
                        size += len(chunk)
                        if 0 < max_size < size:
                            await self._loop.run_in_executor(None, tmp.close)
                            raise HTTPRequestEntityTooLarge(
                                max_size=max_size, actual_size=size
                            )
                        chunk = await field.read_chunk(size=2**16)
                    await self._loop.run_in_executor(None, tmp.seek, 0)

                    if field_ct is None:
                        field_ct = "application/octet-stream"

                    ff = FileField(
                        field.name,
                        field.filename,
                        cast(io.BufferedReader, tmp),
                        field_ct,
                        field.headers,
                    )
                    out.add(field.name, ff)
                else:
                    # deal with ordinary data
                    value = await field.read(decode=True)
                    if field_ct is None or field_ct.startswith("text/"):
                        charset = field.get_charset(default="utf-8")
                        out.add(field.name, value.decode(charset))
                    else:
                        out.add(field.name, value)
                    size += len(value)
                    if 0 < max_size < size:
                        raise HTTPRequestEntityTooLarge(
                            max_size=max_size, actual_size=size
                        )
            else:
                raise ValueError(
                    "To decode nested multipart you need " "to use custom reader",
                )

            field = await multipart.next()
    # 请求体是非表单数据，例如普通的健值对
    else:
        data = await self.read()
        if data:
            charset = self.charset or "utf-8"
            bytes_query = data.rstrip()
            try:
                # 解码，将字节数据转为字符串数据
                query = bytes_query.decode(charset)
            except LookupError:
                raise HTTPUnsupportedMediaType()
            out.extend(
                parse_qsl(qs=query, keep_blank_values=True, encoding=charset)
            )

    self._post = MultiDictProxy(out)
    return self._post
```
> http 传输数据 Content-Type 取值的三种情况说明如下：
> + `application/octet-stream`：
>   - 用途：用于传输未经编码的二进制数据，通常用于文件上传或传输不属于任何特定MIME类型的数据。
>   - 区别：与其他两种类型不同，它不会对数据进行编码或解析，而是直接传输原始二进制数据。
>   - 请求格式样例：
>     ```bash
>     POST /upload HTTP/1.1
>     Host: example.com
>     Content-Type: application/octet-stream
>     
>     [binary data here]
>     ```
> + `application/x-www-form-urlencoded`：
>    - 用途：用于将表单数据编码为键值对形式的数据。
>    - 区别：数据被编码成键值对形式，使用URL编码来转义特殊字符。
>    - 请求格式样例：
>      ```bash
>      POST /submit-form HTTP/1.1
>      Host: example.com
>      Content-Type: application/x-www-form-urlencoded
>      
>      name=John+Doe&email=john%40example.com&age=30
>      ```
> + `multipart/form-data`：
>    - 用途：用于将表单数据以及可能包含文件等二进制数据一起上传。
>    - 区别：允许在同一个请求中传输多个文件和文本数据，每个部分可以有自己的Content-Type。
>    - 请求格式样例：
>      ```bash
>      POST /submit-form HTTP/1.1
>      Host: example.com
>      Content-Type: multipart/form-data; boundary=boundary123
>      
>      --boundary123
>      Content-Disposition: form-data; name="image"; filename="example.jpg"
>      Content-Type: image/jpeg
>      
>      [binary image data here]
>      
>      --boundary123
>      Content-Disposition: form-data; name="name"
>      
>      John Doe
>      --boundary123
>      Content-Disposition: form-data; name="age"
>      
>      30
>      --boundary123--
>      ```

在`post`源码中，当处理`Content-Type != multipart/form-data`时，使用`urllib.parse.parse_qsl`解析健值对请求体，使用样例如下：
```python
qs = "key1=12&key2=hello&key3=10"
a = parse_qsl(qs, keep_blank_values=True)
a
[('key1', '12'), ('key2', 'hello'), ('key3', '10')]
```
当处理`Content-Type = multipart/form-data`时，最终的返回结果字典的 key 是请求体每一个 part 中**子请求头**`Content-Disposition`
中`name`对应的取值，最终返回字典的 value 是请求体每一个 part 中**子请求体**的内容。例如上面的样例中，
最终返回的结果字典如下（实际是个 MultiDict 对象，下面样例只是说明）：
```bash
{
    "image": [binary image data here],
    "name": John Doe,
    "age": 30
}
```
## 请求信息
> URL 的结构如下所示：
>  ```bash
>   http://user:pass@example.com:8042/over/there?name=ferret#nose
>   \__/   \__/ \__/ \_________/ \__/\_________/ \_________/ \__/
>    |      |    |        |       |      |           |        |
>  scheme  user password host    port   path       query   fragment
>  ```

`Request`对象包含了 http 请求相关的所有信息，下面对其进行总结和介绍。
+ `task`：表示处理请求的异步任务对象，例如`self._loop.create_task(self.start())`。
*May be useful for graceful shutdown of long-running requests (streaming, long polling or web-socket)*
  ```python
  @property
  def task(self) -> "asyncio.Task[None]":
      return self._task
  ```
+ `protocol`：`Request`对象底层使用的协议；
  ```python
  @property
  def protocol(self) -> "RequestHandler":
      return self._protocol
  ```
+ `transport`：`Request`对象底层使用的`transport`对象；
  ```python
  @property
  def transport(self) -> Optional[asyncio.Transport]:
      if self._protocol is None:
          return None
      return self._protocol.transport
  ```
+ `client_max_size`：表示请求体大小的最大值；
  ```python
  @property
  def client_max_size(self) -> int:
      return self._client_max_size
  ```
+ `rel_url`：返回 url 的相对资源路径，也就是只包含 path、query 和 fragment 部分，一个 `yarl.URL`对象，
例如上面样例中`URL('/over/there?name=ferret#nose')`；
  ```python
  @reify
  def rel_url(self) -> URL:
      return self._rel_url
  ```
+ `secure`：返回一个 bool 值，表示是否是 https 协议；
  ```python
  @reify
  def secure(self) -> bool:
      """A bool indicating if the request is handled with SSL."""
      return self.scheme == "https"
  ```
+ `forwarded`：解析 Forwarded 头，返回一个元组，每一个`Forwarded 'field-value'`都是一个字典；
  > Forwarded headers 用于在 HTTP 请求或响应中传递关于请求链的信息。它提供了一种机制来跟踪客户端到服务器之间的请求路由路径，
  > 样例说明如下：
  > ```bash
  > Forwarded: by=192.0.2.60; for=192.0.2.0; host=example.com; proto=https
  > ```
  > 这个例子中的 Forwarded 标头包含了四个参数：
  > + by：表示请求的发起者，即客户端的 IP 地址或主机名。
  > + for：表示原始请求的目标，通常是中间代理的 IP 地址。
  > + host：表示请求的目标主机。
  > + proto：表示请求使用的协议。

  > 如果有多个代理服务器，用逗号分开，样例如下：
  > ```bash
  > Forwarded: for=192.0.2.60;by=proxy1.example.com;proto=https, for=203.0.113.11;by=proxy2.example.com;proto=http
  > ```
+ `scheme`：返回请求 url 中的 scheme 部分，例如 http/https；
  ```python
  @reify
  def scheme(self) -> str:
      """A string representing the scheme of the request.
  
      Hostname is resolved in this order:
  
      - overridden value by .clone(scheme=new_scheme) call.
      - type of connection to peer: HTTPS if socket is SSL, HTTP otherwise.
  
      'http' or 'https'.
      """
      if self._transport_sslcontext:
          return "https"
      else:
          return "http"
  ```
+ `method`：返回请求方法，例如 GET/POST 等；
  ```python
  @reify
  def method(self) -> str:
      """Read only property for getting HTTP method.

      The value is upper-cased str like 'GET', 'POST', 'PUT' etc.
      """
      return self._method
  ```
+ `version`：返回 HTTP 的版本，一个`aiohttp.protocol.HttpVersion`实例；
  ```python
  @reify
  def version(self) -> HttpVersion:
      """Read only property for getting HTTP version of request.

      Returns aiohttp.protocol.HttpVersion instance.
      """
      return self._version
  ```
+ `host`：返回请求头 Host 的值，一个字符串对象；如果没有请求头，返回`socket.getfqdn()`的值；
  ```python
  @reify
  def host(self) -> str:
      """Hostname of the request.

      Hostname is resolved in this order:

      - overridden value by .clone(host=new_host) call.
      - HOST HTTP header
      - socket.getfqdn() value
      """
      host = self._message.headers.get(hdrs.HOST)
      if host is not None:
          return host
      return socket.getfqdn()
  ```
+ `remote`：返回客户端的 ip，如果获取不到返回 None；
  ```python
  @reify
  def remote(self) -> Optional[str]:
      """Remote IP of client initiated HTTP request.

      The IP is resolved in this order:

      - overridden value by .clone(remote=new_remote) call.
      - peername of opened socket
      """
      if self._transport_peername is None:
          return None
      # self._transport_peername 是 (ip, port)
      if isinstance(self._transport_peername, (list, tuple)):
          return str(self._transport_peername[0])
      return str(self._transport_peername)
  ```
+ `url`：返回完整的 url 的`yarl.URL`对象，也包含 scheme、host 和 port 部分，例如：`URL('http://example.com:8042/over/there?name=ferret#nose')`；
  ```python
  @reify
  def url(self) -> URL:
      url = URL.build(scheme=self.scheme, host=self.host)
      return url.join(self._rel_url)
  ```
+ `path`：返回 url 中的 path 部分，一个字符串，例如：`/over/there`；
  ```python
  @reify
  def path(self) -> str:
      """The URL including *PATH INFO* without the host or scheme.

      E.g., ``/app/blog``
      """
      return self._rel_url.path
  ```
+ `path_qs`：返回一个字符串，表示 url 的相对资源路径，也就是只包含 path、query 和 fragment 部分，例如：`/over/there?name=ferret#nose`；
  ```python
  @reify
  def path_qs(self) -> str:
      """The URL including PATH_INFO and the query string.

      E.g, /app/blog?id=10
      """
      return str(self._rel_url)
  ```
+ `raw_path`：返回一个字符串，表示**请求行**中的 path 部分；
  ```python
  @reify
  def raw_path(self) -> str:
      """The URL including raw *PATH INFO* without the host or scheme.

      Warning, the path is unquoted and may contains non valid URL characters

      E.g., ``/my%2Fpath%7Cwith%21some%25strange%24characters``
      """
      return self._message.path
  ```
+ `query`：返回一个 MultiDictProxy 对象，表示 url 中的 query 部分，例如：`<MultiDictProxy('name': 'ferret')>`；
  ```python
  @reify
  def query(self) -> MultiDictProxy[str]:
      """A multidict with all the variables in the query string."""
      return MultiDictProxy(self._rel_url.query)
  ```
+ `query_string`：返回一个字符串，表示 url 中的 query 部分，例如：`name=ferret`；
  ```python
  @reify
  def query_string(self) -> str:
      """The query string in the URL.

      E.g., id=10
      """
      return self._rel_url.query_string
  ```
+ `headers`：一个 case-insensitive 的 multidict 对象，包含所有的请求头信息；
  ```python
  @reify
  def headers(self) -> "CIMultiDictProxy[str]":
      """A case-insensitive multidict proxy with all headers."""
      return self._headers
  ```
+ `raw_headers`：一个元组，每一个元素是`(bname, bvalue)`，表示一个请求头名字和取值，`bname`和`bvalue`是字节序列；
  ```python
  @reify
  def raw_headers(self) -> RawHeaders:
      """A sequence of pairs for all headers."""
      return self._message.raw_headers
  ```
+ `if_modified_since`：返回请求头`If-Modified-Since`的值或者 None；
  > 通常用于条件 GET 请求。它允许客户端告知服务器，它只需要响应一个在指定时间之后被修改过的资源。
  如果资源自指定时间之后未被修改，服务器将返回一个 304 Not Modified 响应，而不是完整的资源内容，样例如下：
  ```bash
  If-Modified-Since: Sat, 08 May 2021 12:00:00 GMT
  ```
  ```python
  @reify
  def if_modified_since(self) -> Optional[datetime.datetime]:
      """The value of If-Modified-Since HTTP header, or None.

      This header is represented as a `datetime` object.
      """
      return parse_http_date(self.headers.get(hdrs.IF_MODIFIED_SINCE))
  ```
+ `if_unmodified_since`：返回请求头`If-Unmodified-Since`的值，或者None；
  ```python
  @reify
  def if_unmodified_since(self) -> Optional[datetime.datetime]:
      """The value of If-Unmodified-Since HTTP header, or None.

      This header is represented as a `datetime` object.
      """
      return parse_http_date(self.headers.get(hdrs.IF_UNMODIFIED_SINCE))
  ```
+ `if_range`：返回请求头`If-Range`的值，或者None；
  ```python
  @reify
  def if_range(self) -> Optional[datetime.datetime]:
      """The value of If-Range HTTP header, or None.

      This header is represented as a `datetime` object.
      """
      return parse_http_date(self.headers.get(hdrs.IF_RANGE))
  ```
+ `if_match`：返回一个元组，表示请求头`If-Match`的值，每一个元素都是 ETag，或者返回None；
+ `if_none_match`：返回一个元组，表示请求头`If-None-Match`的值，每一个元素都是 ETag，或者返回None；
  > ETag（实体标签）是用于标识资源版本的一种机制。它是由服务器为每个资源分配的一个唯一的标识符，
  通常是资源内容的哈希值或其他类似的指纹。ETag 被用来帮助客户端和服务器在资源是否发生变化方面进行有效的缓存管理和条件请求。
  >
  > ETag 的工作方式如下：
  > + 当服务器响应一个资源请求时，它会附加一个 ETag 头，其中包含了资源的标识符。
  > + 客户端在后续请求中，如果想要检查资源是否发生了变化，可以将上次获取的 ETag 值发送给服务器，通过条件请求来验证资源的状态。
  
  > ETag 可以是任何能唯一标识资源版本的字符串，但通常采用以下两种方式生成：
  > + 哈希值：服务器可以计算资源内容的哈希值（如 MD5、SHA1 等），将其作为 ETag。
  > + 时间戳或版本号：资源的最后修改时间戳或版本号可以作为 ETag。如果资源发生变化，时间戳或版本号也会改变，因此它们可以作为资源版本的标识符。

  > 客户端可以使用 ETag 来进行条件请求，包括：
  > + If-None-Match：客户端可以发送上次获取的 ETag 值，询问服务器是否有新的资源版本。
  > + If-Match：客户端可以发送希望修改的资源的 ETag 值，服务器会检查该 ETag 是否匹配当前资源版本，如果匹配，则执行请求，否则返回 412 Precondition Failed
+ `keep_alive`：一个 bool 值，表示是否是长连接：
  ```python
  @reify
  def keep_alive(self) -> bool:
      """Is keepalive enabled by client?"""
      return not self._message.should_close
  ```
+ `cookies`：返回一个字典对象，包含所有的 cookies 信息；
  ```python
  @reify
  def cookies(self) -> Mapping[str, str]:
      """Return request cookies.

      A read-only dictionary-like object.
      """
      raw = self.headers.get(hdrs.COOKIE, "")
      parsed = SimpleCookie(raw)
      return MappingProxyType({key: val.value for key, val in parsed.items()})
  ```
+ `http_range`：放回请求头`Range`的内容，结果是一个切片对象`slice(start, end, 1)`；
  > Range 是一个 HTTP 请求头，用于指定客户端想要获取的资源的范围。它通常与 GET 请求一起使用，
  允许客户端请求资源的部分内容，而不是整个资源，样例说明如下：
  ```bash
  Range: bytes=0-499
  ```
  > Range 头的值通常是一个范围描述，指定了资源的起始和结束位置。在这个例子中，
  bytes=0-499 表示从字节偏移量 0 开始，到字节偏移量 499 结束的范围。
  > 
  > 服务器在收到带有 Range 头的请求后，可以根据指定的范围，返回相应的资源部分，
  并使用状态码 206 Partial Content 响应。如果服务器无法满足范围请求，或者不支持范围请求，
  它会返回完整的资源内容，使用状态码 200 OK 响应
+ `content`：返回请求体的流式写对象`StreamWriter`；
  ```python
  @reify
  def content(self) -> StreamReader:
      """Return raw payload stream."""
      return self._payload
  ```
+ `can_read_body`：返回 bool 值，表示请求体是否可读；
  ```python
  @property
  def can_read_body(self) -> bool:
      """Return True if request's HTTP BODY can be read, False otherwise."""
      return not self._payload.at_eof()
  ```
+ `body_exists`：一个 bool 值，表示请求体是否存在；
  ```python
  @reify
  def body_exists(self) -> bool:
      """Return True if request has HTTP BODY, False otherwise."""
      return type(self._payload) is not EmptyStreamReader
  ```
+ `content_length`：返回请求头`Content-Length`的值；
  ```python
  @property
  def content_length(self) -> Optional[int]:
      """The value of Content-Length HTTP header."""
      content_length = self._headers.get(  # type: ignore[attr-defined]
          hdrs.CONTENT_LENGTH
      )

      if content_length is not None:
          return int(content_length)
      else:
          return None
  ```
+ `charset`：获取请求头`Content-Type`的`charset`部分；
+ `content_type`：获取请求头`Content-Type`内容；
  > Content-Type 样例如下：
  ```bash
  Content-Type: text/html; charset=UTF-8
  ```
+ `match_info`：返回匹配的路由结果对象`UrlMappingMatchInfo`；
  ```python
  @reify
  def match_info(self) -> "UrlMappingMatchInfo":
      """Result of route resolving."""
      match_info = self._match_info
      assert match_info is not None
      return match_info
  ```
+ `app`：返回和匹配路由关联的`Application`对象；
  ```python
  @property
  def app(self) -> "Application":
      """Application instance."""
      match_info = self._match_info
      assert match_info is not None
      return match_info.current_app
  ```
+ `config_dict`：返回一个`ChainMapProxy`对象，包含当前 app 以及所有父 app；
  ```python
  @property
  def config_dict(self) -> ChainMapProxy:
      match_info = self._match_info
      assert match_info is not None
      lst = match_info.apps
      app = self.app
      # 获取当前 app 的索引
      idx = lst.index(app)
      sublist = list(reversed(lst[: idx + 1]))
      return ChainMapProxy(sublist)
  ```
## 优雅关闭及信息交互
`Request`对象提供了自身复制能力`clone`用于返回一个新的实例并替换一些属性。

`_prepare_hook`方法用于在默认响应头准备完到发送之间执行，主要用来触发`on_response_prepare`信号，源码如下：
```python
async def _prepare_hook(self, response: StreamResponse) -> None:
    match_info = self._match_info
    if match_info is None:
        return
    for app in match_info._apps:
        # 触发 on_response_prepare 信号
        await app.on_response_prepare.send(self, response)
```
`Request`的优雅关闭主要涉及三个方法：`wait_for_disconnection`、`_finish`和`_cancel`，源码如下：
```python
def _cancel(self, exc: BaseException) -> None:
    set_exception(self._payload, exc)
    for fut in self._disconnection_waiters:
        set_result(fut, None)

def _finish(self) -> None:
    for fut in self._disconnection_waiters:
        fut.cancel()

    if self._post is None or self.content_type != "multipart/form-data":
        return

    # NOTE: Release file descriptors for the
    # NOTE: `tempfile.Temporaryfile`-created `_io.BufferedRandom`
    # NOTE: instances of files sent within multipart request body
    # NOTE: via HTTP POST request.
    for file_name, file_field_object in self._post.items():
        if not isinstance(file_field_object, FileField):
            continue
        # 关闭请求传输文件对象
        file_field_object.file.close()

async def wait_for_disconnection(self) -> None:
    loop = asyncio.get_event_loop()
    fut: asyncio.Future[None] = loop.create_future()
    self._disconnection_waiters.add(fut)
    try:
        await fut
    finally:
        self._disconnection_waiters.remove(fut)
```
TODO 使用场景后面在补充，这是新加特性

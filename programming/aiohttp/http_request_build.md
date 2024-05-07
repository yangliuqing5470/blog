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

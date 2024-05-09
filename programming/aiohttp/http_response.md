```bash
HTTP/1.1 200 OK
Date: Sat, 08 May 2021 12:00:00 GMT
Server: Apache/2.4.41 (Unix)
Content-Type: text/html; charset=UTF-8
Content-Length: 1245

<!DOCTYPE html>
<html>
<head>
    <title>Example Page</title>
</head>
<body>
    <h1>Hello, World!</h1>
    <p>This is an example page.</p>
</body>
</html>
```
以上是 http 响应报文，其格式如下：
+ **起始行（Start Line）**：包含了协议版本（HTTP/1.1）、状态码（200 OK）和状态消息（OK）。
+ **响应头（Response Headers）**：包含了与响应相关的元信息，如日期、服务器信息、内容类型和内容长度等。
+ **空行**：用于分隔响应头和响应体。
+ **响应体（Response Body）**：包含了实际的资源数据，这里是一个简单的 HTML 文档

aiohttp 为 http 响应提供了三个类：`StreamResponse`、`Response`和`FileResponse`，以及一个便捷的`json_response`方法。
# StreamResponse
## 初始化
`StreamResponse`类的初始化源码如下：
```python
class StreamResponse(BaseClass, HeadersMixin, CookieMixin):
    def __init__(
        self,
        *,
        status: int = 200,
        reason: Optional[str] = None,
        headers: Optional[LooseHeaders] = None,
    ) -> None:
        super().__init__()
        # 检查 Content-Length，如果没有 Content-Length，对于 http1.1及之后版本，使用分块传输 
        self._length_check = True
        # 字节对象，响应体数据
        self._body = None
        # 一个 bool 值，表示是否保持连接
        self._keep_alive: Optional[bool] = None
        # 是否分块传输
        self._chunked = False
        # 是否启用数据压缩
        self._compression = False
        # 压缩使用类型 deflate/gzip/identity
        self._compression_force: Optional[ContentCoding] = None
        # 构建的请求对象
        self._req: Optional[BaseRequest] = None
        # 构建的请求对象中的 StreamWriter 对象
        self._payload_writer: Optional[AbstractStreamWriter] = None
        # 响应报文是否写完
        self._eof_sent = False
        # 一个 bool 值，表示是否有响应体
        self._must_be_empty_body: Optional[bool] = None
        # 响应报文字节数
        self._body_length = 0
        # 存储用于同步的变量
        self._state: Dict[str, Any] = {}
        # 响应头
        if headers is not None:
            self._headers: CIMultiDict[str] = CIMultiDict(headers)
        else:
            self._headers = CIMultiDict()
        # 初始化 self._status 和 self._reason 属性
        self.set_status(status, reason)

    def set_status(
        self,
        status: int,
        reason: Optional[str] = None,
    ) -> None:
        assert not self.prepared, (
            "Cannot change the response status code after " "the headers have been sent"
        )
        # 响应码
        self._status = int(status)
        if reason is None:
            try:
                reason = HTTPStatus(self._status).phrase
            except ValueError:
                reason = ""
        # 响应说明
        self._reason = reason
```
## 变量的存储与获取
对于只在`Response`对象生命周期内使用的变量可以方便地按照如下方式存储和使用：
```bash
resp['key'] = value
value = resp["key"]
```
相关源码实现如下：
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

def __hash__(self) -> int:
    return hash(id(self))

def __eq__(self, other: object) -> bool:
    return self is other
```
## 属性及功能设置
+ `prepared`：一个 bool 值，表示`prepare`方法是否被调用，True 表示被调用，False 表示没有；
  ```python
  @property
  def prepared(self) -> bool:
      return self._payload_writer is not None
  ```
+ `task`：处理请求的任务，例如`self._loop.create_task(self.start())`。
May be useful for graceful shutdown of long-running requests (streaming, long polling or web-socket)
  ```python
  @property
  def task(self) -> "Optional[asyncio.Task[None]]":
      if self._req:
          return self._req.task
      else:
          return None
  ```
+ `status`：响应状态码；
  ```python
  @property
  def status(self) -> int:
      return self._status
  ```
+ `chunked`：一个 bool 值，是否使用分块传输；
  ```python
  @property
  def chunked(self) -> bool:
      return self._chunked
  ```
+ `compression`：一个 bool 值，表示是否启用数据压缩；
  ```python
  @property
  def compression(self) -> bool:
      return self._compression
  ```
+ `reason`：响应行原因；
  ```python
  @property
  def reason(self) -> str:
      return self._reason
  ```
+ `keep_alive`：bool 值，表示是否保持连接；
  ```python
  @property
  def keep_alive(self) -> Optional[bool]:
      return self._keep_alive
  ```
+ `force_close`：关闭连接，此操作不可逆；
  ```python
  def force_close(self) -> None:
      self._keep_alive = False
  ```
+ `body_length`：响应报文的大小；
  ```python
  @property
  def body_length(self) -> int:
      return self._body_length
  ```
+ `enable_chunked_encoding`：使能分块传输，响应头中不能有 Content-Length；
  ```python
  def enable_chunked_encoding(self) -> None:
     """Enables automatic chunked transfer encoding."""
     self._chunked = True

     if hdrs.CONTENT_LENGTH in self._headers:
         raise RuntimeError(
             "You can't enable chunked encoding when " "a content length is set"
         )
  ```
+ `enable_compression`：使能数据压缩；
  ```python
  def enable_compression(self, force: Optional[ContentCoding] = None) -> None:
      """Enables response compression encoding."""
      self._compression = True
      # force 是压缩编码方式
      self._compression_force = force
  ```
+ `headers`：一个 CIMultiDict 对象，包含响应头信息；
  ```python
  @property
  def headers(self) -> "CIMultiDict[str]":
      return self._headers
  ```
+ `content_length`：返回或更新响应头 Content-Length 的值，如果没有返回 None；
  ```python
  @property
  def content_length(self) -> Optional[int]:
      # Just a placeholder for adding setter
      return super().content_length

  @content_length.setter
  def content_length(self, value: Optional[int]) -> None:
      if value is not None:
          value = int(value)
          # 不能是分块传输
          if self._chunked:
              raise RuntimeError(
                  "You can't set content length when " "chunked encoding is enable"
              )
          self._headers[hdrs.CONTENT_LENGTH] = str(value)
      else:
          self._headers.pop(hdrs.CONTENT_LENGTH, None)
  ```
+ `content_type`：返回或更新 Content-Type 的值，例如：`application/octet-stream`，不包含后面的`key=value`内容；
  ```python
  @property
  def content_type(self) -> str:
      # Just a placeholder for adding setter
      return super().content_type

  @content_type.setter
  def content_type(self, value: str) -> None:
      # 用来更新 self._content_dict 变量，存储后面的 key=value 内容
      self.content_type  # read header values if needed
      self._content_type = str(value)
      # 更新 Content-Type 全部值字符串，包括后面的 key=value 内容
      self._generate_content_type_header()

  def _generate_content_type_header(
      self, CONTENT_TYPE: istr = hdrs.CONTENT_TYPE
  ) -> None:
      assert self._content_dict is not None
      assert self._content_type is not None
      params = "; ".join(f"{k}={v}" for k, v in self._content_dict.items())
      if params:
          ctype = self._content_type + "; " + params
      else:
          ctype = self._content_type
      self._headers[CONTENT_TYPE] = ctype
  ```
+ `charset`：返回或更新 Content-Type 的 charset 部分（charset 的值），也就是后面的`charset=xxx`部分；
  ```python
  @property
  def charset(self) -> Optional[str]:
      # Just a placeholder for adding setter
      return super().charset

  @charset.setter
  def charset(self, value: Optional[str]) -> None:
      # 用来更新 self._content_dict 变量，存储后面的 key=value 内容
      ctype = self.content_type  # read header values if needed
      if ctype == "application/octet-stream":
          raise RuntimeError(
              "Setting charset for application/octet-stream "
              "doesn't make sense, setup content_type first"
          )
      assert self._content_dict is not None
      if value is None:
          # 删除
          self._content_dict.pop("charset", None)
      else:
          # 更新 charset 的值
          self._content_dict["charset"] = str(value).lower()
      # 更新 Content-Type 全部值字符串
      self._generate_content_type_header()
  ```
+ `last_modified`：返回或更新 Last-Modified 响应头值；
  ```python
  @property
  def last_modified(self) -> Optional[datetime.datetime]:
      """The value of Last-Modified HTTP header, or None.

      This header is represented as a `datetime` object.
      """
      return parse_http_date(self._headers.get(hdrs.LAST_MODIFIED))

  @last_modified.setter
  def last_modified(
      self, value: Optional[Union[int, float, datetime.datetime, str]]
  ) -> None:
      if value is None:
          # 删除
          self._headers.pop(hdrs.LAST_MODIFIED, None)
      elif isinstance(value, (int, float)):
          self._headers[hdrs.LAST_MODIFIED] = time.strftime(
              "%a, %d %b %Y %H:%M:%S GMT", time.gmtime(math.ceil(value))
          )
      elif isinstance(value, datetime.datetime):
          self._headers[hdrs.LAST_MODIFIED] = time.strftime(
              "%a, %d %b %Y %H:%M:%S GMT", value.utctimetuple()
          )
      elif isinstance(value, str):
          self._headers[hdrs.LAST_MODIFIED] = value
  ```
+ `etag`：返回或更新响应头 Etag 的值；
  ```python
  @property
  def etag(self) -> Optional[ETag]:
      quoted_value = self._headers.get(hdrs.ETAG)
      if not quoted_value:
          return None
      # ETAG_ANY = "*"
      elif quoted_value == ETAG_ANY:
          return ETag(value=ETAG_ANY)
      match = QUOTED_ETAG_RE.fullmatch(quoted_value)
      if not match:
          return None
      is_weak, value = match.group(1, 2)
      return ETag(
          is_weak=bool(is_weak),
          value=value,
      )

  @etag.setter
  def etag(self, value: Optional[Union[ETag, str]]) -> None:
      if value is None:
          # 删除
          self._headers.pop(hdrs.ETAG, None)
      # ETAG_ANY = "*"
      elif (isinstance(value, str) and value == ETAG_ANY) or (
          isinstance(value, ETag) and value.value == ETAG_ANY
      ):
          self._headers[hdrs.ETAG] = ETAG_ANY
      elif isinstance(value, str):
          validate_etag_value(value)
          self._headers[hdrs.ETAG] = f'"{value}"'
      elif isinstance(value, ETag) and isinstance(value.value, str):  # type: ignore[redundant-expr]
          validate_etag_value(value.value)
          hdr_value = f'W/"{value.value}"' if value.is_weak else f'"{value.value}"'
          self._headers[hdrs.ETAG] = hdr_value
      else:
          raise ValueError(
              f"Unsupported etag type: {type(value)}. "
              f"etag must be str, ETag or None"
          )
  ```
## 数据准备与发送
响应数据准备阶段包括响应头设置、执行钩子函数（触发响应准备信号）和发送响应头。
相关源码如下：
```python
async def prepare(self, request: "BaseRequest") -> Optional[AbstractStreamWriter]:
    # 判断是否写结束
    if self._eof_sent:
        return None
    # prepare 已经被执行过
    if self._payload_writer is not None:
        return self._payload_writer
    # 响应体是否为空
    self._must_be_empty_body = must_be_empty_body(request.method, self.status)
    return await self._start(request)

async def _start(self, request: "BaseRequest") -> AbstractStreamWriter:
    # 设置构建的请求对象
    self._req = request
    # 设置流式写对象，用于发送响应报文
    writer = self._payload_writer = request._payload_writer

    await self._prepare_headers()
    await request._prepare_hook(self)
    await self._write_headers()

    return writer
```
第一步准备响应头的源码实现如下：
```python
async def _prepare_headers(self) -> None:
    request = self._req
    assert request is not None
    writer = self._payload_writer
    assert writer is not None
    keep_alive = self._keep_alive
    if keep_alive is None:
        # 如果响应头没有指定 keep_alive，则使用请求中指定的 keep_alive
        keep_alive = request.keep_alive
    self._keep_alive = keep_alive
    # 协议版本
    version = request.version

    headers = self._headers
    # 设置 cookies 信息
    populate_with_cookies(headers, self.cookies)
    # 开始数据压缩
    if self._compression:
        await self._start_compression(request)
    # 分块传输
    if self._chunked:
        if version != HttpVersion11:
            raise RuntimeError(
                "Using chunked encoding is forbidden "
                "for HTTP/{0.major}.{0.minor}".format(request.version)
            )
        # 有响应体，给流式写对象设置分块传输，更新响应头 Transfer-Encoding=chunked
        if not self._must_be_empty_body:
            writer.enable_chunking()
            headers[hdrs.TRANSFER_ENCODING] = "chunked"
        # 如果响应头有 Content-Length，删除
        if hdrs.CONTENT_LENGTH in headers:
            del headers[hdrs.CONTENT_LENGTH]
    # 检查响应头 Content-Length
    elif self._length_check:
        # 设置流式写对象最多发送的响应体的大小
        writer.length = self.content_length
        if writer.length is None:
            # 响应头没有 Content-Length
            if version >= HttpVersion11:
                # 有响应体，给流式写对象设置分块传输，
                # 更新响应头 Transfer-Encoding=chunked
                if not self._must_be_empty_body:
                    writer.enable_chunking()
                    headers[hdrs.TRANSFER_ENCODING] = "chunked"
            elif not self._must_be_empty_body:
                keep_alive = False

    # HTTP 1.1: https://tools.ietf.org/html/rfc7230#section-3.3.2
    # HTTP 1.0: https://tools.ietf.org/html/rfc1945#section-10.4
    # 空的响应体
    if self._must_be_empty_body:
        # 删除响应头中的 Content-Length
        if hdrs.CONTENT_LENGTH in headers and should_remove_content_length(
            request.method, self.status
        ):
            del headers[hdrs.CONTENT_LENGTH]
        # https://datatracker.ietf.org/doc/html/rfc9112#section-6.1-10
        # https://datatracker.ietf.org/doc/html/rfc9112#section-6.1-13
        # 删除响应头中的 Transfer-Encoding
        if hdrs.TRANSFER_ENCODING in headers:
            del headers[hdrs.TRANSFER_ENCODING]
    else:
        # 设置 Content-Type 响应头
        headers.setdefault(hdrs.CONTENT_TYPE, "application/octet-stream")
    # 设置 Date 响应头
    headers.setdefault(hdrs.DATE, rfc822_formatted_time())
    # 设置 Server 响应头
    # SERVER_SOFTWARE: str = "Python/{0[0]}.{0[1]} aiohttp/{1}".format(sys.version_info, __version__)
    headers.setdefault(hdrs.SERVER, SERVER_SOFTWARE)
    # 设置 Connection 响应头
    # connection header
    if hdrs.CONNECTION not in headers:
        if keep_alive:
            if version == HttpVersion10:
                headers[hdrs.CONNECTION] = "keep-alive"
        else:
            if version == HttpVersion11:
                headers[hdrs.CONNECTION] = "close"
```
在准备响应头`_prepare_headers`源码中，数据压缩的源码实现如下：
```python
async def _do_start_compression(self, coding: ContentCoding) -> None:
    # 编码方式不是 identity
    if coding != ContentCoding.identity:
        assert self._payload_writer is not None
        # 设置响应头 Content-Encoding
        self._headers[hdrs.CONTENT_ENCODING] = coding.value
        # 用指定的编码，开启流式写对象的数据编码
        self._payload_writer.enable_compression(coding.value)
        # Compressed payload may have different content length,
        # remove the header
        # 删除原始响应头 Content-Length
        self._headers.popall(hdrs.CONTENT_LENGTH, None)

async def _start_compression(self, request: "BaseRequest") -> None:
    # 指定了压缩编码方式
    if self._compression_force:
        await self._do_start_compression(self._compression_force)
    else:
        # Encoding comparisons should be case-insensitive
        # https://www.rfc-editor.org/rfc/rfc9110#section-8.4.1
        # 使用请求头 Accept-Encoding 指定的编码方式
        accept_encoding = request.headers.get(hdrs.ACCEPT_ENCODING, "").lower()
        # ContentCoding 包含 deflate/gzip/identity 三种编码方式
        for coding in ContentCoding:
            if coding.value in accept_encoding:
                await self._do_start_compression(coding)
                return
```
根据源码可知，压缩编码方式可以指定，如果没指定会取请求头 Accept-Encoding 指定的值。

第二步执行钩子函数（触发响应准备信号）源码如下：
```python
async def _prepare_hook(self, response: StreamResponse) -> None:
    match_info = self._match_info
    if match_info is None:
        return
    for app in match_info._apps:
        # 这里的 self 是 Request 对象
        await app.on_response_prepare.send(self, response)
```
相关实现在请求体对象中`Request._prepare_hook`，主要是发送响应准备信号`on_response_prepare`。

第三步发送响应头相关源码如下：
```python
async def _write_headers(self) -> None:
    request = self._req
    assert request is not None
    writer = self._payload_writer
    assert writer is not None
    # status line
    version = request.version
    # 构造响应行，例如 HTTP/1.1 200 OK
    status_line = "HTTP/{}.{} {} {}".format(
        version[0], version[1], self._status, self._reason
    )
    # 委托底层的流式写对象 StreamWriter 进行发送
    await writer.write_headers(status_line, self._headers)
```
响应数据发送的源码如下：
```python
async def write(self, data: bytes) -> None:
    assert isinstance(
        data, (bytes, bytearray, memoryview)
    ), "data argument must be byte-ish (%r)" % type(data)

    if self._eof_sent:
        raise RuntimeError("Cannot call write() after write_eof()")
    if self._payload_writer is None:
        raise RuntimeError("Cannot call write() before prepare()")

    await self._payload_writer.write(data)

async def write_eof(self, data: bytes = b"") -> None:
    assert isinstance(
        data, (bytes, bytearray, memoryview)
    ), "data argument must be byte-ish (%r)" % type(data)

    if self._eof_sent:
        return

    assert self._payload_writer is not None, "Response has not been started"

    await self._payload_writer.write_eof(data)
    # 设置发送完成标志
    self._eof_sent = True
    self._req = None
    # 更新响应报文的大小
    self._body_length = self._payload_writer.output_size
    self._payload_writer = None
```
`write`：用于发送响应体数据；`write_eof`：用于通知响应体数据发送完成。

# Response
`Response`继承`StreamResponse`，下面对`Response`独有地方进行说明。
## 初始化
`Response`类初始化源码如下：
```python
class Response(StreamResponse):
    def __init__(
        self,
        *,
        body: Any = None,
        status: int = 200,
        reason: Optional[str] = None,
        text: Optional[str] = None,
        headers: Optional[LooseHeaders] = None,
        content_type: Optional[str] = None,
        charset: Optional[str] = None,
        zlib_executor_size: Optional[int] = None,
        zlib_executor: Optional[Executor] = None,
    ) -> None:
        if body is not None and text is not None:
            raise ValueError("body and text are not allowed together")
        # 参数指定的响应头
        if headers is None:
            real_headers: CIMultiDict[str] = CIMultiDict()
        elif not isinstance(headers, CIMultiDict):
            real_headers = CIMultiDict(headers)
        else:
            real_headers = headers  # = cast('CIMultiDict[str]', headers)
        # 参数 content_type 不能包含 charset
        if content_type is not None and "charset" in content_type:
            raise ValueError("charset must not be in content_type " "argument")
        # text 表示响应体内容，字符串形式
        if text is not None:
            # 如果响应头有 Content-Type，则参数 content_type 或者 charset 都不能传
            if hdrs.CONTENT_TYPE in real_headers:
                if content_type or charset:
                    raise ValueError(
                        "passing both Content-Type header and "
                        "content_type or charset params "
                        "is forbidden"
                    )
            # 响应头没有 Content-Type
            else:
                # fast path for filling headers
                if not isinstance(text, str):
                    raise TypeError("text argument must be str (%r)" % type(text))
                if content_type is None:
                    content_type = "text/plain"
                if charset is None:
                    charset = "utf-8"
                # 设置 Content-Type 响应头
                real_headers[hdrs.CONTENT_TYPE] = content_type + "; charset=" + charset
                # 编码响应体
                body = text.encode(charset)
                text = None
        else:
            # 如果响应头有 Content-Type，则参数 content_type 或者 charset 都不能传
            if hdrs.CONTENT_TYPE in real_headers:
                if content_type is not None or charset is not None:
                    raise ValueError(
                        "passing both Content-Type header and "
                        "content_type or charset params "
                        "is forbidden"
                    )
            # 响应头没有 Content-Type
            else:
                if content_type is not None:
                    if charset is not None:
                        content_type += "; charset=" + charset
                    # 设置 Content-Type 响应头
                    real_headers[hdrs.CONTENT_TYPE] = content_type

        super().__init__(status=status, reason=reason, headers=real_headers)

        if text is not None:
            # 更新 text 属性
            self.text = text
        else:
            # 更新响应体属性 字节对象
            self.body = body
        # 表示压缩后的响应体内容
        self._compressed_body: Optional[bytes] = None
        # 下面两个参数用于 zlib 压缩
        self._zlib_executor_size = zlib_executor_size
        self._zlib_executor = zlib_executor
```
增加额外的初始化内容主要是初始化响应体`self.body`和设置响应头`Content-Type`。响应体通过参数初始化有两种方式：
+ `text`：一个字符串对象;
+ `body`：一个字节对象；

## 属性
下面主要是新增属性
+ `body`：返回或者更新响应体数据，字节对象；
  ```python
  @property
  def body(self) -> Optional[Union[bytes, Payload]]:
      return self._body

  @body.setter
  def body(self, body: bytes) -> None:
      if body is None:
          self._body: Optional[bytes] = None
          self._body_payload: bool = False
      elif isinstance(body, (bytes, bytearray)):
          self._body = body
          self._body_payload = False
      else:
          try:
              self._body = body = payload.PAYLOAD_REGISTRY.get(body)
          except payload.LookupError:
              raise ValueError("Unsupported body type %r" % type(body))
          # 响应体是 payload 对象
          # Assigning str to body will make the body type of aiohttp.payload.StringPayload, 
          # which tries to encode the given data based on Content-Type HTTP header, 
          # while defaulting to UTF-8
          self._body_payload = True

          headers = self._headers

          # set content-type
          if hdrs.CONTENT_TYPE not in headers:
              headers[hdrs.CONTENT_TYPE] = body.content_type

          # copy payload headers
          if body.headers:
              for key, value in body.headers.items():
                  if key not in headers:
                      headers[key] = value

      self._compressed_body = None
  ```
  TODO payload 对象

+ `text`：返回或更新响应体数据，字符串对象；
  ```python
  @property
  def text(self) -> Optional[str]:
      if self._body is None:
          return None
      return self._body.decode(self.charset or "utf-8")

  @text.setter
  def text(self, text: str) -> None:
      assert isinstance(text, str), "text argument must be str (%r)" % type(text)

      if self.content_type == "application/octet-stream":
          # 更新 content_type 属性
          self.content_type = "text/plain"
      if self.charset is None:
          # 更新 charset 属性
          self.charset = "utf-8"
      # 设置响应体
      self._body = text.encode(self.charset)
      self._body_payload = False
      self._compressed_body = None
  ```
+ `content_length`：返回响应体的大小；
  ```python
  @property
  def content_length(self) -> Optional[int]:
      if self._chunked:
          return None

      if hdrs.CONTENT_LENGTH in self._headers:
          return super().content_length

      if self._compressed_body is not None:
          # Return length of the compressed body
          return len(self._compressed_body)
      elif self._body_payload:
          # A payload without content length, or a compressed payload
          return None
      elif self._body is not None:
          return len(self._body)
      else:
          return 0

  @content_length.setter
  def content_length(self, value: Optional[int]) -> None:
      raise RuntimeError("Content length is set automatically")
  ```
## 数据准备与发送
`Response`的数据发送部分会复写父类的`write_eof`方法，对应的相关源码如下：
```python
async def write_eof(self, data: bytes = b"") -> None:
    # 是否写结束
    if self._eof_sent:
        return
    # 响应体没有压缩
    if self._compressed_body is None:
        body: Optional[Union[bytes, Payload]] = self._body
    # 响应体压缩
    else:
        body = self._compressed_body
    assert not data, f"data arg is not supported, got {data!r}"
    assert self._req is not None
    assert self._payload_writer is not None
    # 有响应体会先发送响应体数据，然后通知写结束
    if body is not None:
        # 不能发送响应体 直接调用父类 write_eof，通知写结束
        if self._must_be_empty_body:
            await super().write_eof()
        # 响应体是 payload 对象
        elif self._body_payload:
            payload = cast(Payload, body)
            await payload.write(self._payload_writer)
            await super().write_eof()
        else:
            await super().write_eof(cast(bytes, body))
    # 没有响应体，直接调用父类 write_eof，通知写结束
    else:
        await super().write_eof()
```
如果有响应体，会先发送响应体数据，然后通知写结束。

`Response`数据准备（响应头准备）会复写父类的`_start`方法，数据压缩会复写父类的`_do_start_compression`方法，相关源码如下：
```python
async def _start(self, request: "BaseRequest") -> AbstractStreamWriter:
    if should_remove_content_length(request.method, self.status):
        if hdrs.CONTENT_LENGTH in self._headers:
            del self._headers[hdrs.CONTENT_LENGTH]
    # 不是分块传输，且响应头也不包含 Content-Length
    elif not self._chunked and hdrs.CONTENT_LENGTH not in self._headers:
        # 响应体数据是 payload 对象
        if self._body_payload:
            size = cast(Payload, self._body).size
            # 更新响应头 Content-Length
            if size is not None:
                self._headers[hdrs.CONTENT_LENGTH] = str(size)
        else:
            # 更新响应头 Content-Length
            body_len = len(self._body) if self._body else "0"
            # https://www.rfc-editor.org/rfc/rfc9110.html#section-8.6-7
            if body_len != "0" or (
                self.status != 304 and request.method.upper() != hdrs.METH_HEAD
            ):
                self._headers[hdrs.CONTENT_LENGTH] = str(body_len)

    return await super()._start(request)

async def _do_start_compression(self, coding: ContentCoding) -> None:
    if self._body_payload or self._chunked:
        # 父类中会移除 Content-Length 响应头，对于非分块传输，
        # 需要 Content-Length 响应头，需要走下面的流程
        return await super()._do_start_compression(coding)

    if coding != ContentCoding.identity:
        # Instead of using _payload_writer.enable_compression,
        # compress the whole body
        compressor = ZLibCompressor(
            encoding=str(coding.value),
            max_sync_chunk_size=self._zlib_executor_size,
            executor=self._zlib_executor,
        )
        assert self._body is not None
        if self._zlib_executor_size is None and len(self._body) > 1024 * 1024:
            warnings.warn(
                "Synchronous compression of large response bodies "
                f"({len(self._body)} bytes) might block the async event loop. "
                "Consider providing a custom value to zlib_executor_size/"
                "zlib_executor response properties or disabling compression on it."
            )
        self._compressed_body = (
            await compressor.compress(self._body) + compressor.flush()
        )
        assert self._compressed_body is not None

        self._headers[hdrs.CONTENT_ENCODING] = coding.value
        self._headers[hdrs.CONTENT_LENGTH] = str(len(self._compressed_body))
```
+ `_start`主要增加更新响应头 Content-Length；
+ `_do_start_compression`：对整个请求体进行压缩而不是对发送的 chunk 数据压缩；

# json_response
`json_response`方法基于`Response`实现，用于响应 json 类型的数据，源码实现如下：
```python
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

# FileResponse
TODO

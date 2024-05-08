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

aiohttp 为 http 响应提供了三个类：`StreamResponse`、`Response`和`FileResponse`。
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

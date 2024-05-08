# 请求解析
主要完成对 http 请求报文的解析工作，http 请求报文由请求行，请求头部，空行，请求体组成。样例说明如下：
```bash
# GET 请求没有请求体
# 下面一行是请求行
GET /index.html HTTP/1.1
# 下面三行是请求头部
Host: www.example.com
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.99 Safari/537.36
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8
# 下面是个空行，必须有

```
```bash
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
```
```bash
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
```
上面的分块传输样例请求体每个块格式如下：
```bash
长度\r\n
数据\r\n
```
长度 0 表示请求体接收，结束样例如下：
```bash
0\r\n
\r\n
```

下面看一下 http 请求报文解析的相关源码实现，先看下初始化：
```python
class HttpParser(abc.ABC, Generic[_MsgT]):
    lax: ClassVar[bool] = False

    def __init__(
        self,
        protocol: BaseProtocol,
        loop: asyncio.AbstractEventLoop,
        limit: int,
        max_line_size: int = 8190,
        max_field_size: int = 8190,
        timer: Optional[BaseTimerContext] = None,
        code: Optional[int] = None,
        method: Optional[str] = None,
        readall: bool = False,
        payload_exception: Optional[Type[BaseException]] = None,
        response_with_body: bool = True,
        read_until_eof: bool = False,
        auto_decompress: bool = True,
    ) -> None:
        self.protocol = protocol
        self.loop = loop
        # 请求行或状态行的最大长度
        self.max_line_size = max_line_size
        # 请求头一行的最大长度
        self.max_field_size = max_field_size
        self.timer = timer
        # 状态码
        self.code = code
        # 请求方法
        self.method = method
        self.readall = readall
        self.payload_exception = payload_exception
        self.response_with_body = response_with_body
        self.read_until_eof = read_until_eof

        self._lines: List[bytes] = []
        # 记录当前调用未处理的原始请求数据
        self._tail = b""
        self._upgraded = False
        self._payload = None
        self._payload_parser: Optional[HttpPayloadParser] = None
        self._auto_decompress = auto_decompress
        self._limit = limit
        self._headers_parser = HeadersParser(max_line_size, max_field_size, self.lax)
```
请求报文的解析逻辑主要在`feed_data`方法中完成，`feed_data`主要完成以下工作：
+ 获取请求行和请求头数据，存放到`self._lines`中；
+ 执行`self.parse_message(self._lines)`方法，解析请求行和请求头数据；
+ 如果有请求体，初始化请求体解析实例`self._payload_parser`；
+ 如果有请求体的数据，调用`self._payload_parser.feed_data`方法处理请求体；

## 获取请求行和请求头
我们先看第一步：获取请求行和请求头数据。其相关源码如下：
```python
def feed_data(
    self,
    data: bytes,
    SEP: _SEP = b"\r\n",
    EMPTY: bytes = b"",
    CONTENT_LENGTH: istr = hdrs.CONTENT_LENGTH,
    METH_CONNECT: str = hdrs.METH_CONNECT,
    SEC_WEBSOCKET_KEY1: istr = hdrs.SEC_WEBSOCKET_KEY1,
) -> Tuple[List[Tuple[_MsgT, StreamReader]], bool, bytes]:
    messages = []

    if self._tail:
        # 如果上次有未处理完的数据，这次追加到新数据前面
        data, self._tail = self._tail + data, b""

    data_len = len(data)
    start_pos = 0
    loop = self.loop

    while start_pos < data_len:
        # read HTTP message (request/response line + headers), \r\n\r\n
        # and split by lines
        if self._payload_parser is None and not self._upgraded:
            # 解析请求行+请求头，每一行都以 \r\n 结束
            pos = data.find(SEP, start_pos)
            # consume \r\n
            if pos == start_pos and not self._lines:
                # 遇到额外的多余的 \r\n 直接忽略
                start_pos = pos + len(SEP)
                continue

            if pos >= start_pos:
                # 当前的数据 data 包含换行符
                # line found
                # 一行的内容，不包括 \r\n
                line = data[start_pos:pos]
                if SEP == b"\n":  # For lax response parsing
                    line = line.rstrip(b"\r")
                self._lines.append(line)
                start_pos = pos + len(SEP)

                # \r\n\r\n found （收到请求头下面的空行）
                if self._lines[-1] == EMPTY:
                    try:
                        # 第二步：解析请求行+请求头
                        msg: _MsgT = self.parse_message(self._lines)
                    finally:
                        self._lines.clear()
                    ...
            else:
                # 当前的数据 data 不包含完整的一行数据，将数据记录到 self._tail，延迟到下次调用处理
                self._tail = data[start_pos:]
                data = EMPTY
                break
        ...

    ...

    return messages, self._upgraded, data
```
## 解析请求行和请求头
接下来看第二步：解析请求行和请求头数据。其相关源码如下：
```python
def parse_message(self, lines: List[bytes]) -> RawRequestMessage:
    # request line
    # 例如：GET /index.html HTTP/1.1
    line = lines[0].decode("utf-8", "surrogateescape")
    try:
        # 例如：method: GET，path: /index.html，version: HTTP/1.1
        method, path, version = line.split(" ", maxsplit=2)
    except ValueError:
        raise BadStatusLine(line) from None

    if len(path) > self.max_line_size:
        raise LineTooLong(
            "Status line is too long", str(self.max_line_size), str(len(path))
        )

    # method
    if not TOKENRE.fullmatch(method):
        raise BadStatusLine(method)

    # version
    match = VERSRE.fullmatch(version)
    if match is None:
        raise BadStatusLine(line)
    # 例如：version_o: 1.1
    version_o = HttpVersion(int(match.group(1)), int(match.group(2)))

    if method == "CONNECT":
        # authority-form,
        # https://datatracker.ietf.org/doc/html/rfc7230#section-5.3.3
        # 例如请求行是：CONNECT www.example.com:80 HTTP/1.1 此时 path: www.example.com:80
        url = URL.build(authority=path, encoded=True)
    elif path.startswith("/"):
        # origin-form,
        # https://datatracker.ietf.org/doc/html/rfc7230#section-5.3.1
        # 例如请求行是：GET /where?q=now HTTP/1.1  此时 path: /where?q=now
        path_part, _hash_separator, url_fragment = path.partition("#")
        path_part, _question_mark_separator, qs_part = path_part.partition("?")

        # NOTE: `yarl.URL.build()` is used to mimic what the Cython-based
        # NOTE: parser does, otherwise it results into the same
        # NOTE: HTTP Request-Line input producing different
        # NOTE: `yarl.URL()` objects
        url = URL.build(
            path=path_part,
            query_string=qs_part,
            fragment=url_fragment,
            encoded=True,
        )
    elif path == "*" and method == "OPTIONS":
        # asterisk-form,
        # 例如请求行是：OPTIONS * HTTP/1.1  此时 path: *
        url = URL(path, encoded=True)
    else:
        # absolute-form for proxy maybe,
        # https://datatracker.ietf.org/doc/html/rfc7230#section-5.3.2
        # 例如请求行是：GET http://www.example.org/pub/WWW/TheProject.html HTTP/1.1
        # 此时 path: http://www.example.org/pub/WWW/TheProject.html
        url = URL(path, encoded=True)
        if url.scheme == "":
            # not absolute-form
            raise InvalidURLError(
                path.encode(errors="surrogateescape").decode("latin1")
            )

    # read headers
    (
        headers,
        raw_headers,
        close,
        compression,
        upgrade,
        chunked,
    ) = self.parse_headers(lines)

    if close is None:  # then the headers weren't set in the request
        if version_o <= HttpVersion10:  # HTTP 1.0 must asks to not close
            close = True
        else:  # HTTP 1.1 must ask to close.
            # HTTP 1.1 默认保持长连接
            close = False

    return RawRequestMessage(
        method,
        path,
        version_o,
        headers,
        raw_headers,
        close,
        compression,
        upgrade,
        chunked,
        url,
    )
```
> http 发送的请求目标有四种形式：<br>
> + **origin-form**
>> 当直接向服务器发起请求时，除开 CONNECT 和 OPTIONS 请求，只允许发送 path 和 query 作为请求资源。
如果请求链接的 path 为空，则必须发送 `/` 作为请求资源。请求链接中的 Host 信息以 Header 头的形式发送。
例如如果希望请求 `http://www.example.org/where?q=now`，则需要发送请求应该是
>> ```bash
>> GET /where?q=now HTTP/1.1
>> Host: www.example.org
>> ```
> + **absolute-form**
>> 向代理发起请求时，请求行的 path 必须是完整的 url，例如 
>> ```bash
>> GET http://www.example.org/pub/WWW/TheProject.html HTTP/1.1
>> ```
> + **authority-form**
>> 向代理服务发送 CONNECT 请求建立隧道时，client 只能发送 URI 的 authority 部分（不包含 userinfo 和 @ 定界符）作为请求资源，
>> 例如 
>> ```bash
>> CONNECT www.example.com:80 HTTP/1.1
>> ```
> + **asterisk-form**
>> 仅适用于 OPTIONS 请求且只能为`*`，例如
>> ```bash
>> OPTIONS * HTTP/1.1
>> ```

由源码可知，`parse_message`方法主要完成以下工作：
+ 解析请求行`lines[0]`，获取`method`、`path`、`version_o`及`url`信息；
+ 执行`self.parse_headers(lines)`方法，解析请求头数据；

其中解析请求头`self.parse_headers`方法的源码如下：
```python
def parse_headers(
    self, lines: List[bytes]
) -> Tuple[
    "CIMultiDictProxy[str]", RawHeaders, Optional[bool], Optional[str], bool, bool
]:
    """Parses RFC 5322 headers from a stream.

    Line continuations are supported. Returns list of header name
    and value pairs. Header name is in upper case.
    """
    headers, raw_headers = self._headers_parser.parse_headers(lines)
    close_conn = None
    encoding = None
    upgrade = False
    chunked = False

    # https://www.rfc-editor.org/rfc/rfc9110.html#section-5.5-6
    # https://www.rfc-editor.org/rfc/rfc9110.html#name-collected-abnf
    # 这些 header 在请求中最多出现一次
    singletons = (
        hdrs.CONTENT_LENGTH,
        hdrs.CONTENT_LOCATION,
        hdrs.CONTENT_RANGE,
        hdrs.CONTENT_TYPE,
        hdrs.ETAG,
        hdrs.HOST,
        hdrs.MAX_FORWARDS,
        hdrs.SERVER,
        hdrs.TRANSFER_ENCODING,
        hdrs.USER_AGENT,
    )
    bad_hdr = next((h for h in singletons if len(headers.getall(h, ())) > 1), None)
    if bad_hdr is not None:
        raise BadHttpMessage(f"Duplicate '{bad_hdr}' header found.")

    # keep-alive
    conn = headers.get(hdrs.CONNECTION)
    if conn:
        v = conn.lower()
        if v == "close":
            # 短连接
            close_conn = True
        elif v == "keep-alive":
            # 长连接
            close_conn = False
        # https://www.rfc-editor.org/rfc/rfc9110.html#name-101-switching-protocols
        elif v == "upgrade" and headers.get(hdrs.UPGRADE):
            # 升级协议
            upgrade = True

    # encoding
    enc = headers.get(hdrs.CONTENT_ENCODING)
    if enc:
        enc = enc.lower()
        if enc in ("gzip", "deflate", "br"):
            # 数据编码方式
            encoding = enc

    # chunking
    te = headers.get(hdrs.TRANSFER_ENCODING)
    if te is not None:
        if "chunked" == te.lower():
            # 分块传输
            chunked = True
        else:
            raise BadHttpMessage("Request has invalid `Transfer-Encoding`")

        # 确保 Content-Length 和 分块传输不能同时存在
        if hdrs.CONTENT_LENGTH in headers:
            raise BadHttpMessage(
                "Transfer-Encoding can't be present with Content-Length",
            )

    return (headers, raw_headers, close_conn, encoding, upgrade, chunked)
```
根据源码可知，解析请求头最终会委托调用`HeadersParser.parse_headers`方法，其源码实现如下：
```python
class HeadersParser:
    def __init__(
        self, max_line_size: int = 8190, max_field_size: int = 8190, lax: bool = False
    ) -> None:
        self.max_line_size = max_line_size
        self.max_field_size = max_field_size
        self._lax = lax

    def parse_headers(
        self, lines: List[bytes]
    ) -> Tuple["CIMultiDictProxy[str]", RawHeaders]:
        headers: CIMultiDict[str] = CIMultiDict()
        # note: "raw" does not mean inclusion of OWS before/after the field value
        raw_headers = []

        lines_idx = 1
        # 拿到第一个请求头，因为lines[0]表示请求行
        line = lines[1]
        line_count = len(lines)

        while line:
            # Parse initial header name : value pair.
            try:
                bname, bvalue = line.split(b":", 1)
            except ValueError:
                raise InvalidHeader(line) from None

            if len(bname) == 0:
                raise InvalidHeader(bname)

            # https://www.rfc-editor.org/rfc/rfc9112.html#section-5.1-2
            if {bname[0], bname[-1]} & {32, 9}:  # {" ", "\t"}
                raise InvalidHeader(line)

            bvalue = bvalue.lstrip(b" \t")
            if len(bname) > self.max_field_size:
                raise LineTooLong(
                    "request header name {}".format(
                        bname.decode("utf8", "backslashreplace")
                    ),
                    str(self.max_field_size),
                    str(len(bname)),
                )
            name = bname.decode("utf-8", "surrogateescape")
            if not TOKENRE.fullmatch(name):
                raise InvalidHeader(bname)

            header_length = len(bvalue)

            # next line
            lines_idx += 1
            line = lines[lines_idx]

            # consume continuation lines
            continuation = self._lax and line and line[0] in (32, 9)  # (' ', '\t')

            if continuation:
                # 处理一个请求头有多行的情况
                bvalue_lst = [bvalue]
                while continuation:
                    header_length += len(line)
                    if header_length > self.max_field_size:
                        raise LineTooLong(
                            "request header field {}".format(
                                bname.decode("utf8", "backslashreplace")
                            ),
                            str(self.max_field_size),
                            str(header_length),
                        )
                    bvalue_lst.append(line)

                    # next line
                    lines_idx += 1
                    if lines_idx < line_count:
                        line = lines[lines_idx]
                        if line:
                            continuation = line[0] in (32, 9)  # (' ', '\t')
                    else:
                        line = b""
                        break
                bvalue = b"".join(bvalue_lst)
            else:
                if header_length > self.max_field_size:
                    raise LineTooLong(
                        "request header field {}".format(
                            bname.decode("utf8", "backslashreplace")
                        ),
                        str(self.max_field_size),
                        str(header_length),
                    )

            bvalue = bvalue.strip(b" \t")
            value = bvalue.decode("utf-8", "surrogateescape")

            # https://www.rfc-editor.org/rfc/rfc9110.html#section-5.5-5
            if "\n" in value or "\r" in value or "\x00" in value:
                raise InvalidHeader(bvalue)

            headers.add(name, value)
            raw_headers.append((bname, bvalue))

        return (CIMultiDictProxy(headers), tuple(raw_headers))
```
`HeadersParser.parse_headers`方法逻辑比较简单，主要就是逐行解析请求头，获取每一个请求头的名字以及对应的值。
返回一个元组，每一项说明如下：
+ `tuple[0]`: 一个只读的字典，其中 key 是大小写不敏感，也就是同一个 key 不能同时存在大写和小写；
+ `tuple[1]`: 一个元组，每一项都是`(bname, bvalue)`形式表示一个请求头名字和取值，`bname`和`bvalue`是字节序列；

我们继续回到调用者`HttpParser.parse_headers`方法内部，方法最后会返回一个元组，每一个元素的说明如下：
+ `headers`: 一个只读的字典，其中 key 是大小写不敏感，也就是同一个 key 不能同时存在大写和小写；
+ `raw_headers`: 一个元组，每一项都是`(bname, bvalue)`形式表示一个请求头名字和取值，`bname`和`bvalue`是字节序列；
+ `close_conn`: 如果请求头中没`Connection`，则取值`None`；如果有`Connection: keep-alive`，则取值为`False`；
如果有`Connection: close`则取值`True`；
+ `encoding`: 如果请求头中没有`Content-Encoding`，则取值`None`；如果有`Content-Encoding`且值属于`(gzip", "deflate", "br")`，
则取值为实际指定的值；否则取值`None`；
+ `upgrade`: 一个`bool`值，如果需要升级协议为`True`，否则为`False`
+ `chunked`: 一个`bool`值，如果是分块传输为`True`，否则为`False`

我们继续往上回到`parse_message`方法。返回是个`RawRequestMessage`数据类型，各个字段的含义如下：
- `method`: 请求行方法，例如 `GET`
- `path`: 请求行中的 `path` 部分，例如 `/index.html`
- `version`: 请求行中协议版本号，例如 `HttpVersion(1, 1)`
- `headers`: 一个只读的字典，包含所有的请求头及值，其中 key 是大小写不敏感，也就是同一个 key 不能同时存在大写和小写；
- `raw_headers`: 一个元组，每一项都是`(bname, bvalue)`形式表示一个请求头名字和取值，`bname`和`bvalue`是字节序列；
- `should_close`: 一个 `bool` 值，控制长连接。http/1.1 默认是 `False`，http/1.0 默认是 `True`；如果请求头有指定，以指定为准；
- `compression`: `str` 类型，压缩类型，如果请求头中不指定或者指定值不在 `("gzip", "deflate", "br")`，取值 `None`，否则按指定值；
- `upgrade`: 一个 `bool` 类型，表示是否升级协议；
- `chunked`: 一个 `bool` 类型，表示是否是分块传输；
- `url`: 从 path 构建的一个 `yarl.URL` 对象；

## 初始化请求体解析
我们继续看`feed_data`中的第三步：如果有请求体，初始化请求体解析实例`self._payload_parser`，相关源码实现如下：
```python
def feed_data(
    self,
    data: bytes,
    SEP: _SEP = b"\r\n",
    EMPTY: bytes = b"",
    CONTENT_LENGTH: istr = hdrs.CONTENT_LENGTH,
    METH_CONNECT: str = hdrs.METH_CONNECT,
    SEC_WEBSOCKET_KEY1: istr = hdrs.SEC_WEBSOCKET_KEY1,
) -> Tuple[List[Tuple[_MsgT, StreamReader]], bool, bytes]:
    messages = []

    ...
    while start_pos < data_len:
        # read HTTP message (request/response line + headers), \r\n\r\n
        # and split by lines
        if self._payload_parser is None and not self._upgraded:
            ...

            if pos >= start_pos:
                ...

                # \r\n\r\n found
                if self._lines[-1] == EMPTY:
                    # 请求头下的空格已经收到，开始构造请求体解析实例
                    ...

                    def get_content_length() -> Optional[int]:
                        # payload length
                        length_hdr = msg.headers.get(CONTENT_LENGTH)
                        if length_hdr is None:
                            return None

                        # Shouldn't allow +/- or other number formats.
                        # https://www.rfc-editor.org/rfc/rfc9110#section-8.6-2
                        # msg.headers is already stripped of leading/trailing wsp
                        if not DIGITS.fullmatch(length_hdr):
                            raise InvalidHeader(CONTENT_LENGTH)

                        return int(length_hdr)

                    # 获取请求头中 Content-Length 值
                    length = get_content_length()
                    # do not support old websocket spec
                    if SEC_WEBSOCKET_KEY1 in msg.headers:
                        raise InvalidHeader(SEC_WEBSOCKET_KEY1)

                    self._upgraded = msg.upgrade and _is_supported_upgrade(msg.headers)

                    method = getattr(msg, "method", self.method)
                    # code is only present on responses
                    code = getattr(msg, "code", 0)

                    assert self.protocol is not None
                    # calculate payload
                    # 状态码 code in {204, 304} or 100 <= code < 200 或者
                    # method.upper() == hdrs.METH_HEAD 表示没有请求体
                    empty_body = status_code_must_be_empty_body(code) or bool(
                        method and method_must_be_empty_body(method)
                    )
                    if not empty_body and (
                        ((length is not None and length > 0) or msg.chunked)
                        and not self._upgraded
                    ):
                        # 有请求体，请求头有 Content-Length 或者是分块传输，且不是升级协议请求
                        payload = StreamReader(
                            self.protocol,
                            timer=self.timer,
                            loop=loop,
                            limit=self._limit,
                        )
                        payload_parser = HttpPayloadParser(
                            payload,
                            length=length,
                            chunked=msg.chunked,
                            method=method,
                            compression=msg.compression,
                            code=self.code,
                            readall=self.readall,
                            response_with_body=self.response_with_body,
                            auto_decompress=self._auto_decompress,
                            lax=self.lax,
                        )
                        if not payload_parser.done:
                            self._payload_parser = payload_parser
                    elif method == METH_CONNECT:
                        # connect 请求
                        assert isinstance(msg, RawRequestMessage)
                        payload = StreamReader(
                            self.protocol,
                            timer=self.timer,
                            loop=loop,
                            limit=self._limit,
                        )
                        self._upgraded = True
                        self._payload_parser = HttpPayloadParser(
                            payload,
                            method=msg.method,
                            compression=msg.compression,
                            readall=True,
                            auto_decompress=self._auto_decompress,
                            lax=self.lax,
                        )
                    elif not empty_body and length is None and self.read_until_eof:
                        # 指定了 read_until_eof 参数，且没有传 Content-Length 请求头，且有请求体
                        payload = StreamReader(
                            self.protocol,
                            timer=self.timer,
                            loop=loop,
                            limit=self._limit,
                        )
                        payload_parser = HttpPayloadParser(
                            payload,
                            length=length,
                            chunked=msg.chunked,
                            method=method,
                            compression=msg.compression,
                            code=self.code,
                            readall=True,
                            response_with_body=self.response_with_body,
                            auto_decompress=self._auto_decompress,
                            lax=self.lax,
                        )
                        if not payload_parser.done:
                            self._payload_parser = payload_parser
                    else:
                        payload = EMPTY_PAYLOAD

                    messages.append((msg, payload))
            else:
                self._tail = data[start_pos:]
                data = EMPTY
                break

        ...
    ...
    return messages, self._upgraded, data
```
请求体解析类`HttpPayloadParser`使用了读流类`StreamReader`，`HttpPayloadParser`类会将解析的请求体数据放到`StreamReader`中，
进而包含请求体数据的`StreamReader`对象会放到`Request`对象中，最后`Request`对象可以按照同步编程的思想获取请求体数据。

我们先看下`StreamReader`类的实现原理，初始化部分源码如下：
```python
class StreamReader(AsyncStreamReaderMixin):
    # 记录总的已经接收的字节数
    total_bytes = 0

    def __init__(
        self,
        protocol: BaseProtocol,
        limit: int,
        *,
        timer: Optional[BaseTimerContext] = None,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        # 用于接收数据的底层协议对象(可以参考asyncio基于transports&protocols编程介绍)
        self._protocol = protocol
        # 存放请求数据缓存_buffer的低水位线，用于控制底层protocol协议读写操作
        self._low_water = limit
        # 存放请求数据缓存_buffer的高水位线，用于控制底层protocol协议读写操作
        self._high_water = limit * 2
        if loop is None:
            loop = asyncio.get_event_loop()
        self._loop = loop
        # 记录缓存_buffer中数据的大小，字节数
        self._size = 0
        # 表示从_buffer中已读字节数，也即表示_buffer中未读的字节的起始位置
        self._cursor = 0
        # 记录每一个接收的 chunk 最后一个字节在 _buffer 中的位置(用于分块传输)
        self._http_chunk_splits: Optional[List[int]] = None
        # 缓存数据的 buffer
        self._buffer: Deque[bytes] = collections.deque()
        # 表示_buffer中未读数据的起始位置
        self._buffer_offset = 0
        # 表示是否数据接收结束，收到EOF
        self._eof = False
        # 一个 Future 对象，用于读同步操作，没有接收到数据读操作调用会等待阻塞
        self._waiter: Optional[asyncio.Future[None]] = None
        # 一个 Future 对象，用于读同步操作，等待 EOF 到来
        self._eof_waiter: Optional[asyncio.Future[None]] = None
        self._exception: Optional[BaseException] = None
        self._timer = TimerNoop() if timer is None else timer
        # 给收到 EOF 注册的回调方法
        self._eof_callbacks: List[Callable[[], None]] = []
```
喂数据（将接收的 http 请求数据缓存到 buffer）相关实现如下：
```python
def feed_data(self, data: bytes, size: int = 0) -> None:
    assert not self._eof, "feed_data after feed_eof"

    if not data:
        return

    # 更新 _size, _buffer, total_bytes
    self._size += len(data)
    self._buffer.append(data)
    self.total_bytes += len(data)

    waiter = self._waiter
    if waiter is not None:
        # 通知数据可读
        self._waiter = None
        set_result(waiter, None)

    if self._size > self._high_water and not self._protocol._reading_paused:
        # _buffer 中的字节数超过高水位线，且底层协议没有暂停读，则暂停底层协议读
        self._protocol.pause_reading()

def feed_eof(self) -> None:
    # 收到读接收标志 EOF
    self._eof = True

    waiter = self._waiter
    if waiter is not None:
        # 通知数据可读
        self._waiter = None
        set_result(waiter, None)

    waiter = self._eof_waiter
    if waiter is not None:
        # 通知 eof 收到
        self._eof_waiter = None
        set_result(waiter, None)

    for cb in self._eof_callbacks:
        # 执行EOF相关的回调
        try:
            cb()
        except Exception:
            internal_logger.exception("Exception in eof callback")

    self._eof_callbacks.clear()
```
在`feed_eof`内部，支持 EOF 相关的回调方法，EOF 的回调注册源码如下：
```python
def on_eof(self, callback: Callable[[], None]) -> None:
    if self._eof:
        try:
            callback()
        except Exception:
            internal_logger.exception("Exception in eof callback")
    else:
        self._eof_callbacks.append(callback)
```
如果是分块传输方式，则喂数据还涉及如下两个方法：
```python
def begin_http_chunk_receiving(self) -> None:
    # 必须在 feed_data 调用之前执行，初始化 self._http_chunk_splits 对象
    if self._http_chunk_splits is None:
        if self.total_bytes:
            raise RuntimeError(
                "Called begin_http_chunk_receiving when" "some data was already fed"
            )
        self._http_chunk_splits = []

def end_http_chunk_receiving(self) -> None:
    # self.begin_http_chunk_receiving 必须已经调用
    if self._http_chunk_splits is None:
        raise RuntimeError(
            "Called end_chunk_receiving without calling "
            "begin_chunk_receiving first"
        )

    # self._http_chunk_splits contains logical byte offsets from start of
    # the body transfer. Each offset is the offset of the end of a chunk.
    # "Logical" means bytes, accessible for a user.
    # If no chunks containing logical data were received, current position
    # is difinitely zero.
    pos = self._http_chunk_splits[-1] if self._http_chunk_splits else 0

    if self.total_bytes == pos:
        # We should not add empty chunks here. So we check for that.
        # Note, when chunked + gzip is used, we can receive a chunk
        # of compressed data, but that data may not be enough for gzip FSM
        # to yield any uncompressed data. That's why current position may
        # not change after receiving a chunk.
        return

    # 每收到新的 chunk，更新self._http_chunk_splits，记录累积的 chunk 大小 
    self._http_chunk_splits.append(self.total_bytes)

    # wake up readchunk when end of http chunk received
    waiter = self._waiter
    if waiter is not None:
        self._waiter = None
        set_result(waiter, None)
```
以上四个方法`feed_data`、`feed_eof`、`begin_http_chunk_receiving`和`end_http_chunk_receiving`就是关于喂数据的相关实现，
每个方法都给出了详细注释。

下面看下用于读同步的相关实现，相关源码如下：
```python
async def wait_eof(self) -> None:
    if self._eof:
        return

    assert self._eof_waiter is None
    self._eof_waiter = self._loop.create_future()
    try:
        await self._eof_waiter
    finally:
        self._eof_waiter = None

async def _wait(self, func_name: str) -> None:
    # StreamReader uses a future to link the protocol feed_data() method
    # to a read coroutine. Running two read coroutines at the same time
    # would have an unexpected behaviour. It would not possible to know
    # which coroutine would get the next data.
    if self._waiter is not None:
        raise RuntimeError(
            "%s() called while another coroutine is "
            "already waiting for incoming data" % func_name
        )

    waiter = self._waiter = self._loop.create_future()
    try:
        # 默认没有定时器对象，什么都不做
        with self._timer:
            await waiter
    finally:
        self._waiter = None
```
`self.wait_eof`协程给上层调用者使用，用于相关同步逻辑操作，`self._wait`用于`StreamReader`内部读同步操作，
`self._buffer`没有可读数据，读操作会一直等待。

下面看下`StreamReader`提供的读相关操作，`StreamReader`提供了`readline`、`readuntil`、`read`、`readany`、
`readchunk`和`readexactly`读相关方法。我们主要看下`read`和`readchunk`方法的实现，相关源码如下：
```python
async def readchunk(self) -> Tuple[bytes, bool]:
    """Returns a tuple of (data, end_of_http_chunk).

    When chunked transfer
    encoding is used, end_of_http_chunk is a boolean indicating if the end
    of the data corresponds to the end of a HTTP chunk , otherwise it is
    always False.
    """
    while True:
        if self._exception is not None:
            raise self._exception

        # 分块传输情况
        while self._http_chunk_splits:
            # pos 表示当前要从self._buffer中读字节的末尾位置（不包括 pos 处的字节）
            pos = self._http_chunk_splits.pop(0)
            # self._cursor 表示从 self._buffer 中已读的字节数，也即self._buffer中未读字节的起始位置
            if pos == self._cursor:
                # 当前 chunk 数据已经读完，没有要读的数据，直接返回
                return (b"", True)
            if pos > self._cursor:
                # 当前 chunk 中有要读的数据，
                # pos - self._cursor 表示需要读的字节个数（当前 chunk 剩余未读的所有字节）
                return (self._read_nowait(pos - self._cursor), True)
            internal_logger.warning(
                "Skipping HTTP chunk end due to data "
                "consumption beyond chunk boundary"
            )

        # 非分块传输，且 buffer 中有数据
        if self._buffer:
            return (self._read_nowait_chunk(-1), False)

        # self._buffer 中没有数据且feed_eof 被调用，读操作结束
        if self._eof:
            # Special case for signifying EOF.
            # (b'', True) is not a final return value actually.
            return (b"", False)
        # 等待数据可读
        await self._wait("readchunk")

async def read(self, n: int = -1) -> bytes:
    if self._exception is not None:
        raise self._exception

    if not n:
        return b""

    if n < 0:
        # This used to just loop creating a new waiter hoping to
        # collect everything in self._buffer, but that would
        # deadlock if the subprocess sends more than self.limit
        # bytes.  So just call self.readany() until EOF.
        blocks = []
        while True:
            block = await self.readany()
            if not block:
                break
            blocks.append(block)
        return b"".join(blocks)

    # TODO: should be `if` instead of `while`
    # because waiter maybe triggered on chunk end,
    # without feeding any data
    while not self._buffer and not self._eof:
        await self._wait("read")

    return self._read_nowait(n)

async def readany(self) -> bytes:
    if self._exception is not None:
        raise self._exception

    # TODO: should be `if` instead of `while`
    # because waiter maybe triggered on chunk end,
    # without feeding any data
    while not self._buffer and not self._eof:
        await self._wait("readany")

    # 读 self._buffer 中的所有数据
    return self._read_nowait(-1)

def _read_nowait(self, n: int) -> bytes:
    """Read not more than n bytes, or whole buffer if n == -1"""
    self._timer.assert_timeout()

    chunks = []
    while self._buffer:
        chunk = self._read_nowait_chunk(n)
        chunks.append(chunk)
        if n != -1:
            n -= len(chunk)
            if n == 0:
                break

    return b"".join(chunks) if chunks else b""

def _read_nowait_chunk(self, n: int) -> bytes:
    first_buffer = self._buffer[0]
    # offset 表示_buffer中未读数据的起始位置
    offset = self._buffer_offset
    # self._buffer[0] 包含的字节数，满足要读的 n 个字节
    if n != -1 and len(first_buffer) - offset > n:
        data = first_buffer[offset : offset + n]
        # 更新 _buffer 中未读数据的起始位置
        self._buffer_offset += n
    # _buffer 中未读数据的起始位置不是 0 且 self._buffer[0] 包含的字节数，不满足要读的 n 个字节
    elif offset:
        self._buffer.popleft()
        data = first_buffer[offset:]
        # 更新 _buffer 中未读数据的起始位置
        self._buffer_offset = 0
    # _buffer 中未读数据的起始位置是 0 且 self._buffer[0] 包含的字节数，不满足要读的 n 个字节
    else:
        data = self._buffer.popleft()

    self._size -= len(data)
    # self._cursor 表示从 self._buffer 中已读的字节数，也即self._buffer中未读字节的起始位置
    self._cursor += len(data)

    chunk_splits = self._http_chunk_splits
    # Prevent memory leak: drop useless chunk splits
    while chunk_splits and chunk_splits[0] < self._cursor:
        chunk_splits.pop(0)

    # self._buffer 中的数据在低水位线下，且底层协议读在暂停中，则恢复底层协议读
    if self._size < self._low_water and self._protocol._reading_paused:
        self._protocol.resume_reading()
    # 返回的数据 <= n
    return data
```
`readchunk`方法返回结果是一个元组，每个成员的含义如下：
+ `tuple[0]`: 字节序列，读取的一个 chunk 数据；如果当前 chunk 没有要读的数据或者遇到 EOF 则为 `b''`
+ `tuple[1]`: bool 值，是否是一个 http chunk 的结尾。分块传输总是 `True`，其他情况表示 `False`；

`read`的返回值有三种情况：
+ 如果`n = 0`，返回空字节序列；
+ 如果`n > 0`，返回最多 n 个字节的字节序列；
+ 如果`n = -1`，会一直读，直到遇到 EOF，返回包含所有读到数据的字节序列；

`StreamReader`还支持异步迭代器方式，使用方式如下（源码其实就是调用对应的`readxxx`方法）：
```python
async for line in reader:
    ...
async for chunk in reader.iter_chunked(1024):
    ...
async for slice in reader.iter_any():
    ...
```
了解完`StreamReader`内部实现原理，我们回到请求体解析类`HttpPayloadParser`，其初始化源码实现如下：
```python
class HttpPayloadParser:
    def __init__(
        self,
        payload: StreamReader,
        length: Optional[int] = None,
        chunked: bool = False,
        compression: Optional[str] = None,
        code: Optional[int] = None,
        method: Optional[str] = None,
        readall: bool = False,
        response_with_body: bool = True,
        auto_decompress: bool = True,
        lax: bool = False,
    ) -> None:
        self._length = 0
        # 解析的状态
        self._type = ParseState.PARSE_NONE
        # 分块传输块的状态
        self._chunk = ChunkState.PARSE_CHUNKED_SIZE
        self._chunk_size = 0
        self._chunk_tail = b""
        self._auto_decompress = auto_decompress
        self._lax = lax
        # 表示请求体解析是否完成
        self.done = False

        # payload decompression wrapper
        # 有请求体，且请求体有压缩
        if response_with_body and compression and self._auto_decompress:
            # DeflateBuffer 和 StreamReader 相比增加了解压缩流程，接口完全兼容
            real_payload: Union[StreamReader, DeflateBuffer] = DeflateBuffer(
                payload, compression
            )
        else:
            real_payload = payload

        # payload parser
        if not response_with_body:
            # don't parse payload if it's not expected to be received
            self._type = ParseState.PARSE_NONE
            real_payload.feed_eof()
            self.done = True

        # 分块传输
        elif chunked:
            self._type = ParseState.PARSE_CHUNKED
        # 请求头有 Content-Length
        elif length is not None:
            self._type = ParseState.PARSE_LENGTH
            self._length = length
            if self._length == 0:
                real_payload.feed_eof()
                self.done = True
        # 既不是分块传输，请求头也没有 Content-Length 字段
        else:
            # 204 表示服务器成功响应，但不需要发送请求体
            if readall and code != 204:
                self._type = ParseState.PARSE_UNTIL_EOF
            elif method in ("PUT", "POST"):
                internal_logger.warning(  # pragma: no cover
                    "Content-Length or Transfer-Encoding header is required"
                )
                self._type = ParseState.PARSE_NONE
                real_payload.feed_eof()
                self.done = True

        self.payload = real_payload
```
以上就是请求体初始化的全部实现原理结束，下面我们会介绍如何解析请求体数据。
## 解析请求体
我们继续看`feed_data`中的第四步：如果有请求体，调用`HttpPayloadParser.feed_data`解析请求体数据，相关源码实现如下：
```python
# HttpParser.feed_data
def feed_data(
    self,
    data: bytes,
    SEP: _SEP = b"\r\n",
    EMPTY: bytes = b"",
    CONTENT_LENGTH: istr = hdrs.CONTENT_LENGTH,
    METH_CONNECT: str = hdrs.METH_CONNECT,
    SEC_WEBSOCKET_KEY1: istr = hdrs.SEC_WEBSOCKET_KEY1,
) -> Tuple[List[Tuple[_MsgT, StreamReader]], bool, bytes]:
    ...
    while start_pos < data_len:
        # read HTTP message (request/response line + headers), \r\n\r\n
        # and split by lines
        if self._payload_parser is None and not self._upgraded:
            ...

        # no parser, just store
        elif self._payload_parser is None and self._upgraded:
            assert not self._lines
            break

        # feed payload
        elif data and start_pos < data_len:
            assert not self._lines
            assert self._payload_parser is not None
            try:
                # eof: 请求体解析是否完成
                # data: 多余的请求体数据，一个字节序列
                eof, data = self._payload_parser.feed_data(data[start_pos:], SEP)
            except BaseException as underlying_exc:
                reraised_exc = underlying_exc
                if self.payload_exception is not None:
                    reraised_exc = self.payload_exception(str(underlying_exc))

                set_exception(
                    self._payload_parser.payload,
                    reraised_exc,
                    underlying_exc,
                )

                eof = True
                data = b""

            if eof:
                # 当前 http 请求解析完成，恢复初始状态，解析下一个http 请求
                # 每个 http 请求都会创建一个StreamReader 和 HttpPayloadParser 实例
                start_pos = 0
                data_len = len(data)
                self._payload_parser = None
                continue
        else:
            break

    if data and start_pos < data_len:
        data = data[start_pos:]
    else:
        data = EMPTY

    return messages, self._upgraded, data
```
请求体的解析主要通过`self._payload_parser.feed_data`方法实现，`self._payload_parser`是`HttpPayloadParser`实例，
相关初始化已经在第三步末尾介绍，下面我们看下`HttpPayloadParser.feed_data`的源码实现：
```python
# HttpPayloadParser.feed_eof
def feed_eof(self) -> None:
    if self._type == ParseState.PARSE_UNTIL_EOF:
        self.payload.feed_eof()
    elif self._type == ParseState.PARSE_LENGTH:
        raise ContentLengthError(
            "Not enough data for satisfy content length header."
        )
    elif self._type == ParseState.PARSE_CHUNKED:
        raise TransferEncodingError(
            "Not enough data for satisfy transfer length header."
        )

# HttpPayloadParser.feed_data
def feed_data(
    self, chunk: bytes, SEP: _SEP = b"\r\n", CHUNK_EXT: bytes = b";"
) -> Tuple[bool, bytes]:
    # Read specified amount of bytes
    # 请求头中有 Content-Length 字段
    if self._type == ParseState.PARSE_LENGTH:
        # Content-Length 取值
        required = self._length
        chunk_len = len(chunk)
        # 请求体未接收完
        if required >= chunk_len:
            self._length = required - chunk_len
            self.payload.feed_data(chunk, chunk_len)
            if self._length == 0:
                self.payload.feed_eof()
                return True, b""
        # 请求体数据接收完
        else:
            self._length = 0
            self.payload.feed_data(chunk[:required], required)
            self.payload.feed_eof()
            return True, chunk[required:]

    # Chunked transfer encoding parser
    # 分块传输
    elif self._type == ParseState.PARSE_CHUNKED:
        # 上次处理的 chunk 有未处理的数据
        if self._chunk_tail:
            chunk = self._chunk_tail + chunk
            self._chunk_tail = b""

        while chunk:
            # read next chunk size
            # ChunkState.PARSE_CHUNKED_SIZE 是初始化指定的值
            if self._chunk == ChunkState.PARSE_CHUNKED_SIZE:
                # 找 \r\n 换行符
                pos = chunk.find(SEP)
                if pos >= 0:
                    # 找 ;
                    i = chunk.find(CHUNK_EXT, 0, pos)
                    if i >= 0:
                        size_b = chunk[:i]  # strip chunk-extensions
                    else:
                        size_b = chunk[:pos]

                    if self._lax:  # Allow whitespace in lax mode.
                        size_b = size_b.strip()

                    if not re.fullmatch(HEXDIGITS, size_b):
                        exc = TransferEncodingError(
                            chunk[:pos].decode("ascii", "surrogateescape")
                        )
                        set_exception(self.payload, exc)
                        raise exc
                    # 找到一个块的大小
                    size = int(bytes(size_b), 16)

                    chunk = chunk[pos + len(SEP) :]
                    # 分块传输结束
                    if size == 0:  # eof marker
                        self._chunk = ChunkState.PARSE_MAYBE_TRAILERS
                        if self._lax and chunk.startswith(b"\r"):
                            chunk = chunk[1:]
                    # 正常的一个分块
                    else:
                        self._chunk = ChunkState.PARSE_CHUNKED_CHUNK
                        self._chunk_size = size
                        # 初始化分块接收数据结构
                        self.payload.begin_http_chunk_receiving()
                # 当前 chunk 没有 \r\n
                else:
                    self._chunk_tail = chunk
                    return False, b""

            # read chunk and feed buffer
            # 解析一个分块
            if self._chunk == ChunkState.PARSE_CHUNKED_CHUNK:
                required = self._chunk_size
                chunk_len = len(chunk)
                # 部分分块数据
                if required > chunk_len:
                    self._chunk_size = required - chunk_len
                    self.payload.feed_data(chunk, chunk_len)
                    return False, b""
                # 完整的分块数据
                else:
                    self._chunk_size = 0
                    self.payload.feed_data(chunk[:required], required)
                    chunk = chunk[required:]
                    if self._lax and chunk.startswith(b"\r"):
                        chunk = chunk[1:]
                    self._chunk = ChunkState.PARSE_CHUNKED_CHUNK_EOF
                    # 通知 payload 一个分块接收完成
                    self.payload.end_http_chunk_receiving()

            # toss the CRLF at the end of the chunk
            if self._chunk == ChunkState.PARSE_CHUNKED_CHUNK_EOF:
                # 去掉 chunk 剩余未解析数据开头的 \r\n
                if chunk[: len(SEP)] == SEP:
                    chunk = chunk[len(SEP) :]
                    # 恢复到初始状态，用于解析下一个 chunk 数据
                    self._chunk = ChunkState.PARSE_CHUNKED_SIZE
                # 剩余未处理的 chunk 数据是 \r 或者 b''，等待下次调用
                else:
                    self._chunk_tail = chunk
                    return False, b""

            # if stream does not contain trailer, after 0\r\n
            # we should get another \r\n otherwise
            # trailers needs to be skipped until \r\n\r\n
            # 收到了分块大小是 0
            if self._chunk == ChunkState.PARSE_MAYBE_TRAILERS:
                head = chunk[: len(SEP)]
                # 数据大小 0\r\n 下一行是 \r\n
                if head == SEP:
                    # end of stream
                    self.payload.feed_eof()
                    return True, chunk[len(SEP) :]
                # Both CR and LF, or only LF may not be received yet. It is
                # expected that CRLF or LF will be shown at the very first
                # byte next time, otherwise trailers should come. The last
                # CRLF which marks the end of response might not be
                # contained in the same TCP segment which delivered the
                # size indicator.
                # 还未接收到 \r\n
                if not head:
                    return False, b""
                # 只接收到 \r
                if head == SEP[:1]:
                    self._chunk_tail = head
                    return False, b""
                # 0\\r\n 下一行是非 \r\n 数据
                self._chunk = ChunkState.PARSE_TRAILERS

            # read and discard trailer up to the CRLF terminator
            # 一直找到 \r\n\r\n 也就是空行
            if self._chunk == ChunkState.PARSE_TRAILERS:
                pos = chunk.find(SEP)
                if pos >= 0:
                    chunk = chunk[pos + len(SEP) :]
                    self._chunk = ChunkState.PARSE_MAYBE_TRAILERS
                else:
                    self._chunk_tail = chunk
                    return False, b""

    # Read all bytes until eof
    # 参数指定读所有数据，直到 eof
    elif self._type == ParseState.PARSE_UNTIL_EOF:
        self.payload.feed_data(chunk, len(chunk))

    return False, b""
```
`HttpPayloadParser.feed_data`内部解析处理三种场景：
+ 请求头中有 Content-Length 字段；
+ 分块传输
+ 参数`readall=True`指定，且响应码不是 204

`HttpPayloadParser.feed_data`返回有是一个元组，说明如下：
+ `tuple[0]`: 一个 bool 值，`True` 表示请求体解析完，`False`表示未完成；
+ `tuple[1]`: 一个字节序列，表示多余的请求体数据；

最终将请求体的数据喂到`StreamReader`的缓存`_buffer`中，以供后续的`Request`实例进行相关的读操作。
总结下请求解析`self._request_parser.feed_data(data)`返回三个数据，对应说明如下：
+ `messages`: 一个 list 对象，每一个元素是一个元组，`tuple[0]`是一个`RawRequestMessage`对象（参考请求解析第二步），
`tuple[1]`是一个`StreamReader`对象，可以调用其提供的`readxxx`方法获取请求体数据；
+ `upgraded`: 一个 bool 值，表示是否升级协议；
+ `tail`: 一个字节序列，表示未解析的数据，用于下次继续解析；

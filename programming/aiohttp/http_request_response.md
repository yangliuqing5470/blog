## 请求解析
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
- `version_o`: 请求行中协议版本号，例如 `HttpVersion(1, 1)`
- `headers`: 一个只读的字典，包含所有的请求头及值，其中 key 是大小写不敏感，也就是同一个 key 不能同时存在大写和小写；
- `raw_headers`: 一个元组，每一项都是`(bname, bvalue)`形式表示一个请求头名字和取值，`bname`和`bvalue`是字节序列；
- `close`: 一个 `bool` 值，控制长连接。http/1.1 默认是 `False`，http/1.0 默认是 `True`；如果请求头有指定，以指定为准；
- `compression`: `str` 类型，压缩类型，如果请求头中不指定或者指定值不在 `("gzip", "deflate", "br")`，取值 `None`，否则按指定值；
- `upgrade`: 一个 `bool` 类型，表示是否升级协议；
- `chunked`: 一个 `bool` 类型，表示是否是分块传输；
- `url`: 从 path 构建的一个 `yarl.URL` 对象；

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

                    self._upgraded = msg.upgrade and _is_supported_upgrade(
                        msg.headers
                    )

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

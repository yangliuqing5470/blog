# 引言
## HTTPS vs HTTP
`HTTPS`协议是身披`SSL&TLS`协议外壳的`HTTP`，`HTTPS`和`HTTP`协议对比如下：
```bash
  HTTP协议         HTTPS协议
+----------+     +----------+
|   HTTP   |     |   HTTP   |
|          |     |----------|
|          |     |  SSL&TLS |
+----------+     +----------+
|TCP(传输层)|     |TCP(传输层)|
+----------+     +----------+
|IP(网络层) |     |IP(网络层) |
+----------+     +----------+
|    ...   |     |    ...   |
+----------+     +----------+
```
## 对称加密
+ 加密和解密同用一个密钥的方式。
+ 加密和解密过程速度很快，适合于大量数据的加密。
+ 主要的缺点是密钥的分发和管理问题，如果密钥泄漏，会导致信息安全受到威胁。

## 非对称加密
+ 发送方和接收方使用一对密钥来进行加密和解密，这对密钥包括公钥和私钥。
+ 公钥可以自由发布，用于加密数据，而私钥则只有接收方拥有，用于解密数据。
+ 非对称加密解决了对称加密中密钥分发和管理的问题，但加密和解密速度通常较慢，适合于加密小量数据或者用于密钥交换。

## 证书
证书用来确认通信方身份的真实性。证书的签名流程如下：
+ **打包**：`CA` 会把持有者的公钥，用途，颁发者，有效时间等信息进行打包，然后对这些信息进行`Hash`计算，得到一个`Hash`值。
+ **签名**：然后`CA`用自己的私钥将该`Hash`值加密，生成`Certificate Signature`。
+ **添加**：将`Certificate Signature`添加到证书文件中，形成数字证书。

客户端对证书身份的验证流程如下：
+ **打包**：客户端使用相同的`Hash`算法，对证书信息进行打包，`Hash`计算，得到一个`Hash`值`H1`。
+ **公钥解密**：使用`CA`机构的公钥对数字证书`Certificate Signature`内容进行解密，得到`Hash`值`H2`。
+ **比较**：如何`H1`和`H2`的值相同，则为可信证书。

实际中使用的都是**证书链**，证书链包含根证书、中间证书和服务器证书，一般终端设备或浏览器内置根证书。证书签发流程如下：
+ 根证书`CA`使用自己的私钥对中间证书进行签名，授权中间机构证书。
+ 中间机构使用自己的私钥对服务器证书进行签名，授权服务器证书。

证书链校验流程如下：
+ 客户端通过服务器证书中签发机构信息获取中间证书公钥，用中间证书公钥对服务器证书进行校验。
+ 客户端通过中间证书中签发机构信息在本地查找获取根证书公钥，用根证书公钥对中间证书进行校验。

证书链样例及中间证书获取如下图所示：
![中间证书获取](./images/ca.png)

# HTTPS 通信流程
`HTTPS`通信分为如下三个阶段：
+ **TCP三次握手**
+ **TLS握手**
+ **HTTP数据传输（SSL加密）**

`HTTPS`使用对称加密和非对称加密两种方式，非对称加密用于握手阶段，对称加密用于数据传输阶段。

## TLS握手
`TLS`握手阶段流程如下：
+ **客户端**发送`Client Hello`报文开始`SSL`通信。`Client Hello`报文包含客户端支持的`SSL`版本，加密套件（`Cipher Suites`）列表，
客户端生成的一个 32 字节的随机数`R1`等。
+ **服务端**响应`Server Hello`响应报文。`Server Hello`响应报文包含`SSL`版本，加密套件（`Cipher Suites`）以及服务端生成的一个 32
位的随机数`R2`。其中加密套件是从接收的客户端加密套件中筛选出来的。
+ **服务端**继续发送`Certificate`、`Server Key Exchange`和`Server Hello Done`三个报文。
  + `Certificate`表示服务端证书。
  + `Server Key Exchange`表示一个对称密钥，用于`DH`算法，`RSA`算法不需要，没这个报文。
  + `Server Hello Done`表示服务端完成握手协议，通知客户端继续下一步。
+ **客户端**开始证书校验。
+ **客户端**发送`Client Key Exchange`报文。证书校验通过后，客户端获的服务端的公钥，
然后客户端生成一个随机数`R3`，并用获取的公钥加密此随机数生成`PreMaster Key`发送给服务端，
后面服务端接收到`PreMaster Key`后，用自己的私钥解密获取随机数`R3`，这样客户端和服务端都有随机数`R1`、
`R2`和`R3`，然后两端用相同的算法生成一个**对称密钥**，握手结束后，会通过该**对称密钥**传输应用数据。
+ **客户端**继续发送`Change Cipher Spec`报文，表示客户端接下来使用前面生成的**对称密钥**来传输数据。
+ **客户端**继续发送`Finished`报文，该报文包含连接至今全部报文的整体校验值，
握手协商是否成功要以服务端是否可以正确解密该报文为准。
+ **服务端**也发送`Change Cipher Spec`报文，表示服务端接下来使用前面生成的**对称密钥**来传输数据。
+ **服务端**也发送`Finished`报文。

# HTTPS 使用样例
## 自签名证书
### 创建根 CA 证书
+ 生成私钥
  ```bash
  openssl ecparam -out contoso.key -name prime256v1 -genkey
  ```
  这里使用`ecparam`加密算法，参数指定`prime256v1`，生成的密钥是`contoso.key`。
+ 生成自签名证书请求（CSR）
  ```bash
  openssl req -new -sha256 -key contoso.key -out contoso.csr
  ```
  出现如下提示，需要填一些证书相关信息：
  ```bash
  You are about to be asked to enter information that will be incorporated
  into your certificate request.
  What you are about to enter is what is called a Distinguished Name or a DN.
  There are quite a few fields but you can leave some blank
  For some fields there will be a default value,
  If you enter '.', the field will be left blank.
  -----
  Country Name (2 letter code) [AU]:CN
  State or Province Name (full name) [Some-State]:BeiJing
  Locality Name (eg, city) []:BeiJing
  Organization Name (eg, company) [Internet Widgits Pty Ltd]:Yang
  Organizational Unit Name (eg, section) []:basic
  Common Name (e.g. server FQDN or YOUR name) []:10.211.55.8
  Email Address []:my@gmail.com
  
  Please enter the following 'extra' attributes
  to be sent with your certificate request
  A challenge password []:123456
  An optional company name []:test
  ```
  + `Country Name`：缩写为`C`，证书持有者所在国家，要求填写国家代码，用2个字母表示。
  + `State or Province Name`：缩写为`ST`，证书持有者所在州或省份，填写全称，可省略不填。
  + `Locality Name`：缩写为`L`，证书持有者所在城市，可省略不填。
  + `Ori`
  + `Organization Name`：缩写为`O`，证书持有者所属组织或公司，可省略不填，建议填。
  + `Organizational Unit Name`：缩写为`OU`，证书持有者所属部门，可省略不填。
  + `Common Name`：缩写为`CN`，证书持有者的通用名，必填，如果是服务器证书一般填域名地址或者 ip 地址。
  + `Email Address`：证书持有者邮箱，可省略不填。

  **`CN`的作用**：客户端使用`HTTPS`连接到服务器时，客户端会检查以确保获取的服务器证书与实际客户端请求主机名称匹配，
  也就是客户端会检查服务器证书上的域名是否和服务器的实际域名相匹配。
+ 生成证书
  ```bash
  openssl x509 -req -sha256 -days 365 -in contoso.csr -signkey contoso.key -out contoso.crt
  ```

经过上述步骤，最终会得到如下三个文件：
+ contoso.key
+ contoso.csr
+ contoso.crt

### 创建服务器证书
+ 生成服务器证书私钥
  ```bash
  openssl ecparam -out fabrikam.key -name prime256v1 -genkey
  ```
  这里使用`ecparam`加密算法，参数指定`prime256v1`，生成的密钥是`fabrikam.key`。
+ 生成自签名证书请求（CSR）
  ```bash
  openssl req -new -sha256 -key fabrikam.key -out fabrikam.csr
  ```
+ 生成服务器证书
  ```bash
  openssl x509 -req -in fabrikam.csr -CA  contoso.crt -CAkey contoso.key -CAcreateserial -out fabrikam.crt -days 365 -sha256
  ```
经过上述步骤，最终会多如下三个文件：
+ fabrikam.key
+ fabrikam.csr
+ fabrikam.crt

可以使用如下的命令查看证书：
```bash
openssl x509 -in fabrikam.crt -text -noout
```
输出结果如下：
```bash
Certificate:
    Data:
        Version: 1 (0x0)
        Serial Number:
            2f:b2:8f:28:ae:ef:95:b3:e6:c9:23:5c:6e:4e:91:a8:33:f8:93:6f
        Signature Algorithm: ecdsa-with-SHA256
        Issuer: C = CN, ST = BeiJing, L = BeiJing, O = Yang, OU = basic, CN = 10.211.55.8, emailAddress = my@gmail.com
        Validity
            Not Before: May 17 03:23:15 2024 GMT
            Not After : May 17 03:23:15 2025 GMT
        Subject: C = CN, ST = BeiJing, L = Beijing, O = Yang, OU = basic, CN = 10.211.55.8, emailAddress = user@gamil.com
        Subject Public Key Info:
            Public Key Algorithm: id-ecPublicKey
                Public-Key: (256 bit)
                pub:
                    04:95:27:1c:c6:4b:ac:0b:7a:5a:2a:cf:29:24:ae:
                    86:00:67:fb:88:ed:1e:7b:05:31:de:79:46:79:56:
                    0c:c6:32:9e:0c:35:ca:8b:64:b9:f3:70:ba:70:e3:
                    3b:af:de:35:b4:a1:11:5b:a0:6c:60:9d:44:e7:de:
                    fa:50:6f:d2:c7
                ASN1 OID: prime256v1
                NIST CURVE: P-256
    Signature Algorithm: ecdsa-with-SHA256
    Signature Value:
        30:45:02:21:00:bd:9d:95:a4:7e:b4:22:2e:90:b3:3a:f4:8f:
        50:3c:89:99:1e:07:a4:9c:e5:66:f3:fe:07:d3:01:a8:6e:ac:
        cd:02:20:21:68:61:ea:74:67:ab:4c:92:dd:0d:d1:08:ab:a4:
        2a:40:1d:5d:22:6e:8f:56:b8:1b:b6:61:2a:d0:84:ff:ee
```
其中`Issuer`字段表示颁发者信息，`Subject`字段表示当前证书信息。

## HTTPS 服务端
基于`aiohttp`实现的`https`服务样例代码如下：
```python
import ssl
from aiohttp import web

async def handle(request):
    return web.Response(text="Hello, HTTPS world!")

def create_ssl_context():
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain('./fabrikam.crt', './fabrikam.key')
    return ssl_context

app = web.Application()
app.router.add_get('/', handle)

if __name__ == "__main__":
    ssl_context = create_ssl_context()
    web.run_app(app, ssl_context=ssl_context, port=8443)
```
其中`fabrikam.crt`是服务器上的证书文件，`fabrikam.key`是私钥。

## HTTPS 客户端
发送`https`请求的客户端样例代码如下：
```python
import requests

def main():
    url = "https://10.211.55.8:8443"
    cert_path = "./contoso.crt"
    response = requests.get(url, verify=cert_path)
    print(response.content)

if __name__ == "__main__":
    main()
```
其中`cert_path`表示`CA bundle`文件路径，因为没有中间证书，这里是根证书。根据证书链验证规则，这里需要指定根证书和中间证书（如果存在）。

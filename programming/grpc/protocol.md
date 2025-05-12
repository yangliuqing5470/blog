# 概述
`Protocol Buffers`是一种**序列化**数据结构的协议。其包含一个**接口描述语言**（`.proto`文件定义）描述一些数据结构，
并提供程序工具根据这些描述产生代码，这些代码将用来生成或解析代表这些数据结构的字节流。

`Protocol Buffers`的工作流如下：

![protobuf工作流](./images/protobuf工作流.png)

# 语法
## 基础语法
```proto
// 简单样例
syntax = "proto3";

message SearchRequest {
  string query = 1;
  int32 page_number = 2;
  int32 results_per_page = 3;
}
```
文件`.proto`的**第一行必须指定`syntax`或者`edition`**。如果不指定，默认使用`proto2`。定义的消息`message`可以包含多个字段（`name/value`对），
每一个字段都需要指定**类型**，如`string`、`int32`等。且每一个字段都需要分配一个**编号**，**编号**具有一些限制：
+ 每一个`message`内的所有字段的编号都需要是独一无二的，不同`message`内字段编号可以重复。
+ 编号`19000 - 19999`是保留编号，不能使用。
+ 不能使用关键字`reserved`指定的编号。

如果**一个`message`已经在使用了，则不能更改其字段的编号。而且也不要重用字段编号**。因为在底层的序列化时候，使用编号作为`key`而不是字段名作为`key`。
尽量**使用小的编号**，因为小的编号在序列化编码时占用字节少。

##  Message 字段类型
`message`的字段分三类：`singular`、`repeated`和`map`。含义如下：
+ `singular`：是`proto3`的默认行为，表示在每个消息的实例中，该字段的值最多只有一个。例如：
  ```proto
  // 在每个 Message 实例中，字段 foo 的值只能有一个
  message Message {
    string foo = 1;
  }
  ```
  可以在`singular`类型字段前加`optional`关键字（**推荐写法**）。使用`optional`在生成的语言代码中，例如`python`会有`HasFiled`方法，
  用于**判断该字段是否被设置过**。
  ```proto
  message Test1 {
    string name = 1;
  }
  
  message Test2 {
    optional string name = 1;
  }
  ```
  使用`protoc`编译上述`.proto`文件，生成`python`语言代码：
  ```bash
  python3 -m grpc_tools.protoc --proto_path=. --python_out=. --pyi_out=. --grpc_python_out=. tutorial/v2/example.proto
  ```
  执行结果如下：
  ```bash
  >>> import example_pb2 as pb2
  >>> a = pb2.Test1()
  >>> b = pb2.Test2()
  >>> a.HasField("name")  # Test1 消息没有 optional 关键字，字段没有 HasField 方法
  Traceback (most recent call last):
    File "<stdin>", line 1, in <module>
  ValueError: Field tutorial.v2.Test1.name does not have presence.
  >>> b.HasField("name")  # Test2 消息有 optional 关键字，字段有 HasField 方法
  False
  >>> a.name
  ''
  >>> b.name
  ''
  >>> b.name = ""  # Test2 消息的 name 字段设置默认值
  >>> b.HasField("name")  # 检查字段 name 被设置过
  True
  ```
  对于**有`optional`关键字的字段，如果字段被设置（不管设置默认值还是其他），此字段都会被序列化。如果字段没有被设置，
  此字段不会被序列化**。

  对于**没有`optional`关键字的字段，如果字段不是`message`类型，则只有被设置非默认值才会序列化，否则不回被序列化**。
  如果字段是`message`类型，行为和`optional`关键字一样。`message`类型字段样例如下：
  ```proto
  message Message1 {}

  message Message2 {
    Message1 foo = 1;
  }
  
  message Message3 {
    optional Message1 bar = 1;
  }
  ```
  上面的`Message2`和`Message3`中的字段`foo`和`bar`都是`message`类型，行为完全一样。
+ `repeated`：表示字段值可以有多个，将字段看成**列表**。
  ```proto
  message Person {
    string name = 1;               // singular
    repeated string hobbies = 2;   // repeated
  }
  ```
+ `map`：将字段看成**字典**，其实是`repeated`的特殊情况。
  ```proto
  message Test6 {
    map<string, int32> g = 7;
  }
  // 等价下面的
  message Test6 {
    message g_Entry {
      string key = 1;
      int32 value = 2;
    }
    repeated g_Entry g = 7;
  }
  ```
## 字段删除
删除一个字段，**不应该使用被删除字段编号，编码应该保留**。
```proto
message Foo {
  reserved 2, 15, 9 to 11;
}
```
当然，也可以保留被删除字段的名字，避免重新使用，保留名字不影响`.proto`的解析过程。
```proto
message Foo {
  reserved 2, 15, 9 to 11;
  reserved "foo", "bar";
}
```
## 数据类型
### Scalar Value 类型
在`.proto`文件中，字段的数据类型可以是常用的标量类型。
|`proto`类型|说明|`Python`语言类型|默认值|
|-----------|----|----------------|------|
|`double`||`float`|`0`|
|`float`||`float`|`0`|
|`int32`|使用变长编码。编码负数效率低，因为占用较多字节|`int`|`0`|
|`int64`|使用变长编码。编码负数效率低，因为占用较多字节|`int/long`|`0`|
|`uint32`|使用变长编码|`int/long`|`0`|
|`uint64`|使用变长编码|`int/long`|`0`|
|`sint32`|使用变长编码。有符号整数值。编码负数效率高|`int`|`0`|
|`sint64`|使用变长编码。有符号整数值。编码负数效率高|`int/long`|`0`|
|`fixed32`|固定`4`字节。如果值超过`2^28`，编码效率比`uint32`高|`int/long`|`0`|
|`fixed64`|固定`8`字节。如果值超过`2^56`，编码效率比`uint64`高|`int/long`|`0`|
|`sfixed32`|固定`4`字节|`int`|`0`|
|`sfixed64`|固定`8`字节|`int/long`|`0`|
|`bool`||`bool`|`false`|
|`string`|长度不能超过`2^32`|`str`|`''`|
|`bytes`|长度不能超过`2^32`|`bytes`|`b''`|

### 枚举类型
下面是在`.proto`文件中使用**枚举类型**的样例。枚举使用`enum`关键字。
```proto
enum Corpus {
  CORPUS_UNSPECIFIED = 0;
  CORPUS_UNIVERSAL = 1;
  CORPUS_WEB = 2;
  CORPUS_IMAGES = 3;
  CORPUS_LOCAL = 4;
  CORPUS_NEWS = 5;
  CORPUS_PRODUCTS = 6;
  CORPUS_VIDEO = 7;
}

message SearchRequest {
  string query = 1;
  int32 page_number = 2;
  int32 results_per_page = 3;
  Corpus corpus = 4;  // 枚举类型
}
```
 枚举类型字段`SearchRequest.corpus`的默认值是枚举变量`Corpus`的第一个值`CORPUS_UNSPECIFIED`。
在`proto3`中**枚举定义的第一个值一定是`0`**，第一个值命名规则是`ENUM_TYPE_NAME_UNSPECIFIED`。
需要注意的是，枚举定义后的数字是取值，而不是编号。例如`CORPUS_WEB`表示数字`2`。

枚举也可以使用**别名**，也就是多个枚举成员可以使用相同的整数值，样例如下。
```proto
enum EnumAllowingAlias {
  option allow_alias = true;  // 必须设置
  EAA_UNSPECIFIED = 0;
  EAA_STARTED = 1;
  EAA_RUNNING = 1;  // 别名
  EAA_FINISHED = 2;
}
```
启动枚举别名必须设置`allow_alias = true`参数。主要用于兼容老接口，不同语义场景。

为了**避免重用**老的枚举值，可以使用`reserved`关键字。
```proto
enum Foo {
  reserved 2, 15, 9 to 11, 40 to max;
  reserved "FOO", "BAR";
}
```
### Message 类型
在一个消息中的字段也可以是自定义的其他消息类型。
```proto
message SearchResponse {
  repeated Result results = 1;  // 自定义的 Result 消息类型
}

message Result {
  string url = 1;
  string title = 2;
  repeated string snippets = 3;
}
```
如果定义的消息在其它`.proto`文件中，可以使用`import`关键字。
```proto
import "myproject/other_protos.proto";
```
需要**注意`import`关键字表示仅仅当前`.proto`文件能使用被导入的消息类型**。**而`import public`关键字表示不仅当前`.proto`文件能使用，
还会传递给导入它的文件**。样例说明如下：
```proto
// a.proto 文件内容如下
syntax = "proto3";

message A {}

// b.proto 文件内容如下
syntax = "proto3";

import "a.proto"  // 或 import public "a.proto"

message B {}

// c.proto 文件内容如下
syntax = "proto3";

import "b.proto"

message C {
  B b = 1;
  A a = 2;  // 如果 b.proto 文件是 import 则会报错。如果是 import public 不会报错
}
```
### 嵌套类型
`message`类型可以嵌套，也就是一个`message`里面可以嵌套另一个`message`。
```proto
message SearchResponse {
  message Result {      // 嵌套 message
    string url = 1;
    string title = 2;
    repeated string snippets = 3;
  }
  repeated Result results = 1;  // 使用嵌套的 message
}
```
可以在其他消息中引用被嵌套的消息，例如：
```proto
message SomeOtherMessage {
  SearchResponse.Result result = 1;  // 引用上面被嵌套的 Result 消息
}
```
### Any 类型
`google.protobuf.Any`类型是一种**通用容器类型，可以用来封装任意消息类型**，即：
可以在一个字段中传递任何`protobuf`消息，而无需提前在`.proto`文件中明确指定其类型。
```proto
syntax = "proto3";

import "google/protobuf/any.proto";  // 必须有

message Dog {
  string name = 1;
}

message Zoo {
  google.protobuf.Any animal = 1;    // 一个 Any 类型
}
```
在`Python`中的使用样例如下：
```python
from google.protobuf.any_pb2 import Any
from zoo_pb2 import Zoo, Dog

# 创建 Dog 实例
dog = Dog(name="Rex")

# 用 Any 封装
any_msg = Any()
any_msg.Pack(dog)  # 自动设置 type_url 和 value

# 放入 Zoo 消息
zoo = Zoo(animal=any_msg)

# 反序列化时解析回原始类型
unpacked_dog = Dog()
if zoo.animal.Unpack(unpacked_dog):
    print("Unpacked dog name:", unpacked_dog.name)

```
`Any`类型的使用场景一般如下：
+ **插件系统**：某个字段可以携带任意拓展信息；
+ **多态消息传递**：某个字段可以是多种类型的一种；

### Oneof 类型
`Oneof`类似`c`语言中的`union`结构。用于在一个消息的**多个字段中同时只能设置一个字段值**。
在`Python`中可以使用`WhichOneof`方法检查哪一个字段被设置。`Oneof`类型具有以下特点：
+ **互斥性**：`oneof`中多个字段只能设置一个，设置一个会自动清除其他的；
+ **节省空间**：多个字段复用一个存储位置，节省序列化数据大小；
+ **自动清除**：设置一个字段会清除其他字段；

```proto
syntax = "proto3";

message Shape {
  oneof shape_type {    // Oneof 类型
    Circle circle = 1;
    Rectangle rectangle = 2;
    Triangle triangle = 3;
  }
}

message Circle {
  double radius = 1;
}

message Rectangle {
  double width = 1;
  double height = 2;
}

message Triangle {
  double base = 1;
  double height = 2;
}
```
在`Python`中的使用样例如下：
```python
shape = Shape()
shape.circle.radius = 5.0

print(shape)  # 会打印 circle 部分

# 设置 rectangle 会自动清除 circle
shape.rectangle.width = 3.0
shape.rectangle.height = 4.0

print(shape.WhichOneof("shape_type"))  # 输出: "rectangle"
```
需要注意，`Oneof`中的字段不能是`map`和`repeated`类型，其他类型都可以。且`Oneof`也不能被`repeated`。
### Map 类型
`Map`类型在`.proto`中的语法定义如下，其表示**键值对集合**。
```proto
map<key_type, value_type> map_field = N;
```
其中`key_type`可以是整数或字符串等`scalar`类型。而`value_type`可以是任意类型，但不能是`map`。
`N`表示字段编号，必须唯一。`Map`的底层实现如下：
```proto
message UserPrefs {
  repeated MapFieldEntry feature_usage_count = 1;
  message MapFieldEntry {
    string key = 1;
    int32 value = 2;
  }
}
```
下面给出在`.proto`中使用`map`的样例说明。
```proto
syntax = "proto3";

message UserPrefs {
  map<string, int32> feature_usage_count = 1;  // map 数据类型
  map<string, Preference> preferences = 2;     // map 数据类型
}

message Preference {
  bool enabled = 1;
  string note = 2;
}
```
在`Python`中使用如下：
```python
prefs = UserPrefs()

# 设置 map<string, int32>
prefs.feature_usage_count["dark_mode"] = 5
prefs.feature_usage_count["notifications"] = 2

# 设置 map<string, Preference>
prefs.preferences["dark_mode"].enabled = True
prefs.preferences["dark_mode"].note = "User prefers dark mode"
```
## Package 声明
在`.proto`文件中可以添加`package`关键字声明的包名以防止不同消息间命名冲突。
```proto
package foo.bar;    // package 声明包名
message Open { ... }
```
使用方式如下：
```proto
message Foo {
  ...
  foo.bar.Open open = 1;
  ...
}
```
## 定义 Service
在`.proto`文件中使用`rpc`关键字定义一个`RPC`服务接口。
```proto
service SearchService {
  rpc Search(SearchRequest) returns (SearchResponse);
}
```
`proto`编译器会自动生成`service`代码和`stub`代码（客户端代码）。
## Option 声明
在`.proto`文件中，可以使用`options`来控制序列化行为、代码生成特性，或者为工具链（如`gRPC`或编译器插件）传递额外的信息。
有些`options`是文件级别，有些是字段级别或者消息级别。下面给出常用`options`的样例说明。
+ `java_package`【文件级别】：针对`java/kotlin`代码，用于指定生成类的包名。
  ```proto
  option java_package = "com.example.foo";
  ```
+ `java_outer_classname`【文件级别】：针对`java`代码，用于指定生成的`java`类名。
  ```proto
  option java_outer_classname = "Ponycopter";
  ```
+ `java_multiple_files`【文件级别】：针对`java`代码，如果为`false`则只生成一个`.java`文件，所有的代码都嵌套在`java_outer_classname`对应的类中。
如果为`true`，每个`message/enum/service/etc`都会生成一个独立的顶级类，分别对应一个`.java`文件。
  ```proto
  option java_multiple_files = true;  // 不指定，默认是 false
  ```
+ `optimize_for`【文件级别】：针对`c++/java`代码，告诉编译器为哪种用途优化生成的代码结构，权衡代码大小、速度和功能完整性。
  ```proto
  option optimize_for = CODE_SIZE;
  ```
  `optimize_for`的取值有以下三种：
    + `SPEED`【`default`】：代码高度优化，为运行速度优化，接口完整，用于性能敏感的服务端。
    + `CODE_SIZE`：为减少代码体积优化，接口完整，但运行速度不如`SPEED`，用于移动端、嵌入式等场景。
    + `LITE_RUNTIME`：使用精简版运行时，牺牲功能换体积，接口不完整。
+ `cc_enable_arenas`【文件级别】：针对`C++`代码，开启`arena`内存分配。加快消息的分配和释放速度，并减少内存碎片和分配开销，适合在性能关键场景中。
+ `objc_class_prefix`【文件级别】：针对`MacOS/IOS`设计，控制生成的`Objective-C`类名前缀，以避免类名冲突。
  ```proto
  option objc_class_prefix = "ABC";
  message User {
    string name = 1;
  }
  ```
  生成的`Objective-C `类名是`ABCUser`。
+ `packed`【字段级别】：默认是`true`，用于`repeated`字段。对于数字类型，用于高效的编码。
  ```proto
  repeated int32 samples = 4 [packed = false];
  ```
+ `deprecated`【字段级别】：如果设置为`true`，则表示此字段被废弃，不应该使用（语义上约定）。
  ```proto
  int32 old_field = 6 [deprecated = true];
  ```
`Options`的`targets`和`retention`选项分别用于控制自定义`option`可应用到哪些对象和控制自定义`option`是否保留在`descriptor/代码`中。
# 编码原理
## 可变宽度编码
**可变宽度编码**是`protobuf`序列化的核心，允许使用`1-10`个字节编码`unsigned 64-bit`整数。数字越小，使用字节数越少。
可变宽度编码的每一个字节都有一个最高位（`MSB`）表示是否接下来的字节是当前数据的一部分。每一个字节的低`7`位表示实际负载。
```bash
# 数字 1 的编码如下   0x01
0000 0001
^ msb
# 数字 150 的编码如下 0x9601
10010110 00000001
^ msb    ^ msb
```
如果反序列化，首先需要去掉每个字节的`MSB`位，然后将每个字节低`7`位负载从**小端序转为大端序**，完成拼接。
```c
10010110 00000001        // Original inputs.
 0010110  0000001        // Drop continuation bits.
 0000001  0010110        // Convert to big-endian.
   00000010010110        // Concatenate.
 128 + 16 + 4 + 2 = 150  // Interpret as an unsigned 64-bit integer.
```
## Message 结构
在`.proto`中，`message`是一系列的`key-value`对。`message`的二进制版本使用**字段编号作为键**。在解码时候，通过引用`.proto`中编号对应的字段名和类型决定解码后的字段名和类型。
当`message`被编码，每一个键值对被转为一个`record`，每一个`record`由**字段编号、编码类型、负载**三部分组成。
+ 编码类型：表示后面负载的大小。

编码类型有如下几种（在用的）：
+ `VARINT`：用于`int32`、`int64`、`uint32`、`uint64`、`sint32`、`sint64`、`bool`和`enum`类型，其`ID=0`。
+ `I64`：用于`fixed64`、`sfixed64`、`double`类型，其`ID=1`。
+ `LEN`：用于`string`、`bytes`、`embedded messages`、`packed repeated fields`类型，其`ID=2`。
+ `I32`：用于`fixed32`、`sfixed32`和`float`类型，其`ID=5`。

每一个`record`的`tag`由字段编号和编码类型组成。**字段编号都使用可变宽度编码**。格式是`(field_number << 3) | wire_type`。
也就是说，一个`tag`的低`3`位表示编码类型，剩余的整数表示字段编号。
```proto
message Test1 {
  int32 a = 1;
}
```
假设字段`a`被设置为`150`，序列化后的结果是`08 96 01`。因为`08`对应的二进制是`000 1000`（去掉`MSB`位），低`3`位`000`表示编码类型`0`也就是`VARINT`，
剩下的右移`3`位为`1`，得到字段编号为`1`。所以可以得到后面的字节是**可变宽度编码**。
## 整数编码
### 布尔和枚举
`bool`和`enum`都被按`int32`类型编码，实际上`bool`值被编码为`00`或`01`。
### 有符号整数
对于负整数，`int32`和`int64`与`sint32`和`sint64`编码方式不同。

`intN`类型编码负数使用**二进制补码**。意味着对于用`64-bit`表示的负数，其补码是一个`unsigned 64-bit`整数。考虑可变宽度编码（有`MSB`位）一个字节只有低`7`位是负载，
所以需要`10`个字节表示负数（其中一个字节表示`tag`）。

`sintN`使用`ZigZag`编码方式表示负数。其中正数被编码为`2 * p`，负数被编码为`2 * |n| -1`。编码负数效率比较高，使用较少字节数。
### 非可变宽度编码
`double`和`fixed64`类型固定使用`8`字节，编码类型是`I64`。`float`和`fixed32`类型固定使用`4`字节，编码类型是`I32`。
### Length 前缀编码
`LEN`编码类型有一个动态的长度值，跟在一个`record`的`tag`后。
```proto
message Test2 {
  string b = 2;
}
```
如果设置`b = testing`，因为`string`类型是`LEN`编码，所以编码后的结果是`120774657374696e67`。
```bash
12 07 [74 65 73 74 69 6e 67]
```
其中`12`是`tag`，`07`表示字符串长度值，后面是字符串的`ASICC`码。

需要注意，`submessage`也是`LEN`编码。

# 序列化为 Json
可选的，可以将`.proto`定义的消息序列化为`json`格式。
```proto
syntax = "proto3";

message User {
  string name = 1;
  int32 age = 2;
}
```
将上述的`.proto`定义的消息，生成对于的`Python`代码。然后在使用的时候利用`google.protobuf.json_format`模块序列化为`json`格式。
```python
from user_pb2 import User
from google.protobuf.json_format import MessageToJson

user = User(name="Alice", age=30)
json_str = MessageToJson(user)

print(json_str)  # json_str 是字符串类型
```
执行的结果如下：
```bash
{
  "name": "Alice",
  "age": 30
}
```

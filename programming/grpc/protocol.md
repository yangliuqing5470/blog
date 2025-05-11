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

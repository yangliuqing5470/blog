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

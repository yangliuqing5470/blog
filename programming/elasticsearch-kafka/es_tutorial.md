# 综述
`Elasticsearch`面向**文档**，不仅存储文档，而且可以**索引**每个文档使之可以被检索。`Elasticsearch`使用`json`序列化文档。
一个文档样例如下：
```json
{
    "email":      "john@smith.com",
    "first_name": "John",
    "last_name":  "Smith",
    "info": {
        "bio":         "Eco-warrior and defender of the weak",
        "age":         25,
        "interests": [ "dolphins", "whales" ]
    },
    "join_date": "2014/05/01"
}
```
**索引**类似关系型数据库中的一张表。索引一个文档就是存储一个文档到一个索引（类似插入一条数据到表中）。
在关系型数据库中，为提高某一列查询速度，可以对该列创建索引（内部使用`B-tree`），对应`Elasticsearch`是**倒排索引**。
为了更好理解`Elasticsearch`的相关概念，下表总结了和关系型数据库对比。
|关系型数据库|`Elasticsearch`|
|------------|------------|
|数据库（`database`）|集群 / 索引集合|
|表（`Table`）|索引（`Index`）|
|行（`Row`）|文档（`Document`）|
|列（`Column`）|字段（`Field`）|
|主键（`Primary Key`）|文档 `_id`|
|表结构（`Scheam`）|映射（`Mapping`）|

# 集群
一个运行中的`Elasticsearch`实例称为一个节点，而集群是由一个或者多个拥有相同`cluster.name`配置的节点组成。
当有节点加入集群中或者从集群中移除节点时，集群将会重新平均分布所有的数据。
+ **主节点**：负责**管理集群范围内**的所有变更，例如增加、删除索引，或者增加、删除节点等。而主节点并**不需要涉及到文档级别的变更和搜索等操作**。

每个节点（包括主节点）都知道任意文档所处的位置，并且能够将请求直接转发到存储所需文档的节点。无论将请求发送到哪个节点，它都能负责从各个包含所需文档的节点收集回数据，并将最终结果返回給客户端。

可以通过在`Kibana`的`Dev Tools`的`Console`里面执行以下命令查看**集群健康状态**。
```bash
GET /_cluster/health
```
返回集群状态样例如下（测试集群根据官方文档使用`docker compose` 管理三节点集群）：
```json
{
  "cluster_name" : "docker-cluster",
  "status" : "green",
  "timed_out" : false,
  "number_of_nodes" : 3,
  "number_of_data_nodes" : 3,
  "active_primary_shards" : 10,
  "active_shards" : 20,
  "relocating_shards" : 0,
  "initializing_shards" : 0,
  "unassigned_shards" : 0,
  "delayed_unassigned_shards" : 0,
  "number_of_pending_tasks" : 0,
  "number_of_in_flight_fetch" : 0,
  "task_max_waiting_in_queue_millis" : 0,
  "active_shards_percent_as_number" : 100.0
}
```
重点关注下`status`值：
+ **`green`**：所有的主分片和副本分片都正常运行。
+ **`yellow`**：所有的主分片都正常运行，但不是所有的副本分片都正常运行。
+ **`red`**：有主分片没能正常运行。

**索引是实际指向一个或多个物理分片的逻辑命名空间**。一个**分片**是一个底层工作单元，仅保存部分数据。
分片是数据的容器，文档保存在分片内，分片被分配到集群内的各个节点里。当集群规模扩大或缩小，`Elasticsearch`会自动的在各节点中迁移分片，使得数据仍然均匀分布在集群里。
**每一个分片都是一个完整的搜索引擎实例，可以检索存储的文档**。

分片分为主分片和副分片：
+ **主分片**：索引内任意一个文档都归属于一个主分片，所以主分片的数目决定着索引能够保存的最大数据量。在**索引建立的时候就已经确定了主分片数**。
+ **副分片**：副本分片只是一个主分片的拷贝。副本分片作为硬件故障时保护数据不丢失的冗余备份，并为搜索和返回文档等**读操作**提供服务。
**副本分片数可以随时修改**。

如果关闭`Elasticsearch`集群的一个主节点，而集群必须拥有一个主节点来保证正常工作，所以集群会先选举一个新的主节点。
如果关闭节点导致缺失主分片，没有主分片索引也不能正常工作，所以主节点立刻将其它副本分片提升为主分片。

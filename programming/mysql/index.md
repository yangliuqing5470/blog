# 索引
## 基本原理
### 索引类别
索引用于加快数据查询，是一种数据结构。对于`InnoDB`引擎，索引的实现是`B+`树。`mysql`中支持多种类型的索引，
本文只讨论主键索引、普通单列索引、联合索引。
+ 主键索引：主键索引又叫聚簇索引，**叶子节点存储的是数据表的某一行数据**。表中的`primary key`会用于创建主键索引。
假设表中`id`列表示主键，下面是主键索引简单样例说明：
  ```bash
  其中 Px 表示指向下一个磁盘块的指针；数字表示主键值；叶子节点最后两行表示当前行实际存储数据。
                                      磁盘1
                                      +----+----+----+-----+
                                      | P1 | 44 | P2 | 100 |
                                      +----+----+----+-----+
                                         |         |
                    +--------------------+         +----------------------+
         磁盘2      v                                           磁盘3      v
         +----+---+----+----+----+                             +----+----+----+
         | P1 | 8 | P2 | 37 | P3 |                             | P1 | 65 | P2 |
         +----+---+----+----+----+                             +----+----+----+
           |        |          |                                 |          |
        +--+        +-------+   +---------------+                |          +--------+
        v                   v                   v                v                   v
  +-----+-----+       +-----+-----+       +-----+-----+       +-----+       +-----+-----+-----+
  |  2  |  6  | <---> |  8  |  18 | <---> |  37 |  38 | <---> |  44 | <---> |  65 |  78 |  85 |
  +-----+-----+       +-----+-----+       +-----+-----+       +-----+       +-----+-----+-----+
  |  a  |  b  |       |  c  |  d  |       |  e  |  f  |       |  g  |       |  h  |  i  |  j  |
  |  22 |  26 |       |  28 |  38 |       |  47 |  48 |       |  54 |       |  78 |  88 |  95 |
  +-----+-----+       +-----+-----+       +-----+-----+       +-----+       +-----+-----+-----+
     磁盘4                磁盘5               磁盘6            磁盘7             磁盘8
  ```
  查询语句如下：
  ```bash
  select * from student where id = 38;
  ```
  查询过程如下：
  + 第一次磁盘 IO：从根节点检索，将`数据块1`加载到内存，比较`38 < 44`，走左边 P1；
  + 第二次磁盘 IO：将左边`数据块2`加载到内存，比较`8<37<38`，走右边 P3；
  + 第三次磁盘 IO：将右边`数据块6`加载到内存，比较`37<38 38=38`，查询完毕。
+ 普通单列索引：对某一列创建普通索引，**`B+`树普通索引叶节点不存储数据，只存储数据的主键值**。例如对普通列`age`创建索引，
下面是普通但列索引的样例：
  ```bash
  其中 Px 表示指向下一个磁盘块的指针；数字表示 age 值；叶子节点最后一行表示存储的主键值。
                                      磁盘1
                                      +----+----+----+-----+
                                      | P1 | 54 | P2 | 100 |
                                      +----+----+----+-----+
                                         |         |
                    +--------------------+         +----------------------+
         磁盘2      v                                           磁盘3      v
         +----+----+----+----+----+                             +----+----+----+
         | P1 | 28 | P2 | 47 | P3 |                             | P1 | 78 | P2 |
         +----+----+----+----+----+                             +----+----+----+
           |        |          |                                 |          |
        +--+        +-------+   +---------------+                |          +--------+
        v                   v                   v                v                   v
  +-----+-----+       +-----+-----+       +-----+-----+       +-----+       +-----+-----+-----+
  |  22 |  26 | <---> |  28 |  38 | <---> |  47 |  48 | <---> |  54 | <---> |  78 |  88 |  95 |
  +-----+-----+       +-----+-----+       +-----+-----+       +-----+       +-----+-----+-----+
  |  2  |  6  |       |  8  |  18 |       |  37 |  38 |       |  44 |       |  65 |  78 |  85 |
  +-----+-----+       +-----+-----+       +-----+-----+       +-----+       +-----+-----+-----+
     磁盘4                磁盘5               磁盘6            磁盘7             磁盘8
  ```
  查询语句如下：
  ```bash
  select * from student where age = 48;
  ```
  **使用普通索引需要查询两次索引，第一次查询普通`age`列索引，找到`age=48`对应的主键值 38；第二次根据主键值 38 查询主键索引，
  获取实际的一行数据，查询主键索引过程称为回表。**

  查询过程如下：
  + 第一次磁盘 IO：从`age`列索引的根节点开始检索，将`磁盘块1`加载到内存，比较`48<54`，走左边`P1`指向的磁盘块；
  + 第二次磁盘 IO：将`磁盘块2`加载到内存，比较`28<47<48`，走右边`P3`指向的磁盘块；
  + 第三次磁盘 IO：将`磁盘块6`加载到内存，找到`age=48`对应的主键值`38`；
  + 第四次磁盘 IO：从主键索引根节点检索，将`数据块1`加载到内存，比较`38 < 44`，走左边`P1`；
  + 第五次磁盘 IO：将左边`数据块2`加载到内存，比较`8<37<38`，走右边`P3`；
  + 第六次磁盘 IO：将右边`数据块6`加载到内存，比较`37<38 38=38`，查询完毕。
+ 联合索引：对**多个普通列**创建普通索引，**`B+`树普通索引叶节点不存储数据，只存储数据的主键值**。例如对普通列`name`和`age`设置索引，
索引样例如下：
  ```bash
  其中 Px 表示指向下一个磁盘块的指针；字母和数字表示 name 和 age；叶子节点最后一行表示存储的主键值。
                                      磁盘1
                                      +----+----+----+
                                      |    | g  |    |
                                      | P1 | 54 | P2 |
                                      +----+----+----+
                                         |         |
                    +--------------------+         +----------------------+
         磁盘2      v                                           磁盘3      v
         +----+---+----+----+----+                             +----+----+----+
         |    | c |    | e  |    |                             |    | h  |    |
         | P1 | 28| P2 | 47 | P3 |                             | P1 | 78 | P2 |
         +----+---+----+----+----+                             +----+----+----+
           |        |          |                                 |          |
        +--+        +-------+   +---------------+                |          +--------+
        v                   v                   v                v                   v
  +-----+-----+       +-----+-----+       +-----+-----+       +-----+       +-----+-----+-----+
  |  a  |  b  |       |  c  |  d  |       |  e  |  f  |       |  g  |       |  h  |  i  |  j  |
  |  22 |  26 |       |  28 |  38 |       |  47 |  48 |       |  54 |       |  78 |  88 |  95 |
  +-----+-----+       +-----+-----+       +-----+-----+       +-----+       +-----+-----+-----+
  |  2  |  6  | <---> |  8  |  18 | <---> |  37 |  38 | <---> |  44 | <---> |  65 |  78 |  85 |
  +-----+-----+       +-----+-----+       +-----+-----+       +-----+       +-----+-----+-----+
     磁盘4                磁盘5               磁盘6            磁盘7             磁盘8
  ```
  查询语句如下：
  ```bash
  select * from student where name = 'f' and age = 48;
  ```
  查询过程如下：
  + 第一次磁盘 IO：从`name age`两列索引的根节点开始检索，将`磁盘块1`加载到内存，比较`f<g`，走左边`P1`指向的磁盘块；
  + 第二次磁盘 IO：将`磁盘块2`加载到内存，比较`c<e<f`，走右边`P3`指向的磁盘块；
  + 第三次磁盘 IO：将`磁盘块6`加载到内存，找到`name=f`，同时判断`age=48`，如果满足，则获取主键值`38`；
  + 第四次磁盘 IO：从主键索引根节点检索，将`数据块1`加载到内存，比较`38 < 44`，走左边`P1`；
  + 第五次磁盘 IO：将左边`数据块2`加载到内存，比较`8<37<38`，走右边`P3`；
  + 第六次磁盘 IO：将右边`数据块6`加载到内存，比较`37<38 38=38`，查询完毕。

### 原则或优化
+ **最左匹配**：在组合索引中，首先按创建组合索引最左边列排序。例如上面`name age`组合索引，会先以`name`排序，在`name`相同的情况下，
以`age`排序，也就是说`name`是全局有序的，`age`是局部有序，全局无序。查询的时候，`B+`树以`name`确定搜索方向，如果没有`name`列，
则`B+`树无法确定搜索方向，这就是最左匹配原则；
  > 创建组合索引`idx_name_age (name, age)`，逻辑上可以认为创建列`idx_name (name)`和`idx_name_age (name, age)`两个索引。

  使用组合索引查询时，`mysql`会一直向右匹配直至遇到范围查询`(>、<、between、like)`就停止匹配。
+ **覆盖索引**：对于普通索引查询，查询结果所需要的数据只在主键索引上有，所以不得不回表。但如果查询字段在普通索引的叶节点有，
则直接返回，不需要回表，这种叫覆盖索引。例如：
  ```bash
  select age from student where age = 48;
  ```
  `age`字段就是索引的`key`。

### 执行计划
执行计划样例如下：
```bash
mysql> explain select * from task_info where model_num < 200 and cube_num=100;
+----+-------------+-----------+------------+------+----------------------+------+---------+------+---------+----------+-------------+
| id | select_type | table     | partitions | type | possible_keys        | key  | key_len | ref  | rows    | filtered | Extra       |
+----+-------------+-----------+------------+------+----------------------+------+---------+------+---------+----------+-------------+
|  1 | SIMPLE      | task_info | NULL       | ALL  | index_model_cube_num | NULL | NULL    | NULL | 9435886 |     5.00 | Using where |
+----+-------------+-----------+------------+------+----------------------+------+---------+------+---------+----------+-------------+
1 row in set, 1 warning (0.01 sec)
```
主要字段含义说明如下：
+ `id`：一组数字，表示一个查询中各个子查询执行顺序。如果`id`相同，则从上往下执行，如果`id`不同，值越大，越先被执行；
+ `select_type`：每个子查询的类型，取值如下：
  + `SIMPLE`：不包含任何子查询或`union`等查询；
  + `PRIMARY`：包含子查询最外层查询就显示为`PRIMARY`；
  + `SUBQUERY`：在`select`或`where`字句中包含的查询；
  + `DERIVED`：`from`字句中包含的查询；
  + `UNION`：出现在`union`后的查询语句中；
  + `UNION RESULT`：从`UNION`中获取结果集；
+ `type`：查询类型，部分取值如下：
  + `ALL`：扫描全表数据；
  + `index`：遍历索引；
  + `range`：索引范围查找；
  + `index_subquery`：子查询中使用`ref`；
  + `unique_subquery`：子查询中使用`eq_ref`；
  + `fulltext`：使用全文索引；
  + `ref`：使用非唯一索引查询；
  + `const`：使用主键索引或唯一索引查询，且匹配结果只有一条；
  + `system`：`const`的特例；
+ `possible_keys`：可能使用的索引，但不一定使用，当改列为`NULL`，需要考虑`SQL`优化；
+ `key`：实际使用的索引；
+ `Extra`：附加信息，取值如下：
  + `Using index`：使用了覆盖索引，不用回表；
  + `Using where`：使用`where`子句对结果集进行筛选；
  + `Using temporary`：需要创建临时表来存储查询的结果，常见于`ORDER BY`和`GROUP BY`；
  + `Using filesort`：表示`MySQL`使用了文件排序算法来排序结果集，而不是通过索引顺序快速获取结果。
  这通常是因为没有合适的索引或者查询需要进行排序操作；
  + `Using index condition`：查询优化器选择使用了索引条件下推这个特性；

## 测试环境准备
创建测试表`task_info`：
```bash
mysql> create table task_info (id bigint(20) unsigned not null auto_increment, task_id varchar(32) not null default "", usetime int(4), source char(8), model_num int(4), cube_num int(4), primary key(id)) engine=InnoDB CHARSET=utf8mb4;
```
其中列`id`是自增的`primary key`。对列`task_id`和`usetime`添加单列索引：
```bash
mysql> alter table task_info add index index_task_id(task_id);

mysql> alter table task_info add index index_usetime(usetime);
```
对列`model_num`和`cube_num`添加联合索引：
```bash
mysql> alter table task_info add index index_model_cube_num(model_num, cube_num);
```
测试表`task_info`的结构如下：
```bash
mysql> show columns from task_info;
+-----------+-----------------+------+-----+---------+----------------+
| Field     | Type            | Null | Key | Default | Extra          |
+-----------+-----------------+------+-----+---------+----------------+
| id        | bigint unsigned | NO   | PRI | NULL    | auto_increment |
| task_id   | varchar(32)     | NO   | MUL |         |                |
| usetime   | int             | YES  | MUL | NULL    |                |
| source    | char(8)         | YES  |     | NULL    |                |
| model_num | int             | YES  | MUL | NULL    |                |
| cube_num  | int             | YES  |     | NULL    |                |
+-----------+-----------------+------+-----+---------+----------------+
```
索引的信息如下：
```bash
mysql> show index from task_info;
+-----------+------------+----------------------+--------------+-------------+-----------+-------------+----------+--------+------+------------+---------+---------------+---------+------------+
| Table     | Non_unique | Key_name             | Seq_in_index | Column_name | Collation | Cardinality | Sub_part | Packed | Null | Index_type | Comment | Index_comment | Visible | Expression |
+-----------+------------+----------------------+--------------+-------------+-----------+-------------+----------+--------+------+------------+---------+---------------+---------+------------+
| task_info |          0 | PRIMARY              |            1 | id          | A         |           0 |     NULL |   NULL |      | BTREE      |         |               | YES     | NULL       |
| task_info |          1 | index_task_id        |            1 | task_id     | A         |           0 |     NULL |   NULL |      | BTREE      |         |               | YES     | NULL       |
| task_info |          1 | index_usetime        |            1 | usetime     | A         |           0 |     NULL |   NULL | YES  | BTREE      |         |               | YES     | NULL       |
| task_info |          1 | index_model_cube_num |            1 | model_num   | A         |           0 |     NULL |   NULL | YES  | BTREE      |         |               | YES     | NULL       |
| task_info |          1 | index_model_cube_num |            2 | cube_num    | A         |           0 |     NULL |   NULL | YES  | BTREE      |         |               | YES     | NULL       |
+-----------+------------+----------------------+--------------+-------------+-----------+-------------+----------+--------+------+------------+---------+---------------+---------+------------+
```
插入一千万数据到测试表，批量插入脚本如下：
```python
import pymysql
import random
import uuid


sources = ["1", "2", "3", "4", "5" ,"6"]

def get_one_task_info():
    task_id = uuid.uuid1().hex
    usetime = random.randint(1, 3000)
    source  = sources[random.randint(0, 5)]
    model_num = random.randint(20, 400)
    cube_num = random.randint(1, 200)
    return task_id, usetime, source, model_num, cube_num

def main():
    db = pymysql.connect(host="localhost", port=3306, user="root", db="testdb", password="xxxx")
    cursor = db.cursor()
    sql = "INSERT INTO task_info(task_id, usetime, source, model_num, cube_num) VALUES (%s, %s, %s, %s, %s)"
    count = 8000000
    V = list()
    for _ in range(count):
        V.append(get_one_task_info())
    cursor.executemany(sql, tuple(V))
    db.commit()
    cursor.close()
    db.close()


if __name__ == "__main__":
    main()
```
执行完，查看表的总数目如下：
```bash
mysql> select count(1) from task_info;
+----------+
| count(1) |
+----------+
| 10000001 |
+----------+
1 row in set (1.54 sec)
```
最终表中`id`列是主键索引，`task_id`和`usetime`两列是两个普通索引，`source`没有添加索引，`model_num`和`cube_num`是一个联合索引。

## 测试结果
### 普通索引 vs 没有索引
使用有普通索引的列`usetime`查询，执行计划如下：
```bash
mysql> explain select SQL_NO_CACHE count(1) from task_info where usetime=100;
+----+-------------+-----------+------------+------+---------------+---------------+---------+-------+------+----------+-------------+
| id | select_type | table     | partitions | type | possible_keys | key           | key_len | ref   | rows | filtered | Extra       |
+----+-------------+-----------+------------+------+---------------+---------------+---------+-------+------+----------+-------------+
|  1 | SIMPLE      | task_info | NULL       | ref  | index_usetime | index_usetime | 5       | const | 3296 |   100.00 | Using index |
+----+-------------+-----------+------------+------+---------------+---------------+---------+-------+------+----------+-------------+
1 row in set, 2 warnings (0.00 sec)
```
查询使用索引`index_usetime`，查询类型为`ref`。查询结果及耗时如下：
```bash
mysql> select SQL_NO_CACHE count(1) from task_info where usetime=100;
+----------+
| count(1) |
+----------+
|     3296 |
+----------+
1 row in set, 1 warning (0.00 sec)
```
不使用索引的列`source`查询，执行计划如下：
```bash
mysql> explain select SQL_NO_CACHE count(1) from task_info where source=3;
+----+-------------+-----------+------------+------+---------------+------+---------+------+---------+----------+-------------+
| id | select_type | table     | partitions | type | possible_keys | key  | key_len | ref  | rows    | filtered | Extra       |
+----+-------------+-----------+------------+------+---------------+------+---------+------+---------+----------+-------------+
|  1 | SIMPLE      | task_info | NULL       | ALL  | NULL          | NULL | NULL    | NULL | 9435886 |    10.00 | Using where |
+----+-------------+-----------+------------+------+---------------+------+---------+------+---------+----------+-------------+
1 row in set, 2 warnings (0.00 sec)
```
查询不使用索引，查询类型为`ALL`，查询结果及耗时如下：
```bash
mysql> select SQL_NO_CACHE count(1) from task_info where source=3;
+----------+
| count(1) |
+----------+
|  1666975 |
+----------+
1 row in set, 1 warning (5.06 sec)
```
结论：使用索引可以有效提高查询效率。

### 联合索引
联合索引需要满足**最左匹配原则**，例如对于联合索引`index_model_cube_num (model_num, cube_num)`，查询执行计划如下：
```bash
mysql> explain select SQL_NO_CACHE * from task_info where model_num=184 and cube_num=141;
+----+-------------+-----------+------------+------+----------------------+----------------------+---------+-------------+------+----------+-------+
| id | select_type | table     | partitions | type | possible_keys        | key                  | key_len | ref         | rows | filtered | Extra |
+----+-------------+-----------+------------+------+----------------------+----------------------+---------+-------------+------+----------+-------+
|  1 | SIMPLE      | task_info | NULL       | ref  | index_model_cube_num | index_model_cube_num | 10      | const,const |  148 |   100.00 | NULL  |
+----+-------------+-----------+------------+------+----------------------+----------------------+---------+-------------+------+----------+-------+
1 row in set, 2 warnings (0.00 sec)
```
查询条件为`model_num and cube_num`时，使用联合索引，查询类型为`ref`。查询条件为`model_num`的执行计划如下：
```bash
mysql> explain select SQL_NO_CACHE count(*) from task_info where model_num=184;
+----+-------------+-----------+------------+------+----------------------+----------------------+---------+-------+-------+----------+-------------+
| id | select_type | table     | partitions | type | possible_keys        | key                  | key_len | ref   | rows  | filtered | Extra       |
+----+-------------+-----------+------------+------+----------------------+----------------------+---------+-------+-------+----------+-------------+
|  1 | SIMPLE      | task_info | NULL       | ref  | index_model_cube_num | index_model_cube_num | 5       | const | 57264 |   100.00 | Using index |
+----+-------------+-----------+------------+------+----------------------+----------------------+---------+-------+-------+----------+-------------+
1 row in set, 2 warnings (0.01 sec)
```
查询条件`model_num`时，使用联合索引，查询类型为`ref`。当查询条件为`cube_num`，执行计划如下：
```bash
mysql> explain select SQL_NO_CACHE count(*) from task_info where cube_num=141;
+----+-------------+-----------+------------+-------+----------------------+----------------------+---------+------+---------+----------+----------------------------------------+
| id | select_type | table     | partitions | type  | possible_keys        | key                  | key_len | ref  | rows    | filtered | Extra                                  |
+----+-------------+-----------+------------+-------+----------------------+----------------------+---------+------+---------+----------+----------------------------------------+
|  1 | SIMPLE      | task_info | NULL       | range | index_model_cube_num | index_model_cube_num | 10      | NULL | 2358971 |   100.00 | Using where; Using index for skip scan |
+----+-------------+-----------+------------+-------+----------------------+----------------------+---------+------+---------+----------+----------------------------------------+
1 row in set, 2 warnings (0.00 sec)
```
查询条件为`cube_num`时，在新版的`MySQL`中使用联合索引，但查询类型为`range`，`Extra`包含`Using index for skip scan`，
这是新版`MySQL`优化；对于老版本的`MySQL`，则不会使用联合索引，查询类型为`ALL`。查询效率对比如下：
```bash
# 使用 model_num 查询，满足最左匹配
mysql> select SQL_NO_CACHE count(*) from task_info where model_num=184;
+----------+
| count(*) |
+----------+
|    26432 |
+----------+
1 row in set, 1 warning (0.02 sec)

# 使用 cube_num 查询，不满足最左匹配
mysql> select SQL_NO_CACHE count(*) from task_info where cube_num=141;
+----------+
| count(*) |
+----------+
|    49772 |
+----------+
1 row in set, 1 warning (0.42 sec)
```

### 索引范围查找
对于索引范围查找，`MySQL`优化器会自动根据查询范围大小选择使用索引还是不使用索引。例如：
```bash
# 范围小，使用索引
mysql> explain select SQL_NO_CACHE * from task_info where usetime>4000;
+----+-------------+-----------+------------+-------+---------------+---------------+---------+------+------+----------+-----------------------+
| id | select_type | table     | partitions | type  | possible_keys | key           | key_len | ref  | rows | filtered | Extra                 |
+----+-------------+-----------+------------+-------+---------------+---------------+---------+------+------+----------+-----------------------+
|  1 | SIMPLE      | task_info | NULL       | range | index_usetime | index_usetime | 5       | NULL |    1 |   100.00 | Using index condition |
+----+-------------+-----------+------------+-------+---------------+---------------+---------+------+------+----------+-----------------------+
1 row in set, 2 warnings (0.00 sec)

# 范围大，不使用索引
mysql> explain select SQL_NO_CACHE * from task_info where usetime>1000;
+----+-------------+-----------+------------+------+---------------+------+---------+------+---------+----------+-------------+
| id | select_type | table     | partitions | type | possible_keys | key  | key_len | ref  | rows    | filtered | Extra       |
+----+-------------+-----------+------------+------+---------------+------+---------+------+---------+----------+-------------+
|  1 | SIMPLE      | task_info | NULL       | ALL  | index_usetime | NULL | NULL    | NULL | 9435886 |    50.00 | Using where |
+----+-------------+-----------+------------+------+---------------+------+---------+------+---------+----------+-------------+
1 row in set, 2 warnings (0.01 sec)
```

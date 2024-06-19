# 索引
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
## 基本原理
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
+ 普通单列索引：对某一列创建普通索引，**`B+`树普通索引叶节点不存储数据，只存储数据的主键值**。
+ 联合索引：

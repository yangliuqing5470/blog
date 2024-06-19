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
索引用于加快数据查询，是一种数据结构。对于`InnoDB`引擎，索引的实现是`B+`树。`myssql`中支持多种类型的索引，
本文只讨论主键索引、普通单列索引、联合索引。


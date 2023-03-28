# 安装
```bash
sudo apt-get update
sudo apt-get install rsync
```

# 服务配置
```bash
sudo vim /etc/default/rsync

修改好配置项并保存
RSYNC_ENABLE=true  # false to true
```

# 配置文件`rsyncd.conf`
## 配置文件说明[官方文档](https://download.samba.org/pub/rsync/rsyncd.conf.5)
配置文件有三类: 注释, 参数, 模块
+ `#`表示注释;
+ 参数的格式: `name = value`;
+ 模块格式: `[module_name]`;

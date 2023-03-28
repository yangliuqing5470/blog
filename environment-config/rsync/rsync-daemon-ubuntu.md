# 安装
```bash
sudo apt-get update
sudo apt-get install rsync
```

# 服务配置
## 修改好配置项并保存 
```bash
sudo vim /etc/default/rsync

RSYNC_ENABLE=true  # false to true
```
## 查看查看服务启动配置
```bash
cat /lib/systemd/system/rsync.service

[Unit]
Description=fast remote file copy program daemon
Documentation=man:rsync(1) man:rsyncd.conf(5)
ConditionPathExists=/etc/rsyncd.conf
After=network.target

[Service]
ExecStart=/usr/bin/rsync --daemon --no-detach

[Install]
WantedBy=multi-user.target
```

## 配置文件`rsyncd.conf`
配置文件说明--[官方文档](https://download.samba.org/pub/rsync/rsyncd.conf.5)
配置文件有三类: 注释, 参数, 模块
+ `#`表示注释;
+ 参数的格式: `name = value`;
+ 模块格式: `[module_name]`;

### 配置文件示例
```bash
# /etc/rsyncd: configuration file for rsync daemon mode

# See rsyncd.conf man page for more options.

# configuration example:

uid = root
gid = root
port = 873
use chroot = no
max connections = 4
pid file = /var/run/rsyncd.pid
transfer logging = yes
timeout = 900
# secrets file = /etc/rsyncd.secrets
ignore nonreadable = yes
# dont compress   = *.gz *.tgz *.zip *.z *.Z *.rpm *.deb *.bz2

[rsyncdata]
path = /home/parallels/Workspace/rsyncdata
```

# 服务启动
```bash
sudo systemctl start rsync.service
```

# 使用示例
```bash
rsync <src_path> <des_ip>::rsyncdata
```

# 安装
## 服务端
```bash
sudo apt-get update
sudo apt-get install rpcbind
sudo apt-get install nfs-kernel-server
```

## 客户端
```bash
sudo apt-get update
sudo apt-get install rpcbind
sudo apt-get install nfs-common
```

# 配置
## 服务端
### 创建共享目录
```bash
mkdir -p ~/Workspace
```
### 修改配置文件
打开配置文件
```bash
sudo vim /etc/exports
```
配置暴露给`NFS`客户端的访问列表--[共享目录路径  允许的客户端(参数)]。配置文件示例
```bash
# /etc/exports: the access control list for filesystems which may be exported
#               to NFS clients.  See exports(5).
#
# Example for NFSv2 and NFSv3:
# /srv/homes       hostname1(rw,sync,no_subtree_check) hostname2(ro,sync,no_subtree_check)
#
# Example for NFSv4:
# /srv/nfs4        gss/krb5i(rw,sync,fsid=0,crossmnt,no_subtree_check)
# /srv/nfs4/homes  gss/krb5i(rw,sync,no_subtree_check)

/home/parallels/Workspace 192.168.18.0/24(rw,insecure,all_squash,no_subtree_check,anonuid=1000,anongid=1000)
```
### 启动NFS服务端
```bash
sudo systemctl start nfs-kernel-server.service
```
每次修改配置文件`/etc/exports`不需要重启服务，调用命令`sudo exportfs -r`即可

### 常用参数说明
`exportfs`命令常用命令及参数
- `exportfs -r`：重新导出所有共享目录，使得/etc/exports文件中的更改生效
- `exportfs -v`：显示当前导出的所有共享目录及其选项
- `exportfs -u [客户端]:[目录]`：取消导出指定的共享目录
- `exportfs [客户端]:[目录]`：导出指定的共享目录给客户端访问

/etc/exports文件用于配置NFS服务器上的共享目录。每行定义一个共享目录及其选项，格式为：
```bash
[共享的目录] [客户端1(选项)] [客户端2(选项)] ...
```
`[共享的目录]`是要共享的目录的路径，`[客户端]`是允许访问该目录的客户端主机名或IP地址，`(选项)`是一组
逗号分隔的选项，用于控制客户端对共享目录的访问。<br>
`/etc/exports`常用选项
- `rw`：允许客户端对共享目录进行读写操作
- `ro`：只允许客户端对共享目录进行只读操作
- `sync`：要求NFS服务器在回复客户端之前将数据写入磁盘
- `async`：允许NFS服务器在回复客户端之前不将数据写入磁盘
- `no_root_squash`：不映射客户端的root用户到服务器上的匿名用户
- `root_squash`：将客户端的root用户映射到服务器上的匿名用户
- `all_squash`：将所有客户端用户映射到服务器上的匿名用户
- `no_all_squash`：不映射所有客户端用户到服务器上的匿名用户
- `anonuid`：设置匿名用户的UID
- `anongid`：设置匿名用户组的GID
- `subtree_check`：检查客户端请求是否在共享目录的子树中
- `no_subtree_check`：不检查客户端请求是否在共享目录的子树中
- `insecure`：控制 NFS 服务器是否接受来自客户端的非特权端口(大于1024端口)的连接，默认情况下，NFS 
服务器只接受来自客户端特权端口(小于等于1024)的连接。这是为了增强安全性，因为只有特权用户(例如root用户)才
能在客户端上打开特权端口。当使用此选项时，客户端挂载需要使用`noresvport`参数

## 客户端
### 查看NFS服务端共享信息
```bash
# 192.168.18.235 服务端的ip
$ showmount -e 192.168.18.235
Exports list on 192.168.18.235:
/home/parallels/Workspace           192.168.18.0/24
```
### 客户端创建挂载的目录
```bash
mkdir -p ~/Workspace/Ubuntu20
```
### 挂载远程目录
```bash
sudo mount 192.168.18.235:/home/parallels/Workspace ~/Workspace/Ubuntu20
```
### 查看客户端挂载状态
```bash
$ df -h
Filesystem                                 Size   Used  Avail Capacity iused      ifree %iused  Mounted
......
192.168.18.235:/home/parallels/Workspace   62Gi   14Gi   45Gi    24%  326861    3834675    8%   /Users/yangliuqing/Workspace/Yangliuqing/Ubuntu20
```
### 卸载挂载
```bash
sudo umount ~/Workspace/Ubuntu20
```

### 挂载常用参数
在 NFS 客户端上，可以使用`mount`命令来挂载 NFS``服务器上的共享目录。`mount`命令支持许多选项，可以
用来控制挂载操作的行为。<br>
下面是一些常用的mount命令选项：
- `-t nfs`：指定文件系统类型为NFS
- `-o rw`：以读写方式挂载共享目录
- `-o ro`：以只读方式挂载共享目录
- `-o soft`：如果服务器无响应，客户端将报告错误
- `-o hard`：如果服务器无响应，客户端将一直重试，直到服务器恢复
- `-o timeo=[值]`：设置客户端等待服务器响应的超时时间(以十分之一秒为单位)
- `-o retrans=[值]`：设置客户端重试次数
- `-o vers=[值]`：指定NFS协议的版本

例如，要挂载名为`/data`的共享目录，使其可供客户端以读写方式访问，并且在服务器无响应时报告错误，可以
使用以下命令：
```bash
mount -t nfs -o rw,soft [服务器]:/data [挂载点]
```
其中，`[服务器]`是 NFS 服务器的主机名或IP地址，`[挂载点]`是客户端上用于挂载共享目录的目录

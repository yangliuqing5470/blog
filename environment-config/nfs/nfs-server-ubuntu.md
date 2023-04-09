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


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
mkdir -p ~/nfs-share
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


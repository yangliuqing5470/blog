# NFS 问题汇总
## macos 10.15.7 系统使用`NFSv4`版本问题
### 问题描述
客户端环境: `macos 10.15.7` <br>
客户端挂载命令
```bash
sudo mount -t nfs -o vers=4,noresvport, 192.168.18.235:/home/parallels/Workspace ./UbuntuServer/
```
服务端环境: `ubuntu 20.0.4` <br>
服务配置
```bash
➜  nfs git:(master) cat /etc/exports 
/home/parallels/Workspace 192.168.18.0/24(rw,insecure,all_squash,no_subtree_check,anonuid=1000,anongid=1000)
```

客户端可以成功挂载，但是读/写会很慢且写操作失败，通过`wireshark`抓包发现写的时候报`NFSERR_OPENMODE`错误，对目标文件的`open`调用看到的`StateID`和`write`调用
看到的`StateID`不一样(在`ubuntu`客户端这两个`StateID`是一样的)
### 解决方案
还未知上述问题的根本原因，可能是`macos 10.15.7`版本不能很好支持`NFSv4`协议版本，未在最新`macos`系统尝试，先用下面临时方案解决。 <br>
`macos 10.15.7`系统版本使用`NFSv3`版本挂载
```bash
sudo mount -t nfs -o vers=3,noresvport, 192.168.18.235:/home/parallels/Workspace ./UbuntuServer/
```


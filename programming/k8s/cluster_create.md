# 环境准备
## 集群节点
| 节点ip | 系统 | 角色 | hostname |
|-----------|------------------|------|-----------------|
|10.211.55.9|ubuntu24.04-server|master|ylq-ubuntu-server|
|10.211.55.10|ubuntu24.04-server|node|ylq-ubuntu-server-node1|

## 确认防火墙关闭
每个节点都需要操作
```bash
$ sudo ufw status
Status: inactive
```

## 禁止交换分区
每个节点都需要操作

编辑`/etc/fstab`文件，禁止带`swap`的一行，并重启机器。
```shell
# /swap.img     none    swap    sw      0       0
```

## 网络参数配置
每个节点都需要操作

```bash
# 设置所需的 sysctl 参数，参数在重新启动后保持不变
cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
net.ipv4.ip_forward = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
EOF

# 应用 sysctl 参数而不重新启动
sudo sysctl --system
```

## 安装容器运行时
每个节点都需要操作

这里的容器运行时选择`containerd`。[安装指导](https://docs.docker.com/engine/install/ubuntu/)如下：
```bash
# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://mirrors.tuna.tsinghua.edu.cn/docker-ce/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://mirrors.tuna.tsinghua.edu.cn/docker-ce/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```
容器运行时只需要安装`containerd.io`，其他的是可选的。由于国内网络隔离，这里换成清华源：
```bash
https://mirrors.tuna.tsinghua.edu.cn/docker-ce/
```

## 安装 kubeadm、kubelet 和 kubectl
每个节点都需要操作

```bash
sudo apt-get update
# apt-transport-https 可能是一个虚拟包（dummy package）；如果是的话，你可以跳过安装这个包
sudo apt-get install -y apt-transport-https ca-certificates curl gpg

# 如果 `/etc/apt/keyrings` 目录不存在，则应在 curl 命令之前创建它，请阅读下面的注释。
# sudo mkdir -p -m 755 /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.31/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

# 此操作会覆盖 /etc/apt/sources.list.d/kubernetes.list 中现存的所有配置。
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.31/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list

sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl
```

# Mater 节点部署

# 容器网络插件部署

# Worker 节点部署

# Dashboard 可视化插件部署

# 容器存储插件部署

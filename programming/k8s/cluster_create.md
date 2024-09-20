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

## 安装必要的软件
每个节点都需要操作

安装`socat`软件
```bash
sudo apt install socat
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

生成`containerd`默认配置文件：
```bash
containerd config default > ./config.toml
```
在`config.toml`文件中配置`systemd cgroup`驱动：
```bash
...
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc]
  ...
  [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
    SystemdCgroup = true
...
```
在`config.toml`文件中配置`pause`镜像版本为`3.10`（和`kubeadm`版本对应）并修改镜像源为国内源：
```bash
[plugins."io.containerd.grpc.v1.cri"]
  sandbox_image = "registry.aliyuncs.com/google_containers/pause:3.10"
```

将`config.toml`文件覆盖`/etc/containerd/config.toml`下默认文件：
```bash
sudo mv config.toml /etc/containerd/
```
重启`containerd`服务：
```bash
sudo systemctl restart containerd.service
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
生成默认`kubeadm.yaml`配置文件：
```bash
kubeadm config print init-defaults --component-configs KubeletConfiguration,KubeProxyConfiguration > kubeadm.yaml
```
修改`master`节点地址、设置节点名及添加`pod`子网段配置`podSubnet`：
```bash
apiVersion: kubeadm.k8s.io/v1beta4
...
kind: InitConfiguration
localAPIEndpoint:
  # master 节点地址
  advertiseAddress: 10.211.55.9
  bindPort: 6443
nodeRegistration:
  criSocket: unix:///var/run/containerd/containerd.sock
  imagePullPolicy: IfNotPresent
  imagePullSerial: true
  # 设置节点名
  name: ylq-ubuntu-server
  taints: null
...
---
apiServer: {}
apiVersion: kubeadm.k8s.io/v1beta4
...
# 设置国内镜像源地址
imageRepository: registry.aliyuncs.com/google_containers
kind: ClusterConfiguration
kubernetesVersion: 1.31.0
networking:
  dnsDomain: cluster.local
  # 添加pod子网
  podSubnet: 192.168.0.0/16
  serviceSubnet: 10.96.0.0/12
...
```
执行`kubeadm init`命令：
```bash
sudo kubeadm init --config kubeadm.yaml
```
上述命令执行成功后，会输出如下信息：
```bash
Your Kubernetes control-plane has initialized successfully!

To start using your cluster, you need to run the following as a regular user:

  mkdir -p $HOME/.kube
  sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
  sudo chown $(id -u):$(id -g) $HOME/.kube/config

Alternatively, if you are the root user, you can run:

  export KUBECONFIG=/etc/kubernetes/admin.conf

You should now deploy a pod network to the cluster.
Run "kubectl apply -f [podnetwork].yaml" with one of the options listed at:
  https://kubernetes.io/docs/concepts/cluster-administration/addons/

Then you can join any number of worker nodes by running the following on each as root:

kubeadm join 10.211.55.9:6443 --token abcdef.0123456789abcdef \
	--discovery-token-ca-cert-hash sha256:86b06dd50ff64bc1ba67d4f0591a68ad7171fd5d37439bd0d9c40dc778a9aa75
```
根据提示，执行如下配置命令：
```bash
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
```
因为`k8s`集群默认需要以加密方式访问，所以需要将部署生成的`k8s`集群安全配置文件`admin.conf`保存到当前用户的`.kube`目录下，
`kubectl`默认使用此目录下的授权信息访问`k8s`集群。

执行如下命令开启`kubectl`命令行补全：
```bash
echo 'source <(kubectl completion bash)' >>~/.bashrc
source ~/.bashrc
```

# 容器网络插件部署
部署`flannel`容器网络插件。

下载`flannel`容器网络插件配置文件：
```bash
wget https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml
```
修改网络插件配置文件`kube-flannel.yml`子网段为部署集群指定的`pod`子网段`192.168.0.0/16`：
```bash
...
net-conf.json: |
    {
      "Network": "192.168.0.0/16",
      "EnableNFTables": false,
      "Backend": {
        "Type": "vxlan"
      }
    }
...
```
执行如下命令：
```bash
kubectl apply -f kube-flannel.yml
```
成功后查看集群`pod`状态都在`running`状态：
```bash
$ kubectl get pods -A
NAMESPACE      NAME                                        READY   STATUS    RESTARTS   AGE
kube-flannel   kube-flannel-ds-cnvrb                       1/1     Running   0          2m17s
kube-system    coredns-855c4dd65d-7j98d                    1/1     Running   0          20m
kube-system    coredns-855c4dd65d-cf8kd                    1/1     Running   0          20m
kube-system    etcd-ylq-ubuntu-server                      1/1     Running   0          20m
kube-system    kube-apiserver-ylq-ubuntu-server            1/1     Running   0          20m
kube-system    kube-controller-manager-ylq-ubuntu-server   1/1     Running   0          20m
kube-system    kube-proxy-48595                            1/1     Running   0          20m
kube-system    kube-scheduler-ylq-ubuntu-server            1/1     Running   0          20m
```

# Worker 节点部署
在`worker`节点上执行`kubeadm join`命令，以加入`k8s`集群：
```bash
$ sudo kubeadm join 10.211.55.9:6443 --token abcdef.0123456789abcdef  --discovery-token-ca-cert-hash sha256:86b06dd50ff64bc1ba67d4f0591a68ad7171fd5d37439bd0d9c40dc778a9aa75
```
在`master`节点查看集群节点信息：
```bash
$ kubectl get nodes
NAME                      STATUS   ROLES           AGE   VERSION
ylq-ubuntu-server         Ready    control-plane   29m   v1.31.1
ylq-ubuntu-server-node1   Ready    <none>          68s   v1.31.1
```

# Dashboard 可视化插件部署
最新的`dashboard`只能通过`helm`进行安装，需要先安装`helm`包管理软件：
```bash
sudo snap install helm --classic
```
开始安装`dashboard`：
```bash
helm repo add kubernetes-dashboard https://kubernetes.github.io/dashboard/
helm upgrade --install kubernetes-dashboard kubernetes-dashboard/kubernetes-dashboard --create-namespace --namespace kubernetes-dashboard
```
安装成功后会输出如下日志：
```bash
NAME: kubernetes-dashboard
LAST DEPLOYED: Wed Sep 18 10:28:40 2024
NAMESPACE: kubernetes-dashboard
STATUS: deployed
REVISION: 1
TEST SUITE: None
NOTES:
*************************************************************************************************
*** PLEASE BE PATIENT: Kubernetes Dashboard may need a few minutes to get up and become ready ***
*************************************************************************************************

Congratulations! You have just installed Kubernetes Dashboard in your cluster.

To access Dashboard run:
  kubectl -n kubernetes-dashboard port-forward svc/kubernetes-dashboard-kong-proxy 8443:443

NOTE: In case port-forward command does not work, make sure that kong service name is correct.
      Check the services in Kubernetes Dashboard namespace using:
        kubectl -n kubernetes-dashboard get svc

Dashboard will be available at:
  https://localhost:8443
```

# 容器存储插件部署

# 卷类型
卷用于`Pod`中容器数据的持久化。卷的主要部分类型如下：
+ 持久卷（`PV`和`PVC`）。
+ 投射卷：参考 [工作负载](./cluster_workloads.md) 中`Pod`部分相关介绍。
  + `secret`
  + `downloadAPI`
  + `configMap`
  + `serviceAccountToken`
+ `hostPath`
+ `emptyDir`

# emptyDir
若一个`Pod`指定了`emptyDir`类型的卷，则在`Pod`被调度到某一个节点上时，此卷会被创建。`emptyDir`类型的卷初始状态是空的。
当`Pod`从节点上删除时，`emptyDir`类型的卷中数据也会被删除。**`emptyDir`类型卷的生命周期和`Pod`一样**。
> 容器崩溃并不会导致`Pod`被从节点上移除，因此容器崩溃期间`emptyDir`卷中的数据是安全的。

`emptyDir`类型的卷使用场景参考如下：
+ 缓存空间。例如基于磁盘的归并排序。
+ 临时数据存储。数据在`Pod`生命周期期间有效。

`emptyDir`类型卷的主要参数解释如下：
+ `emptyDir.medium`：控制`emptyDir`卷的存储位置，默认值是`""`，表示`emptyDir`卷存储在节点使用的介质，例如磁盘、`SSD`等。
也可以指定`Memory`值，告诉`k8s`挂载`tmpfs`（内存文件系统）。如果指定了`Memory`值，写入的所有文件都会计入容器的内存消耗，受容器内存限制约束。
+ `emptyDir.sizeLimit`：指定使用的存储介质的大小。`emptyDir`的内存介质最大使用量将是此处指定的`sizeLimit`与`Pod`中所有容器内存限制总和这两个值之间的最小值。

`emptyDir`类型卷使用样例如下：
```yml
apiVersion: v1
kind: Pod
metadata:
  name: test-pd
spec:
  containers:
  - image: registry.k8s.io/test-webserver
    name: test-container
    volumeMounts:
    - mountPath: /cache
      name: cache-volume
  volumes:
  - name: cache-volume
    emptyDir:
      sizeLimit: 500Mi
```

# hostPath
`hostPath`卷能将主机节点文件系统上的文件或目录挂载到`Pod`中。`hostPath`类型卷主要参数解释如下：
+ `hostPath.path`：目录在主机节点上的路径。
+ `hostPath.type`：部分取值及含义说明如下：
  + `""`：默认值，表示在安装`hostPath`卷之前不做任何检查。
  + `DirectoryOrCreate`：如果给定路径不存在，那么将创建空目录，权限设置为`0755`，具有与`kubelet`相同的组和属主信息。
  + `Directory`：目录在给定路径上必须存在。
  + `FileOrCreate`：如果给定路径不存在，创建空文件，权限设置为`0644`，具有与`kubelet`相同的组和所有权。注意不会创建文件的父目录，
  如果父目录不存在，则`Pod`启动失败。
  + `File`：文件在给定路径必须存在。
  + `Socket`：`UNIX socket`在给定路径必须存在。

`hostPath`类型卷的使用样例如下：
```yml
apiVersion: v1
kind: Pod
metadata:
  name: test-webserver
spec:
  os: { name: linux }
  nodeSelector:
    kubernetes.io/os: linux
  containers:
  - name: test-webserver
    image: registry.k8s.io/test-webserver:latest
    volumeMounts:
    - mountPath: /var/local/aaa
      name: mydir
    - mountPath: /var/local/aaa/1.txt
      name: myfile
  volumes:
  - name: mydir
    hostPath:
      # 确保文件所在目录成功创建。
      path: /var/local/aaa
      type: DirectoryOrCreate
  - name: myfile
    hostPath:
      path: /var/local/aaa/1.txt
      type: FileOrCreate
```
上述定义的`Pod`将`/var/local/aaa`挂载到`Pod`的容器中，如果节点上没有路径`/var/local/aaa`，`kubelet`会创建这一目录，
然后将其挂载到`Pod`中。如果`/var/local/aaa`已经存在但不是一个目录，`Pod`会失败。

`kubelet`还会尝试在该目录内创建一个名为`/var/local/aaa/1.txt`的文件（从主机的视角来看）；
如果在该路径上已经存在但不是常规文件，则`Pod`会失败。

# 持久卷
对于持久化存储，`k8s`设计上使用了`PersistentVolume, PV`和`PersistentVolumeClaim, PVC`两个`API`对象。
+ `PV`：是集群中的一块存储，由集群管理员事先创建好。记录了存储的实现细节，例如使用`NFS`，`CFS`等。
  ```yml
  apiVersion: v1
  kind: PersistentVolume
  metadata:
    name: nfs
  spec:
    capacity:
      storage: 1Gi
    accessModes:
      - ReadWriteMany
    storageClassName: manual
    nfs:
      server: 10.244.1.4
      path: "/"
  ```
+ `PVC`：用户声明对存储的请求。例如申领特定大小和访问模式（`ReadWriteOnce`访问）的持久化存储。
  ```yml
  apiVersion: v1
  kind: PersistentVolumeClaim
  metadata:
    name: nfs
  spec:
    accessModes:
      - ReadWriteMany
    storageClassName: manual
    resources:
      requests:
        storage: 1Gi
  ```

用户提交了一个`PVC`，`k8s`会自动寻找一个`PV`与之绑定。绑定的原则主要包括：
+ `PV`和`PVC`的`spec`字段内容匹配。例如`PV`声明的存储容量`storage`必须大于等于`PVC`的请求。`PV`的访问模式`accessModes`必须包含`PVC`请求的访问模式。
`PVC`和`PV`的存储类`storageClassName`必须一样。

**`PV`和`PVC`的绑定是一一对应关系。即使`PV`的容量有空余也不能绑定多个匹配的`PVC`。** 一旦`PV`和`PVC`绑定，
`PV`对象的名字会填到`PVC`对象的`spec.volumeName`字段。

`PV`对象是如何变为一个持久化存储的呢？所谓持久化存储是指不和宿主机绑定，当容器重启或在其他节点部署，可以依然挂载之前的`Volumn`访问之前的内容。
持久化存储通常依赖一个远程存储服务，例如`NFS`，`CFS`等。为了实现持久化这个目的，`k8s`会使用指定的远程存储服务为容器准备一个持久化的宿主机目录，
以供将来容器挂载使用。`k8s`通过两阶段准备持久化的**宿主机目录**：
+ **`Attach`**：**给宿主机挂载一块磁盘**。这部分由`AttachDetachController`和`external-attacher`协作完成。具体来说就是`AttachDetachController`检查宿主机需要挂载远程磁盘，
`AttachDetachController`创建一个`VolumeAttachment`对象描述远程磁盘和宿主机关系，`external-attacher`观察到`VolumeAttachment`对象，根据描述关系调用`CSI`接口将远程存储挂载到宿主机。
    ```bash
    # GoogleCloud 提供的 Persistent Disk
    gcloud compute instances attach-disk < 虚拟机名字 > --disk < 远程磁盘名字 >
    ```
+ **`Mount`**：将上一步给宿主机加的磁盘挂载到宿主机指定的目录，由`kubelet`组件完成。宿主机的指定目录一般是：
  ```bash
  /var/lib/kubelet/pods/<Pod-ID>/volumes/kubernetes.io~<Volumn 类型>/<Volumn 名字>
  ```
  如果是远程存储，相当于执行如下命令：
  ```bash
  # 通过 lsblk 命令获取磁盘设备 ID
  $ sudo lsblk
  # 格式化成 ext4 格式
  $ sudo mkfs.ext4 -m 0 -F -E lazy_itable_init=0,lazy_journal_init=0,discard /dev/<磁盘设备ID>
  # 挂载到挂载点
  $ sudo mkdir -p /var/lib/kubelet/pods/<Pod的ID>/volumes/kubernetes.io~<Volume类型>/<Volume名字>
  mount /dev/<磁盘设备ID> /var/lib/kubelet/pods/<Pod的ID>/volumes/kubernetes.io~<Volume类型>/<Volume名字>
  ```
  如果是`NFS`，没有磁盘，节点直接作为`NFS`的客户端。相当于执行如下命令：
  ```bash
  # 挂载 NFS 服务的 / 目录
  $ mount -t nfs <NFS服务器地址>:/ /var/lib/kubelet/pods/<Pod的ID>/volumes/kubernetes.io~<Volume类型>/<Volume名字>
  ```
完成了**持久化的宿主机目录**，接下来`kubelet`只需要将此宿主机目录通过`CRI`的`Mounts`参数传递给`docker`容器即可。类似执行：
```bash
sudo docker run -v /home:/test ...
```
以上就是`PV`和`PVC`挂载绑定使用的原理。

`PV`除了可以静态创建（管理员事先创建好），也可以通过`StorageClass`动态创建。`StorageClass`可以理解为创建`PV`的模版。
每一个`StorageClass`类都会有`provisioner`、`parameters`和`reclaimPolicy`字段。
+ `provisioner`：制备器类别，也就是用于创建具体`PV`。
+ `parameters`：创建`PV`的制备器的参数。
+ `reclaimPolicy`：控制此存储类动态制备的`PersistentVolume`的`reclaimPolicy`。默认为`Delete`。

下面以一个创建`NFS`类型远程存储`PV`的`StorageClass`样例来说明其工作原理。

**准备工作如下**：
+ 集群部署`NFS`服务。 
  ```yml
  # nfs-server.yaml 文件
  ---
  kind: Service
  apiVersion: v1
  metadata:
    name: nfs-server
    namespace: default
    labels:
      app: nfs-server
  spec:
    type: ClusterIP
    selector:
      app: nfs-server
    ports:
      - name: tcp-2049
        port: 2049
        protocol: TCP
      - name: udp-111
        port: 111
        protocol: UDP
  ---
  kind: Deployment
  apiVersion: apps/v1
  metadata:
    name: nfs-server
    namespace: default
  spec:
    replicas: 1
    selector:
      matchLabels:
        app: nfs-server
    template:
      metadata:
        name: nfs-server
        labels:
          app: nfs-server
      spec:
        nodeSelector:
          "kubernetes.io/os": linux
        containers:
          - name: nfs-server
            image: itsthenetwork/nfs-server-alpine:latest
            env:
              - name: SHARED_DIRECTORY
                value: "/exports"
            volumeMounts:
              - mountPath: /exports
                name: nfs-vol
            securityContext:
              privileged: true
            ports:
              - name: tcp-2049
                containerPort: 2049
                protocol: TCP
              - name: udp-111
                containerPort: 111
                protocol: UDP
        volumes:
          - name: nfs-vol
            hostPath:
              path: /nfs-vol
              type: DirectoryOrCreate
  ```
  在`default`命名空间创建名为`nfs-server`的`Service`。对外由`nfs-server.default.svc.cluster.local`域名暴露`NFS`服务端。
  `NFS`服务端使用宿主机`/nfs-vol`目录作为存储，也就是`NFS`服务端对外共享的`/`实际上是宿主机的`/nfs-vol`目录。
+ 集群安装`NFS CSI`驱动，也就是制备器。
  ```bash
  $ curl -skSL https://raw.githubusercontent.com/kubernetes-csi/csi-driver-nfs/v4.9.0/deploy/install-driver.sh | bash -s v4.9.0 --
  Installing NFS CSI driver, version: v4.9.0 ...
  serviceaccount/csi-nfs-controller-sa created
  serviceaccount/csi-nfs-node-sa created
  clusterrole.rbac.authorization.k8s.io/nfs-external-provisioner-role created
  clusterrolebinding.rbac.authorization.k8s.io/nfs-csi-provisioner-binding created
  csidriver.storage.k8s.io/nfs.csi.k8s.io created
  deployment.apps/csi-nfs-controller created
  daemonset.apps/csi-nfs-node created
  NFS CSI driver installed successfully.
  # 查看 Pod 状态
  $ kubectl -n kube-system get pod -l app=csi-nfs-controller
  NAME                                  READY   STATUS    RESTARTS        AGE
  csi-nfs-controller-85d948fb95-4c4dl   4/4     Running   2 (4m21s ago)   9m13s
  $ kubectl -n kube-system get pod -l app=csi-nfs-node
  NAME                 READY   STATUS    RESTARTS        AGE
  csi-nfs-node-46fkf   3/3     Running   1 (6m28s ago)   9m16s
  csi-nfs-node-5t2nm   3/3     Running   1 (3m23s ago)   9m16s
  ```
  > 清理`NFS CSI`驱动
  > ```bash
  > curl -skSL https://raw.githubusercontent.com/kubernetes-csi/csi-driver-nfs/v4.9.0/deploy/uninstall-driver.sh | bash -s v4.9.0 --
  > ```
**然后创建一个`StorageClass`资源**：
```yml
# storageclass-nfs.yaml 文件
---
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nfs-csi
provisioner: nfs.csi.k8s.io
parameters:
  server: nfs-server.default.svc.cluster.local
  share: /
  # csi.storage.k8s.io/provisioner-secret is only needed for providing mountOptions in DeleteVolume
  # csi.storage.k8s.io/provisioner-secret-name: "mount-options"
  # csi.storage.k8s.io/provisioner-secret-namespace: "default"
reclaimPolicy: Delete
volumeBindingMode: Immediate
allowVolumeExpansion: true
mountOptions:
  - nfsvers=4.1
```
将`StorageClass`资源部署到集群：
```bash
$ kubectl apply -f storageclass-nfs.yaml
# 查看 StorageClass 状态
$ kubectl get storageclasses.storage.k8s.io
NAME      PROVISIONER      RECLAIMPOLICY   VOLUMEBINDINGMODE   ALLOWVOLUMEEXPANSION   AGE
nfs-csi   nfs.csi.k8s.io   Delete          Immediate           true                   2s
```
**创建一个`PVC`资源**：
```yml
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pvc-nfs-dynamic
  namespace: default
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 10Gi
  storageClassName: nfs-csi
```
将`PVC`资源部署到集群：
```bash
$ kubectl apply -f pvc-nfs-csi-dynamic.yaml
# 查看 PVC 状态
$ kubectl get persistentvolumeclaims
NAME              STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   VOLUMEATTRIBUTESCLASS   AGE
pvc-nfs-dynamic   Bound    pvc-41720a1a-e32f-459d-b12b-d33f10c040df   10Gi       RWX            nfs-csi        <unset>                 6s
```
发现`PVC`的状态已经是`Bound`状态，继续查看`PV`对象：
```bash
$ kubectl get persistentvolume
NAME                                       CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS   CLAIM                     STORAGECLASS   VOLUMEATTRIBUTESCLASS   REASON   AGE
pvc-41720a1a-e32f-459d-b12b-d33f10c040df   10Gi       RWX            Delete           Bound    default/pvc-nfs-dynamic   nfs-csi        <unset>                          107s
```
发现集群已经多了一个`pvc-41720a1a-e32f-459d-b12b-d33f10c040df`的`pv`对象，说明`StorageClass`已经自动帮我们创建了`PV`，并和部署的`PVC`绑定。
其中自动创建的`PV`资源如下：
```yml
$ kubectl get persistentvolume pvc-41720a1a-e32f-459d-b12b-d33f10c040df -o yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  annotations:
    pv.kubernetes.io/provisioned-by: nfs.csi.k8s.io
    volume.kubernetes.io/provisioner-deletion-secret-name: ""
    volume.kubernetes.io/provisioner-deletion-secret-namespace: ""
  creationTimestamp: "2024-12-13T10:12:15Z"
  finalizers:
  - external-provisioner.volume.kubernetes.io/finalizer
  - kubernetes.io/pv-protection
  name: pvc-41720a1a-e32f-459d-b12b-d33f10c040df
  resourceVersion: "1436195"
  uid: 732f48b7-7385-4d29-97c0-3b9cc7bd0d76
spec:
  accessModes:
  - ReadWriteMany
  capacity:
    storage: 10Gi
  claimRef:
    apiVersion: v1
    kind: PersistentVolumeClaim
    name: pvc-nfs-dynamic
    namespace: default
    resourceVersion: "1436188"
    uid: 41720a1a-e32f-459d-b12b-d33f10c040df
  csi:
    driver: nfs.csi.k8s.io
    volumeAttributes:
      csi.storage.k8s.io/pv/name: pvc-41720a1a-e32f-459d-b12b-d33f10c040df
      csi.storage.k8s.io/pvc/name: pvc-nfs-dynamic
      csi.storage.k8s.io/pvc/namespace: default
      server: nfs-server.default.svc.cluster.local
      share: /
      storage.kubernetes.io/csiProvisionerIdentity: 1734084111311-2675-nfs.csi.k8s.io
      subdir: pvc-41720a1a-e32f-459d-b12b-d33f10c040df
    volumeHandle: nfs-server.default.svc.cluster.local##pvc-41720a1a-e32f-459d-b12b-d33f10c040df##
  mountOptions:
  - nfsvers=4.1
  persistentVolumeReclaimPolicy: Delete
  storageClassName: nfs-csi
  volumeMode: Filesystem
status:
  lastPhaseTransitionTime: "2024-12-13T10:12:15Z"
  phase: Bound
```
创建的`PV`资源的`spec.csi`和`StorageClass`指定的一样。**所以说`StorageClass`是创建`PV`的模版**。

**创建一个`Deployment`资源并使用上一步的`PVC`资源**：
```yml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: deployment-nfs
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      name: deployment-nfs
  template:
    metadata:
      name: deployment-nfs
      labels:
        name: deployment-nfs
    spec:
      nodeSelector:
        "kubernetes.io/os": linux
      containers:
        - name: deployment-nfs
          image: mcr.microsoft.com/oss/nginx/nginx:1.19.5
          command:
            - "/bin/bash"
            - "-c"
            - set -euo pipefail; while true; do echo $(hostname) $(date) >> /mnt/nfs/outfile; sleep 1; done
          volumeMounts:
            - name: nfs
              mountPath: "/mnt/nfs"
              readOnly: false
      volumes:
        - name: nfs
          persistentVolumeClaim:
            claimName: pvc-nfs-dynamic
```
部署完成后，继续查看宿主机的挂载情况：
```bash
$ mount | grep /var/lib/kubelet/pods/
nfs-server.default.svc.cluster.local:/pvc-41720a1a-e32f-459d-b12b-d33f10c040df on /var/lib/kubelet/pods/76048f69-8869-44de-801f-9f2cbc1e8f08/volumes/kubernetes.io~csi/pvc-41720a1a-e32f-459d-b12b-d33f10c040df/mount type nfs4 (rw,relatime,vers=4.1,rsize=524288,wsize=524288,namlen=255,hard,proto=tcp,timeo=600,retrans=2,sec=sys,clientaddr=10.211.55.10,local_lock=none,addr=10.103.123.135)
```
可以看到，最终会将`NFS`指定目录挂载到宿主机的`/var/lib/kubelet/pods/<Pod-ID>/volumes/kubernetes.io~<Volumn 类型>/<Volumn 名字>`下。
到这里就完成了**持久化宿主机目录**。接着会将宿主机目录挂载到`Pod`中。`Pod`会最终往宿主机目录写数据，最终体现在`NFS`中。查看宿主机的`/nfs-vol`目录：
```bash
$ cat /nfs-vol/pvc-41720a1a-e32f-459d-b12b-d33f10c040df/outfile
deployment-nfs-599c7cc94b-qkbj5 Fri Dec 13 10:23:15 UTC 2024
deployment-nfs-599c7cc94b-qkbj5 Fri Dec 13 10:23:16 UTC 2024
deployment-nfs-599c7cc94b-qkbj5 Fri Dec 13 10:23:17 UTC 2024
deployment-nfs-599c7cc94b-qkbj5 Fri Dec 13 10:23:18 UTC 2024
deployment-nfs-599c7cc94b-qkbj5 Fri Dec 13 10:23:19 UTC 2024
...
```

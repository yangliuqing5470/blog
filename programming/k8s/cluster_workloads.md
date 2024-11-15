# 容器概述
容器的**核心功能**是通过**约束和修改进程的动态表现，为其创造一个边界**。容器本质上是宿主机上的一个进程，
也就是说宿主机上的所有容器都共享宿主机的内核。这也是为什么`Windows`系统不能运行`Linux`容器，低版本内核`Linux`系统不能运行高版本`Linux`容器。

容器创建过程分三个方面工作：
+ 为容器进程设置`Namespace`参数。
  > `Mount Namespace`需要先执行挂载动作，然后启动容器进程，这样在容器内挂载才会生效。
+ 为容器进程指定`Cgroup`参数。
+ 为容器进程切换根目录，调用`chroot`。

一个正在运行的容器可以分以下两个方面看：
+ 一组联合挂载的`rootfs`文件系统，这一部分是**容器镜像**，也是容器的静态视图。
+ 一个由`Namespace`和`Cgroup`实现的隔离环境，这一部分是**容器运行时**，容器的动态视图。

# Pod
`Pod`是`k8s`中最小的调度单位。`Pod`的本质在扮演传统的**虚拟机角色**，容器是这个虚拟机里运行的用户进程。
所以在`Pod`的`API`定义中，凡是和调度，网络，存储，安全等相关的字段都是`Pod`级别的定义（机器相关），而不是容器级别。

`Pod`内可以有多个容器，`Pod`内的所有容器都共享同一个`Network Namespace`，并且可以声明共享同一个`Volume`。
`Pod`中有一个`Infra`容器，此容器永远是第一个被创建的容器，其他用户定义的容器通过`Join Network Namespace`的方式与`Infra`容器关联在一起。

![Pod结构](./images/pod.png)

`Pod`里面的所有容器有如下特点：
+ 互相可以用`localhost`通信。
+ 所有的网络资源都是一个`Pod`一份，且被`Pod`内所有的容器共享，一个`Pod`只有一个`IP`地址。
+ `Pod`的生命周期只和`Infra`容器有关，和其他容器无关。

由于`Pod`的这种设计（类比虚拟机角色），`Pod`里面的容器共享`Volume`实现比较简单。`Pod`中`Volume`定义在`Pod`层级，
每个容器声明挂载`Pod`中定义的`Volume`即可实现容器共享挂载的宿主机上的目录。下面是一个`Pod`的定义：
```yml
apiVersion: v1
kind: Pod
metadata:
  name: two-containers
spec:
  volumes:
    - name: shared-data
      hostPath:
        path: /data
  containers:
    - name: nginx-container
      image: nginx
      volumeMounts:
        - mountPath: /usr/share/nginx/html
          name: shared-data
    - name: debian-container
      image: debian
      volumeMounts:
        - mountPath: /pod-data
          name: shared-data
```
上述的`Pod`定义了`nginx-container`和`debian-container`两个容器，且都挂载了`shared-data`这个`Volume`。`Volume`是`hostPath`类型的挂载，
其对应的目录就是宿主机的`/data`目录，所以两个容器都可以访问宿主机的`/data`目录。

`Pod`中的容器大致可以分以下三种：
+ **主容器**：运行具体应用的容器。
+ **`Init Container`**：在`Pod`内**所有主容器启动之前启动**，`Init`容器运行完就退出。如果为一个`Pod`指定了多个`Init`容器，
这些容器会按顺序逐个运行。每个`Init`容器必须运行成功，下一个才能够运行。当所有`Init`容器运行完成时，`Kubernetes`才会为`Pod`初始化启动应用容器。
  ```yml
  apiVersion: v1
  kind: Pod
  metadata:
    name: myapp-pod
    labels:
      app.kubernetes.io/name: MyApp
  spec:
    containers:
    - name: myapp-container
      image: busybox:1.28
      command: ['sh', '-c', 'echo The app is running! && sleep 3600']
    initContainers:
    - name: init-myservice
      image: busybox:1.28
      command: ['sh', '-c', "until nslookup myservice.$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace).svc.cluster.local; do echo waiting for myservice; sleep 2; done"]
  ```
  样例中`init-myservice`就是一个`Init`容器，`Init`容器可以用于初始化环境设置，一次性任务等。
+ **`Sidecar Container`**：辅助容器是和主容器在同一个`Pod`中运行的。主要用来执行日志收集，数据同步，监控等需求。
  ```yml
  apiVersion: apps/v1
  kind: Deployment
  metadata:
    ...
  spec:
    ...
    template:
      spec:
        containers:
          - name: myapp
            image: alpine:latest
            command: ['sh', '-c', 'while true; do echo "logging" >> /opt/logs.txt; sleep 1; done']
            volumeMounts:
              - name: data
                mountPath: /opt
        initContainers:
          - name: logshipper
            image: alpine:latest
            restartPolicy: Always
            command: ['sh', '-c', 'tail -F /opt/logs.txt']
            volumeMounts:
              - name: data
                mountPath: /opt
        volumes:
          - name: data
            emptyDir: {}
  ```
  和`Init`容器定义类似，只是**需要声明`restartPolicy: Always`字段**。

下面介绍`Pod`定义相关的几个字段。
+ `nodeSelector`：节点选择器，只有匹配`nodeSelector`指定标签的节点才会部署`Pod`。
+ `nodeName`：一旦`Pod`的此字段被赋值，则`k8s`认为此`Pod`已经被调度，一般由调度器设置。但可以人工设置骗过调度器。
+ `hostAliases`：定义`Pod`的`/etc/hosts`文件里面的内容，只对非`hostNetwork`的`Pod`有效。
  ```yml
  apiVersion: v1
  kind: Pod
  metadata:
    name: dnsutils
    namespace: default
  spec:
    restartPolicy: Always
    containers:
    - name: dnsutils
      # 国内无法访问 registry.k8s.io，替换为 k8s.m.daocloud.io
      image: k8s.m.daocloud.io/e2e-test-images/agnhost:2.39
      imagePullPolicy: IfNotPresent
    hostAliases:
    - ip: "10.211.55.10"
      hostnames:
      - "foo"
      - "bar"
  ```
  上述定义的`Pod`的`/etc/hosts`内容如下：
  ```bash
  $ kubectl exec dnsutils -- cat /etc/hosts
  # Kubernetes-managed hosts file.
  127.0.0.1	localhost
  ::1	localhost ip6-localhost ip6-loopback
  fe00::0	ip6-localnet
  fe00::0	ip6-mcastprefix
  fe00::1	ip6-allnodes
  fe00::2	ip6-allrouters
  192.168.1.138	dnsutils
  
  # Entries added by HostAliases.
  10.211.55.10	foo	bar
  ```
  可以看到在`Pod`的`/etc/hosts`文件追加了`10.211.55.10 foo bar`内容。
+ `shareProcessNamespace`：在`Pod`中的所有容器之间共享单个进程名字空间。设置了此字段之后，
容器将能够查看来自同一`Pod`中其他容器的进程并发出信号，并且每个容器中的第一个进程不会被分配`PID 1`。
  ```yml
  apiVersion: v1
  kind: Pod
  metadata:
    name: dnsutils
    namespace: default
  spec:
    # 设置 shareProcessNamespace 参数
    shareProcessNamespace: true
    restartPolicy: Always
    containers:
    - name: dnsutils
      image: k8s.m.daocloud.io/e2e-test-images/agnhost:2.39
      imagePullPolicy: IfNotPresent
  ```
  在上述`Pod`内的容器`dnsutils`里执行`ps`命令：
  ```bash
  $ kubectl exec dnsutils -c dnsutils -- ps
  PID   USER     TIME  COMMAND
      1 65535     0:00 /pause
     20 root      0:00 /agnhost pause
     32 root      0:00 ps
  ```
  可以看到`/pause`容器的进程`ID=1`，`dnsutils`容器的进程`ID=20`。作为对比，不设置`shareProcessNamespace`字段，执行结果如下：
  ```bash
  $ kubectl exec dnsutils -c dnsutils -- ps
  PID   USER     TIME  COMMAND
      1 root      0:00 /agnhost pause
     13 root      0:00 ps
  ```
  可以看到只能看到`dnsutils`容器的进程，且`ID=1`。
+ `lifecycle`：这是容器层级的参数，表示在容器状态发生变化时触发的一系列钩子。
  ```yml
  apiVersion: v1
  kind: Pod
  metadata:
    name: lifecycle-demo
  spec:
    containers:
    - name: lifecycle-demo-container
      image: nginx
      lifecycle:
        postStart:
          exec:
            command: ["/bin/sh", "-c", "echo Hello from the postStart handler > /usr/share/message"]
        preStop:
          exec:
            command: ["/bin/sh","-c","nginx -s quit; while killall -0 nginx; do sleep 1; done"]
  ```
  `postStart`表示在容器启动后立刻执行。`postStart`定义的操作虽然是在容器的`ENTRYPOINT`之后，但是不保证在`ENTRYPOINT`执行完才执行，
  也就是说`postStart`启动时，`ENTRYPOINT`可能还没结束。

  `preStop`表示在容器被结束之前（例如收到`SIGKILL`信号），执行。`preStop`操作是同步的，会阻塞当前容器的结束流程，
  直到`preStop`命令执行完成。

继续介绍下`Pod`中的`Projected Volume`（投射数据卷）：为容器提供预先定义好的数据。主要介绍以下四种：
+ **`Secret`**：将数据加密保存在`etcd`中，`Pod`里面的容器通过`Volume`挂载的方式访问`Secret`里面保存的加密信息。
首先创建一个存放数据库用户和密码的`Secret`对象（**容器以`subPath`卷挂载方式使用`Secret`时，将无法接收`Secret`的更新**）：
  ```yml
  apiVersion: v1
  kind: Secret
  metadata:
    name: secret-mysql
  type: Opaque
  data:
    username: YWRtaW4=
    password: MTIzNDU2
  ```
  其中`data`字段中的`username`和`password`需要是`base64`编码格式：
  ```bash
  # username
  $ echo -n "admin" | base64
  YWRtaW4=
  # password
  $ echo -n "123456" | base64
  MTIzNDU2
  ```
  创建一个`Pod`，引用上述的`Secret`对象：
  ```yml
  apiVersion: v1
  kind: Pod
  metadata:
    name: secret-test-pod
    labels:
      name: secret-test
  spec:
    volumes:
    - name: secret-volume
      secret:
        secretName: secret-mysql
    containers:
    - name: secret-test-container
      image: busybox
      args:
      - sleep
      - "86400"
      volumeMounts:
      - name: secret-volume
        readOnly: true
        mountPath: "/etc/secret-volume"
  ```
  在`Pod`中查看对应的`secret-mysql`信息是否存在：
  ```bash
  # 查看 Pod 中挂载的目录内容，也就是 Secret 定义中 data 字段指定的 key
  $ kubectl exec secret-test-pod -- ls /etc/secret-volume/
  password
  username
  # 查看挂载的文件数据
  $ kubectl exec secret-test-pod -- cat /etc/secret-volume/password
  123456
  $ kubectl exec secret-test-pod -- cat /etc/secret-volume/username
  admin
  ```
  这种通过挂载方式进入容器的`Secret`，一旦对应的`etcd`中数据更新，则`Volume`里的文件内容也会更新，但更新会有延时，编程需要做好重试。
+ **`ConfigMap`**：用法和`Secret`类似，但`ConfigMap`保存的是无需加密的配置信息（**容器以`subPath`卷挂载方式使用`ConfigMap`时，将无法接收`ConfigMap`的更新**）。
首先创建一个`yaml`文件存放需要挂载的配置信息：
  ```yml
  cube_size_to_pano_resolution:
    2048: 8000
    4096: 16000
    6144: 24000
  ```
  从上述文件在集群创建一个`ConfigMap`对象。
  ```bash
  $ kubectl create configmap configmap-test --from-file configmap_test.yaml

  # 查看 configmap 内容
  $ kubectl get configmaps configmap-test -o yaml
  apiVersion: v1
  data:
    configmap_test.yaml: |
      cube_size_to_pano_resolution:
        2048: 8000
        4096: 16000
        6144: 24000
  kind: ConfigMap
  metadata:
    creationTimestamp: "2024-11-13T07:16:25Z"
    name: configmap-test
    namespace: default
    resourceVersion: "1079429"
    uid: e029dfbf-8099-4a17-8dc7-c174e54f8f51
  ```
  创建一个`Pod`，引用上述创建的`ConfigMap`对象：
  ```yml
  apiVersion: v1
  kind: Pod
  metadata:
    name: configmap-test-pod
    labels:
      name: configmap-test
  spec:
    volumes:
    - name: configmap-volume
      configMap:
        name: configmap-test
    containers:
    - name: configmap-test-container
      image: busybox
      args:
      - sleep
      - "86400"
      volumeMounts:
      - name: configmap-volume
        readOnly: true
        mountPath: "/etc/configmap-volume"
  ```
  在`Pod`中查看对应的`configmap-test`资源对象是否存在：
  ```bash
  # 查看 Pod 中挂载的目录内容，也就是 ConfigMap 定义中 data 字段指定的 key
  $ kubectl exec configmap-test-pod -- ls /etc/configmap-volume
  configmap_test.yaml
  # 查看文件内容
  $ kubectl exec configmap-test-pod -- cat /etc/configmap-volume/configmap_test.yaml
  cube_size_to_pano_resolution:
    2048: 8000
    4096: 16000
    6144: 24000
  ```
+ **`Download API`**：让`Pod`里面的容器可以直接获取`Pod API`对象本身的信息。所公开的数据以纯文本格式的只读文件形式存在（**容器以`subPath`卷挂载方式使用`downward API`时，在字段值更改时将不能接收到它的更新**）。
`Download API`可以作为环境变量或者`Volume`。
  ```yml
  apiVersion: v1
  kind: Pod
  metadata:
    name: downloadapi-test-pod
    labels:
      name: downloadapi-test
  spec:
    # 卷挂载方式
    volumes:
    - name: downloadapi-volume
      downwardAPI:
        items:
          - path: "labels"
            fieldRef:
              fieldPath: metadata.labels
          - path: "annotations"
            fieldRef:
              fieldPath: metadata.annotations
    containers:
    - name: downloadapi-test-container
      image: busybox
      args:
      - sleep
      - "86400"
      # 环境变量方式
      env:
      - name: MY_NODE_NAME
        valueFrom:
          fieldRef:
            fieldPath: spec.nodeName
      volumeMounts:
      - name: downloadapi-volume
        mountPath: "/etc/downloadapi-volume"
  ```
  在`Pod`中查看挂载的卷以及环境变量结果：
  ```bash
  # 查看挂载卷
  $ kubectl exec downloadapi-test-pod -- ls /etc/downloadapi-volume
  annotations
  labels
  $ kubectl exec downloadapi-test-pod -- cat /etc/downloadapi-volume/labels
  name="downloadapi-test"
  # 查看环境变量
  $ kubectl exec downloadapi-test-pod -- printenv MY_NODE_NAME
  ylq-ubuntu-server-node1
  ```
  `Download API`支持的字段可以查看 [Download API](https://kubernetes.io/zh-cn/docs/concepts/workloads/pods/downward-api/)
+ **`ServiceAccountToken`**：`ServiceAccount`用于访问集群资源，每个可以设置不同权限。而`ServiceAccountToken`则是`ServiceAccount`的授权信息和文件，
实际是一种特殊的`Secret`。集群中的每个`Pod`都有默认的`ServiceAccount`以及自动挂载默认的`ServiceAccountToken`：
  ```yml
  spec:
    containers:
    - image: k8s.m.daocloud.io/e2e-test-images/agnhost:2.39
      imagePullPolicy: IfNotPresent
      name: dnsutils
      resources: {}
      terminationMessagePath: /dev/termination-log
      terminationMessagePolicy: File
      # 默认挂载的卷
      volumeMounts:
      - mountPath: /var/run/secrets/kubernetes.io/serviceaccount
        name: kube-api-access-7rdtr
        readOnly: true
    ...
    # 默认挂载的卷
    volumes:
    - name: kube-api-access-7rdtr
      projected:
        defaultMode: 420
        sources:
        - serviceAccountToken:
            expirationSeconds: 3607
            path: token
        - configMap:
            items:
            - key: ca.crt
              path: ca.crt
            name: kube-root-ca.crt
        - downwardAPI:
            items:
            - fieldRef:
                apiVersion: v1
                fieldPath: metadata.namespace
              path: namespace
  ```

接下来继续看下`Pod`的健康检查和恢复机制。`Pod`的健康检查可以通过探针实现，探针有三种：
+ **存活探针**：决定何时重启容器。 例如，存活探针可以捕获程序死锁。一个容器的存活探针失败多次，`kubelet`将重启该容器。
存活探针不会等待就绪探针成功。如果想在执行存活探针前等待，可以定义`initialDelaySeconds`。
  ```yml
  apiVersion: v1
  kind: Pod
  metadata:
    labels:
      test: liveness
    name: liveness-exec
  spec:
    containers:
    - name: liveness
      image: registry.k8s.io/busybox
      args:
      - /bin/sh
      - -c
      - touch /tmp/healthy; sleep 30; rm -f /tmp/healthy; sleep 600
      # 定义存活探针
      livenessProbe:
        exec:
          command:
          - cat
          - /tmp/healthy
        initialDelaySeconds: 5
        periodSeconds: 5
  ```
  存活探针除了`exec`，还可以有`HTTP`和`TCP`方式。
+ **就绪探针**：决定何时容器准备好开始接受流量。 这种探针在等待应用执行耗时的初始任务时非常有用，例如建立网络连接、加载文件和预热缓存。
如果就绪探针返回的状态为失败，`Kubernetes`会将该`Pod`从所有对应服务的端点中移除。
  ```yml
  # 就绪探针
  readinessProbe:
    exec:
      command:
      - cat
      - /tmp/healthy
    initialDelaySeconds: 5
    periodSeconds: 5
  ```
  就绪探针和存活探针配置基本一样，也有`HTTP`和`TCP`方式。
+ **启动探针**：可以用于对慢启动容器进行存活性检测，避免它们在启动运行之前就被`kubelet`杀掉。配置了这类探针，会禁用存活检测和就绪检测，直到启动探针成功为止。
这类探针仅在启动时执行，不像存活探针和就绪探针那样周期性地运行。
  ```yml
  # 存活探针
  livenessProbe:
    httpGet:
      path: /healthz
      port: liveness-port
    failureThreshold: 1
    periodSeconds: 10
  # 启动探针 
  startupProbe:
    httpGet:
      path: /healthz
      port: liveness-port
    failureThreshold: 30
    periodSeconds: 10
  ```
  启动探针失败，会根据`restartPolicy`配置决定是否重启。

探针的官方文档可以查看[探针配置](https://kubernetes.io/zh-cn/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)

`Pod`的恢复过程（重启）永远发生在当前节点，一旦`Pod`和一个节点绑定（除非`.spec.nodeName`改变）就不会离开绑定的节点。
即使节点宕机，也不会迁移到其它节点。

# Deployments
`Deployment`用于管理一组`Pod`，是一种控制器对象。`k8s`中的控制器编排模式是控制循环，逻辑如下：
```bash
for {
    实际状态 = 获取集群中对象 X 的实际状态；
    期望状态 = 获取集群中对象 X 的期望状态；
    if 实际状态 == 期望状态:
        什么都不做；
    else:
        执行编排动作，将实际状态调整为期望状态；
}
```
`Deployment`对象的样例如下：
```yml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-deployment
  labels:
    app: nginx
spec:
  replicas: 2
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:1.14.2
        ports:
        - containerPort: 80
```
定义了所有带有标签`app=nginx`的`Pod`的期望状态是`replicas=2`。定义的`template`字段是被管理`Pod`创建使用的模版，内容和上面介绍的`Pod`对象基本一样。
```bash
# 在集群中部署 Deployment
$ kubectl apply -f nginx-deployment.yaml
deployment.apps/nginx-deployment created
# 查询部署结果
$ kubectl get pods
NAME                               READY   STATUS    RESTARTS        AGE
nginx-deployment-d556bf558-2bjdz   1/1     Running   0               13s
nginx-deployment-d556bf558-6ts2w   1/1     Running   0               13s
```
实际上`Deployment`并不直接管理`Pod`对象，而是`ReplicaSet`直接管理`Pod`，`Deployment`管理`ReplicaSet`。三者的关系如下：

![deployment](./images/deployment.png)

`Deployment`只允许容器配置`restartPolicy=Always`。`Deployment`最终对`Pod`的控制动作有两个：
+ 水平拓展：更改期望的副本数。通过命令行操作的方式如下：
  ```bash
  $ kubectl scale deployment nginx-deployment --replicas=3
  deployment.apps/nginx-deployment scaled
  ```
  这时候查看`Deployment`可以发现`replicas`值已经被更新为`3`。
+ 滚动更新：每次部署或者更新`Deployment`时，都会自动创建一个`ReplicaSet`对象，**`ReplicaSet`和应用版本一一对应**。
  ```bash
  # 部署 Deployment
  $ kubectl apply -f nginx-deployment.yaml
  deployment.apps/nginx-deployment created
  # 查看部署的结果
  $ kubectl get deployments.apps
  NAME               READY   UP-TO-DATE   AVAILABLE   AGE
  nginx-deployment   2/2     2            2           21s
  # 查看自动创建的 ReplicaSet 对象，名字后面的随机字符串是 pod-template-hash
  $ kubectl get rs
  NAME                         DESIRED   CURRENT   READY   AGE
  nginx-deployment-d556bf558   2         2         2       57s
  ```
  每次更新`Deployment`，都会触发一次滚动更新。更新`Deployment`方式有多种，例如使用`kubectl edit`命令：
  ```bash
  $ kubectl edit deployments.apps nginx-deployment
  ```
  将`nginx`使用的镜像版本由`1.14.2`改为`1.16.1`，可以通过`kubectl rollout status`命令查看滚动更新结果：
  ```bash
  $ kubectl rollout status deployment nginx-deployment
  deployment "nginx-deployment" successfully rolled out
  ```
  查看`Deployment`的事件信息
  ```bash
  $ kubectl describe deployments.apps nginx-deployment
  Events:
    Type    Reason             Age    From                   Message
    ----    ------             ----   ----                   -------
    Normal  ScalingReplicaSet  3m33s  deployment-controller  Scaled up replica set nginx-deployment-d556bf558 to 2
    Normal  ScalingReplicaSet  3m2s   deployment-controller  Scaled up replica set nginx-deployment-7dbfbc79cf to 1
    Normal  ScalingReplicaSet  3m     deployment-controller  Scaled down replica set nginx-deployment-d556bf558 to 1 from 2
    Normal  ScalingReplicaSet  3m     deployment-controller  Scaled up replica set nginx-deployment-7dbfbc79cf to 2 from 1
    Normal  ScalingReplicaSet  2m59s  deployment-controller  Scaled down replica set nginx-deployment-d556bf558 to 0 from 1
  ```
  可以发现，第一次创建`Deployment`时，其创建了一个`ReplicaSet`对象`nginx-deployment-d556bf558`，并将其扩容到`2`个副本。
  每次更新`Deployment`时，都会创建一个新的`ReplicaSet`对象`nginx-deployment-7dbfbc79cf`，并首先将其扩容到`1`等待就绪，
  然后将旧的`ReplicaSet`副本从`2`缩容到`1`。然后继续将新的`ReplicaSet`副本从`1`扩容到`2`。最后将旧的`ReplicaSet`副本从`1`缩容到`0`。
  如此交替进行。

  默认情况下，更新过程中，`Deployment`确保可用副本数介于`75%-125%`之间。在计算`availableReplicas`数值时候不考虑终止过程中的`Pod`，
  `availableReplicas`的值一定介于`replicas - maxUnavailable`和`replicas + maxSurge`之间。在上线期间看到`Pod`个数比预期的多，
  `Deployment`所消耗的总的资源也大于`replicas + maxSurge`个`Pod`所用的资源，直到被终止的`Pod`所设置的`terminationGracePeriodSeconds`到期为止。
  ```yml
  spec:
    replicas: 2
    strategy:
      rollingUpdate:
        maxSurge: 100%
        maxUnavailable: 0%
      type: RollingUpdate
  ```

  > `Deployment`滚动更新策略的好处就是，遇到新的`Pod`起不来，则不会影响太多线上服务，因为旧的`Pod`还工作。

可以通过如下命令查看`Deployment`历史修改版本信息：
```bash
$ kubectl rollout history deployment nginx-deployment
deployment.apps/nginx-deployment
REVISION  CHANGE-CAUSE
1         <none>
2         <none>
```
> `CHANGE-CAUSE`的内容是从`Deployment`的`kubernetes.io/change-cause`注解复制过来的。复制动作发生在修订版本创建时。
可以通过以下方式设置`CHANGE-CAUSE`消息：
> + 使用`kubectl annotate deployment/nginx-deployment kubernetes.io/change-cause="image updated to 1.16.1"`为`Deployment`添加注解。
> + 手动编辑资源的清单。

查看`Deployment`历史版本的详细信息如下：
```bash
$ kubectl rollout history deployment nginx-deployment --revision=1
deployment.apps/nginx-deployment with revision #1
Pod Template:
  Labels:	app=nginx
	pod-template-hash=d556bf558
  Containers:
   nginx:
    Image:	nginx:1.14.2
    Port:	80/TCP
    Host Port:	0/TCP
    Environment:	<none>
    Mounts:	<none>
  Volumes:	<none>
  Node-Selectors:	<none>
  Tolerations:	<none>
```
可以使用`--to-revision`参数回滚到指定版本。
```bash
$ kubectl rollout undo deployment nginx-deployment --to-revision=1
deployment.apps/nginx-deployment rolled back
```
回滚的动作也是一种滚动更新。指定版本的`ReplicaSet`和当前版本的`ReplicaSet`交替创建或缩容。查看`Deployment`事件信息如下：
```bash
Events:
  Type    Reason             Age   From                   Message
  ----    ------             ----  ----                   -------
  ...
  Normal  ScalingReplicaSet  73s   deployment-controller  Scaled up replica set nginx-deployment-d556bf558 to 1 from 0
  Normal  ScalingReplicaSet  72s   deployment-controller  Scaled down replica set nginx-deployment-7dbfbc79cf to 1 from 2
  Normal  ScalingReplicaSet  72s   deployment-controller  Scaled up replica set nginx-deployment-d556bf558 to 2 from 1
  Normal  ScalingReplicaSet  71s   deployment-controller  Scaled down replica set nginx-deployment-7dbfbc79cf to 0 from 1
```

每次滚动更新都会创建一个新的`ReplicaSet`对象，为了控制历史`ReplicaSet`版本数量，可以通过`.spec.revisionHistoryLimit`用来设定出于回滚目的所要保留的旧`ReplicaSet`数量。
这些旧`ReplicaSet`会消耗`etcd`中的资源。

**`Deployment`控制`ReplicaSet`（应用版本），`ReplicaSet`控制`Pod`（副本数）。**

# StatefulSet
对于有状态应用，也就是各个实例之间不是对等关系以及实例对外部数据有依赖关系。例如主从关系，主备关系等。不适合使用`Deployment`管理。

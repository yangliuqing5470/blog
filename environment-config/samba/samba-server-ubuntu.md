# 服务端安装及配置
## 安装 samba 服务
```bash
sudo apt-get update & sudo apt-get install samba -y
```

## 查看 samba 服务状态
```bash
systemctl status smbd
```

# 配置
## 创建共享目录
```bash
mkdir -p ~/Workspace/sambashare
```

## 修改配置文件
配置文件的路径是`/etc/samba/smb.conf`，该文件包含多个段，每个段由段名开始，直到下个段名。每个段名
放在方括号中间。每段的参数的格式是：`名称=值`。除了`[global]`段外，所有的段都可以看作是一个共享资
源。段名是该共享资源的名字，段里的参数是该共享资源的属性。<br>

### Global Settings -- Browsing/Iedentification
- `workgroup`：设定`samba`服务器所要加入的工作组或者域；
- `server string`：设定`samba`服务器的注释，可以是任何字符串，也可以不填；

配置样例
```bash
workgroup = WORKGROUP

server string = %h server (Samba, Ubuntu)
```
### Global Settings -- Networking
- `interfaces`：设置`samba`服务器监听哪些网卡，可以写网卡名，也可以写该网卡的`IP address/netmask`；
- `bind interfaces only`：默认值是`yes`，确保`samba`服务只绑定到指定的接口；
- hosts allow：表示允许连接到 Samba 服务器的客户端，多个参数以空格隔开。可以用一个 IP 表示，也可以
用一个网段表示；

配置样例
```bash
interfaces = lo enp0s5

bind interfaces only = yes
```
可以使用`ip link`列出所有可用的接口
```bash
➜  sambashare ip link                      
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
2: enp0s5: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP mode DEFAULT group default qlen 1000
    link/ether 00:1c:42:2d:3e:d9 brd ff:ff:ff:ff:ff:ff
3: docker0: <NO-CARRIER,BROADCAST,MULTICAST,UP> mtu 1500 qdisc noqueue state DOWN mode DEFAULT group default 
    link/ether 02:42:ce:9e:f4:07 brd ff:ff:ff:ff:ff:ff
```
### Global Settings -- Debugging
- `log file`：设置`samba`服务器日志文件的存储位置以及日志文件名称；
- `max log size`：设置`samba`服务器日志文件的最大容量，单位为`kB`，`0`代表不限制；
- `log level`：指定日志记录的详细程度。值越高，记录的信息就越详细。默认值为`0`，表示仅记录关键信息；
- `panic action`：指定当`samba`服务器发生严重错误（例如崩溃）时要执行的操作。可以使用此配置项来
运行脚本或命令；
- `logging`：指定日志的类型；

配置样例
```bash
# 日志文件将被存储在 /var/log/samba/ 目录下，文件名为 log. 加上客户端主机名（由 %m 变量表示）
log file = /var/log/samba/log.%m

max log size = 1000

logging = file
# 当`samba`发生严重错误时，它将运行`/usr/local/bin/samba-panic-action`脚本，并将`samba`进程的`PID`作
# 为参数传递给该脚本
panic action = /usr/local/bin/samba-panic-action %d
```
### Global Settings -- Authentication, Domains, Misc
- `server role`：指定`samba`服务的模式，`server role = standalone server`，`samba`服务将作为
一个独立的服务器运行，不加入任何域或目录；`server role` = member server`，`samba`服务将加入
一个`Windows`域或`Active Directory`域，并作为域中的一个成员服务运行；`server role = classic primary domain controller`，
`samba`服务将作为一个经典的`Windows NT4`风格的主域控制器运行；`server role = classic backup domain controller`，
`samba`服务将作为一个经典的`Windows NT4`风格的备份域控制器运行；`server role = active directory domain controller`，
`samba`服务将作为一个 Active Directory 域控制器运行；
- `obey pam restrictions`：指定`samba`服务是否遵守`PAM`（可插拔认证模块）限制，`PAM`是一种用于管理
应用程序身份验证的模块化框架。它允许系统管理员通过配置文件来控制应用程序如何处理身份验证请求；
- `unix password sync`：指定`samba`服务是否将用户的`samba`密码与其`UNIX`密码同步。如果设置
为`yes`，则当用户更改其`samba`密码时，`samba`服务也将更新用户的`UNIX`密码；
- `passwd program`：指定用于更改`UNIX`密码的程序；
- `passwd chat`：指定`samba`服务与`passwd program`程序之间的交互方式；
- `pam password change`：指定`samba`服务是否使用`PAM`（可插拔认证模块）来更改用户的`UNIX`密码，如
果设置为`yes`，则当用户更改其`samba`密码时，`samba`服务将使用`PAM`来更新用户的`UNIX`密码；
- `map to guest`：指定如何将未经身份验证的用户映射到一个匿名账户，`map to guest = never`，从不将
未经身份验证的用户映射到匿名账户；`map to guest = bad user`，仅当用户名不存在时，才将未经身份验证
的用户映射到匿名账户；`map to guest = bad password`，仅当用户名存在但密码错误时，才将未经身份验证
的用户映射到匿名账户；`map to guest = bad uid`，仅当用户名存在但`UID`无效时，才将未经身份验证的用
户映射到匿名账户；

配置样例
```bash
server role = standalone server

obey pam restrictions = yes
# Samba 服务将同步用户的 Samba 密码和 UNIX 密码
unix password sync = yes
# Samba 服务将使用 /usr/bin/passwd 程序来更改 UNIX 密码。%u 变量表示用户名
passwd program = /usr/bin/passwd %u
# Samba 服务将通过发送预定义的字符串来与 passwd program 程序进行交互，以完成密码更改过程
passwd chat = *Enter\snew\s*\spassword:* %n\n *Retype\snew\s*\spassword:* %n\n *password\supdated\ssuccessfully* .
# Samba 服务将使用 PAM 来更改用户的 UNIX 密码
pam password change = yes

map to guest = bad user
```

`Domains`相关参数只有`server role`设置为相关域模式才会生效；<br>

- `usershare path`：指定用于存储用户共享定义的目录，此目录必须存在，并且`samba`用
户（通常是`nobody`）必须具有对其的写入权限；
- `usershare max shares`：指定每个用户最多可以创建多少个用户共享；默认值为`0`，表示禁用用户共享功能；
- `usershare allow guests`：指定是否允许创建允许匿名访问的用户共享；

配置样例
```bash
usershare path = /home/parallels/Workspace/sambashare/usershares
usershare max shares = 100
usershare allow guests = yes
```

### Share Definitions
只对当前的共享资源起作用，一些常见的`[Share]`配置项包括：
- `comment`：简单的解释，内容无关紧要。
- `path`：实际的共享目录。
- `writable`：设置为可写入。
- `browseable`：可以被所有用户浏览到资源名称。
- `guest ok`：可以让用户随意登录。
- `public`：允许匿名查看。
- `valid users`：设置可访问共享资源的用户。
- `readonly`：只读或读写

配置样例
```bash
[sambashare]
comment = Samba Share Directory
path = /home/parallels/Workspace/sambashare/usershares
read only = no
writable = yes
browseable = yes
guest ok = no
valid users = @samba-user
```

### 检查配置文件
```bash
➜  sambashare testparm                     
Load smb config files from /etc/samba/smb.conf
Loaded services file OK.
Weak crypto is allowed

Server role: ROLE_STANDALONE

Press enter to see a dump of your service definitions

# Global parameters
[global]
	bind interfaces only = Yes
	interfaces = lo enp0s5
	log file = /var/log/samba/log.%m
	logging = file
	map to guest = Bad User
	max log size = 1000
	obey pam restrictions = Yes
	pam password change = Yes
	panic action = /usr/share/samba/panic-action %d
	passwd chat = *Enter\snew\s*\spassword:* %n\n *Retype\snew\s*\spassword:* %n\n *password\supdated\ssuccessfully* .
	passwd program = /usr/bin/passwd %u
	server role = standalone server
	server string = %h server (Samba, Ubuntu)
	unix password sync = Yes
	usershare allow guests = Yes
	usershare path = /home/parallels/Workspace/sambashare
	idmap config * : backend = tdb


[sambashare]
	comment = Samba Share Directory
	path = /home/parallels/Workspace/sambashare/usershares
	read only = No
	valid users = @samba-user
```

## 添加 samba 用户
要创建`samba`账户，需要先在系统上为该用户创建一个`UNIX`账户，如果在`samba`配置中启用
了`unix password sync`选项，则当用户更改其`samba`密码时，其`UNIX`密码也将被更新。<br>

### 创建一个 samba 用户
创建一个`samba-user`账户，因为此账户在在系统中不存在，需要先在系统中创建此账户
```bash
➜  sambashare sudo adduser samba-user
正在添加用户"samba-user"...
正在添加新组"samba-user" (1001)...
正在添加新用户"samba-user" (1001) 到组"samba-user"...
创建主目录"/home/samba-user"...
正在从"/etc/skel"复制文件...
新的 密码： 
重新输入新的 密码： 
passwd：已成功更新密码
正在改变 samba-user 的用户信息
请输入新值，或直接敲回车键以使用默认值
	全名 []: 
	房间号码 []: 
	工作电话 []: 
	家庭电话 []: 
	其它 []: 
这些信息是否正确？ [Y/n]
```
创建一个samba 账户
```bash
➜  sambashare sudo smbpasswd -a samba-user 
New SMB password:
Retype new SMB password:
Added user samba-user.
```
使新账户`samba-user`对共享目录有读写和可执行权限
```bash
sudo setfacl -R -m "u:samba-user:rwx" ~/Workspace/sambashare
```

## 重启 samba 服务
```bash
sudo systemctl restart smbd
```

# 客户端访问共享资源
## Windows 客户端
在“资源管理器”中输入`\\servername\sharename`来访问`samba`服务上名为`sharename`的共享资源，
其中，`servername`是`samba`服务器的主机名或`IP`地址

## Linux 客户端
使用`smbclient`命令来访问`samba`服务器上的共享资源，例如
```bash
smbclient //servername/sharename
```
如果没有`smbclient`程序，需要安装
```bash
sudo apt-get update & sudo apt-get install smbclient
```

## macOS 客户端
在“访达”中选择“前往”>“连接服务器”，然后输入`smb://servername/sharename`来访问`samba`服务器上
的共享资源

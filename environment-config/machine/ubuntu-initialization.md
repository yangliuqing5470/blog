# 机器初始化

## 安装 vim
```bash
sudo apt-get update
sudo apt-get install vim
```
## 更换软件更新源
将 `/etc/apt/sources.list` 文件备份
```bash
sudo mv /etc/apt/sources.list /etc/apt/sources.list.backup
```
将清华源写入到文件 `/etc/apt/sources.list` 中
```bash
清华源:
deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ jammy main restricted universe multiverse
# deb-src https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ jammy main restricted universe multiverse
deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ jammy-updates main restricted universe multiverse
# deb-src https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ jammy-updates main restricted universe multiverse
deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ jammy-backports main restricted universe multiverse
# deb-src https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ jammy-backports main restricted universe multiverse
deb https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ jammy-security main restricted universe multiverse
# deb-src https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ jammy-security main restricted universe multiverse
```
执行更新命令
```bash
sudo apt-get update && sudo apt-get upgrade
```
## 安装开发基础软件
```bash
sudo apt-get update
# git
sudo apt-get install git
# gcc, g++, make
sudo apt-get install build-essential
# curl
sudo apt-get install curl
# node
sudo apt-get install nodejs
# npm
sudo apt-get install npm
```

## 安装 terminator 终端
```bash
sudo apt-get update && sudo apt-get install terminator
```
### 安装 JetBrainsMono 字体
将下载的字体解压放到 `/usr/share/fonts` 下，然后执行 `fc-cache -f -v`
```bash
sudo unzip JetBrainsMono-2.304.zip -d /usr/share/fonts/
fc-cache -f -v
```
### 安装 Nerd Fonts 字体
```bash
sudo unzip JetBrainsMono.zip -d /usr/share/fonts/
fc-cache -f -v
```

### 配置终端
主题，字体等

## 安装 neovim
[配置neovim环境](https://github.com/yangliuqing5470/neovim-config)

# 📦 如何手动部署MaiMbot麦麦？

## 你需要什么？

- 一台电脑，能够上网的那种

- 一个QQ小号（QQ框架的使用可能导致qq被风控，严重（小概率）可能会导致账号封禁，强烈不推荐使用大号）

- 可用的大模型API

- 一个AI助手，网上随便搜一家打开来用都行，可以帮你解决一些不懂的问题

## 你需要知道什么？

- 如何正确向AI助手提问，来学习新知识

- Python是什么

- Python的虚拟环境是什么？如何创建虚拟环境

- 命令行是什么

- 数据库是什么？如何安装并启动MongoDB

- 如何运行一个QQ机器人，以及NapCat框架是什么

## 如果准备好了，就可以开始部署了

### 1️⃣ **我们需要创建一个Python环境来运行程序**

    你可以选择使用以下两种方法之一来创建Python环境：

```bash
# ---方法1：使用venv（Python自带）
# 在命令行中创建虚拟环境（环境名为maimbot）
# 这会让你在运行命令的目录下创建一个虚拟环境
# 请确保你已通过cd命令前往到了对应路径，不然之后你可能找不到你的python环境
python -m venv maimbot

maimbot\\Scripts\\activate 

# 安装依赖
pip install -r requirements.txt
```
```bash
# ---方法2：使用conda
# 创建一个新的conda环境（环境名为maimbot）
# Python版本为3.9
conda create -n maimbot python=3.9

# 激活环境
conda activate maimbot

# 安装依赖
pip install -r requirements.txt
```

### 2️⃣ **然后你需要启动MongoDB数据库，来存储信息**
- 安装并启动MongoDB服务
- 默认连接本地27017端口

### 3️⃣ **配置NapCat，让麦麦bot与qq取得联系**
- 安装并登录NapCat（用你的qq小号）
- 添加反向WS：`ws://localhost:8080/onebot/v11/ws`

### 4️⃣ **配置文件设置，让麦麦Bot正常工作**
- 修改环境配置文件：`.env.prod`
- 修改机器人配置文件：`bot_config.toml`

### 5️⃣ **启动麦麦机器人**
- 打开命令行，cd到对应路径
```bash
nb run
```
- 或者cd到对应路径后
```bash
python bot.py
```

### 6️⃣ **其他组件(可选)**
- `run_thingking.bat`: 启动可视化推理界面（未完善）
- 直接运行 knowledge.py生成知识库

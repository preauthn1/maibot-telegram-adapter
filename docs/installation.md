# 🔧 安装与配置指南

## 部署方式

**如果你不知道Docker是什么，建议寻找相关教程或使用手动部署**

### 🐳 Docker部署（推荐，但不一定是最新）

1. 获取配置文件：
```bash
wget https://raw.githubusercontent.com/SengokuCola/MaiMBot/main/docker-compose.yml
```

2. 启动服务：
```bash
NAPCAT_UID=$(id -u) NAPCAT_GID=$(id -g) docker compose up -d
```

3. 修改配置后重启：
```bash
NAPCAT_UID=$(id -u) NAPCAT_GID=$(id -g) docker compose restart
```

### 📦 手动部署

([这里](https://www.bilibili.com/opus/1041609335464001545)有一份由社区大佬编写的，适用于Windows的部署教程，可供参考)

1. **环境准备**
先参考图片，下载Releases中的`Source code(zip)`并将其解压到一个文件夹里(**路径不要有中文**)

2. **安装Python**

要求Python 3.9+

Linux用户可在终端输入`python3 --version`确认Python版本，Windows用户可在命令行输入`python --version`确认Python版本

Windows用户需要安装[Python](https://www.python.org/downloads/windows/)并在安装时勾选“Add Python to PATH”选项（如访问速度慢，[这里](https://www.123912.com/s/ydQuVv-TMKBd)提供Python 3.12的安装包网盘链接）

Linux由于不同发行版安装Python的方式不同，请自行查阅相关教程(问AI、用搜索引擎搜一下都行)

```bash
# 创建虚拟环境（推荐）
# 在机器人的目录内打开终端/命令行，执行
python -m venv venv

# 激活虚拟环境
venv\\Scripts\\activate   # Windows
source venv/bin/activate  # Linux

# 安装依赖
pip install -r requirements.txt
```

3. **配置MongoDB**
- 安装并启动MongoDB服务
  - 参考[MongoDB官方文档](https://www.mongodb.com/zh-cn/docs/manual/administration/install-community/#std-label-install-mdb-community-edition)
  - 建议使其开机自启（教程中有提及，称为“在系统重新启动后启动”）
- 默认连接本地27017端口

4. **配置NapCat**
- 安装并登录NapCat
  - 参考[NapCat官方文档](https://www.napcat.wiki/guide/install)
- 添加反向WS：`ws://localhost:8080/onebot/v11/ws`
*该项目基于 nonebot2 框架开发，理论上也支持对接其他平台，如有需求请自行寻找教程*

5. **首次启动麦麦机器人**
```bash
# 在机器人的目录内打开终端/命令行，执行
nb run
```
程序会创建基本配置文件，然后退出

6. **配置文件设置**
参照“配置说明”一节进行配置
- 修改环境配置文件：`.env.prod`(位于机器人文件夹根目录)
- 修改机器人配置文件：`config/bot_config.toml`(位于机器人文件夹根目录/config文件夹内)

7. **启动麦麦机器人**
- 打开命令行，cd到对应路径
```bash
nb run
```

6. **其他组件**
- `run_thingking.bat`: 启动可视化推理界面（未完善）

- ~~`knowledge.bat`: 将`/data/raw_info`下的文本文档载入数据库~~
- 直接运行 knowledge.py生成知识库

## ⚙️ 配置说明

### 环境配置 (.env.prod)
```ini
HOST=127.0.0.1
PORT=8080   # 端口号，有需求可改

# 插件配置
PLUGINS=["src2.plugins.chat"]

# 数据库配置
MONGODB_HOST=127.0.0.1
MONGODB_PORT=27017
DATABASE_NAME=MegBot

MONGODB_USERNAME = ""  # 默认空值
MONGODB_PASSWORD = ""  # 默认空值
MONGODB_AUTH_SOURCE = ""  # 默认空值

# 以上内容如看不懂，保持默认即可

# 以下为API配置,你可以在这里定义你的密钥和base_url
# 你可以选择定义其他服务商提供的KEY，完全可以自定义

#key and url
# 定义你要用的api的base_url
CHAT_ANY_WHERE_BASE_URL=https://api.chatanywhere.tech/v1
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1/
DEEP_SEEK_BASE_URL=https://api.deepseek.com/v1
# 你也可以自定义所需平台的base_url
# 举例：
# MODEL_NAME_BASE_URL=https://api.example.com/v1


#定义你要用的api的API-KEY
DEEP_SEEK_KEY=
CHAT_ANY_WHERE_KEY=
SILICONFLOW_KEY=
# 你也可以自定义所需平台的API-KEY
# 举例：
# MODEL_NAME_KEY=

```



### 机器人配置 (bot_config.toml)
```toml
[bot]
qq = 123
nickname = "麦麦"   # 可自定义

[personality]
prompt_personality = [
        
    ]
prompt_schedule = 

[message]
min_text_length = 2 # 与麦麦聊天时麦麦只会回答文本大于等于此数的消息
max_context_size = 15 # 麦麦获得的上文数量
emoji_chance = 0.2 # 麦麦使用表情包的概率
ban_words = [
    # "403","张三"
    ]

[emoji]
check_interval = 120 # 检查表情包的时间间隔
register_interval = 10 # 注册表情包的时间间隔

[cq_code]
enable_pic_translate = false

[response]
model_r1_probability = 0.8 # 麦麦回答时选择R1模型(即[model.llm_reasoning]指定的模型)的概率
model_v3_probability = 0.1 # 麦麦回答时选择V3模型(即[model.llm_normal]指定的模型)的概率
model_r1_distill_probability = 0.1 # 麦麦回答时选择R1蒸馏模型(即[model.llm_reasoning_minor]指定的模型)的概率

[memory]
build_memory_interval = 300 # 记忆构建间隔 单位秒
forget_memory_interval = 300 # 记忆遗忘间隔 单位秒

[others]
enable_advance_output = true # 是否启用高级输出
enable_kuuki_read = true # 是否启用读空气功能

[groups]
talk_allowed = [
    123,
    123,
]  #可以回复消息的群
talk_frequency_down = []  #降低回复频率的群
ban_user_id = []  #禁止回复消息的QQ号


#V3
#name = "deepseek-chat"
#base_url = "DEEP_SEEK_BASE_URL"
#key = "DEEP_SEEK_KEY"

#R1
#name = "deepseek-reasoner"
#base_url = "DEEP_SEEK_BASE_URL"
#key = "DEEP_SEEK_KEY"

#下面的模型若使用硅基流动则不需要更改，使用ds官方则改成.env.prod自定义的宏，使用自定义模型则选择定位相似的模型自己填写

[model.llm_reasoning] #R1
name = "Pro/deepseek-ai/DeepSeek-R1"
base_url = "SILICONFLOW_BASE_URL"
key = "SILICONFLOW_KEY"

[model.llm_reasoning_minor] #R1蒸馏
name = "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B"
base_url = "SILICONFLOW_BASE_URL"
key = "SILICONFLOW_KEY"

[model.llm_normal] #V3
name = "Pro/deepseek-ai/DeepSeek-V3"
base_url = "SILICONFLOW_BASE_URL"
key = "SILICONFLOW_KEY"

[model.llm_normal_minor] #V2.5
name = "deepseek-ai/DeepSeek-V2.5"
base_url = "SILICONFLOW_BASE_URL"
key = "SILICONFLOW_KEY"

[model.vlm] #图像识别
name = "deepseek-ai/deepseek-vl2"
base_url = "SILICONFLOW_BASE_URL"
key = "SILICONFLOW_KEY"

[model.embedding] #嵌入
name = "BAAI/bge-m3"
base_url = "SILICONFLOW_BASE_URL"
key = "SILICONFLOW_KEY"

# 主题提取，jieba和snownlp不用api，llm需要api
[topic]
topic_extract='snownlp' # 只支持jieba,snownlp,llm三种选项

[topic.llm_topic]
name = "Pro/deepseek-ai/DeepSeek-V3"
base_url = "SILICONFLOW_BASE_URL"
key = "SILICONFLOW_KEY"

```

## ⚠️ 注意事项

- 目前部署方案仍在测试中，可能存在未知问题
- 配置文件中的API密钥请妥善保管，不要泄露，如需截图描述问题，请将截图中的API密钥打码(它们通常以`sk-`开头)
- 建议先在测试环境中运行，确认无误后再部署到生产环境 

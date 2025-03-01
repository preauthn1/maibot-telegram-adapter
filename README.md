# 麦麦！MaiMBot (编辑中) 


<div align="center">


![Python Version](https://img.shields.io/badge/Python-3.8-blue)
![License](https://img.shields.io/github/license/SengokuCola/MaiMBot)
![Status](https://img.shields.io/badge/状态-开发中-yellow)

</div>

## 📝 项目简介

**麦麦qq机器人的源代码仓库**

基于llm、napcat、nonebot和mongodb的专注于群聊天的qqbot

> ⚠️ **警告**：代码可能随时更改，目前版本不一定是稳定版本
> ⚠️ **警告**：请自行了解qqbot的风险，麦麦有时候一天被腾讯肘七八次
> ⚠️ **警告**：由于麦麦一直在迭代，所以可能存在一些bug，请自行测试，包括胡言乱语（

关于麦麦的开发和部署相关的讨论群（不建议发布无关消息）这里不会有麦麦发言！

## 开发计划TODO：LIST

- 兼容gif的解析和保存
- 小程序转发链接解析
- 对思考链长度限制
- 修复已知bug
- 完善文档


<div align="center">
<img src="docs/qq.png" width="300" />
</div>

## 📚 详细文档
- [项目详细介绍和架构说明](docs/doc1.md) - 包含完整的项目结构、文件说明和核心功能实现细节(由claude-3.5-sonnet生成)

### 安装方法（还没测试好，现在部署可能遇到未知问题！！！！）

#### Linux 使用 Docker Compose 部署
获取项目根目录中的```docker-compose.yml```文件，运行以下命令
```bash
NAPCAT_UID=$(id -u) NAPCAT_GID=$(id -g) docker compose up -d
```
配置文件修改完成后，运行以下命令
```bash
NAPCAT_UID=$(id -u) NAPCAT_GID=$(id -g) docker compose restart
```

#### 手动运行
1. **创建Python环境**
   推荐使用conda或其他环境管理来管理你的python环境
   ```bash
   # 安装requirements（还没检查好，可能有包漏了）
   conda activate 你的环境
   cd 对应路径
   pip install -r requirements.txt
   ```
2. **MongoDB设置**
   - 安装并运行mongodb
   - 麦麦bot会自动连接默认的mongodb，端口和数据库名可配置

3. **Napcat配置**
   - 安装并运行Napcat，登录
   - 在Napcat的网络设置中添加ws反向代理:ws://localhost:8080/onebot/v11/ws

4. **配置文件设置**
   - 把env.example改成.env，并填上你的apikey（硅基流动或deepseekapi）
   - 把bot_config_toml改名为bot_config.toml，并填写相关内容，不然无法正常运行

   #### .env 文件配置说明
   ```ini
   # 环境配置
   ENVIRONMENT=dev          # 开发环境设置
   HOST=127.0.0.1          # 主机地址
   PORT=8080               # 端口号

   # 命令前缀设置
   COMMAND_START=["/"]     # 命令起始符

   # 插件配置
   PLUGINS=["src2.plugins.chat"]  # 启用的插件列表

   # MongoDB配置
   MONGODB_HOST=127.0.0.1        # MongoDB主机地址
   MONGODB_PORT=27017            # MongoDB端口
   DATABASE_NAME=MegBot          # 数据库名称
   MONGODB_USERNAME=""           # MongoDB用户名（可选）
   MONGODB_PASSWORD=""           # MongoDB密码（可选）
   MONGODB_AUTH_SOURCE=""        # MongoDB认证源（可选）

   # API密钥配置
   CHAT_ANY_WHERE_KEY=           # ChatAnyWhere API密钥
   SILICONFLOW_KEY=             # 硅基流动 API密钥（必填）
   DEEP_SEEK_KEY=               # DeepSeek API密钥（必填）

   # API地址配置
   CHAT_ANY_WHERE_BASE_URL=https://api.chatanywhere.tech/v1
   SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1/
   DEEP_SEEK_BASE_URL=https://api.deepseek.com/v1
   ```

   #### bot_config.toml 文件配置说明
   ```toml
   # 数据库设置
   [database]
   host = "127.0.0.1"      # MongoDB主机地址
   port = 27017            # MongoDB端口
   name = "MegBot"         # 数据库名称

   # 机器人基本设置
   [bot]
   qq =                    # 你的机器人QQ号（必填）
   nickname = "麦麦"       # 机器人昵称

   # 消息处理设置
   [message]
   min_text_length = 2     # 最小响应文本长度
   max_context_size = 15   # 上下文最大保存数量
   emoji_chance = 0.2      # 表情包使用概率

   # 表情包功能设置
   [emoji]
   check_interval = 120    # 表情检查间隔（秒）
   register_interval = 10  # 表情注册间隔（秒）

   # CQ码设置
   [cq_code]
   enable_pic_translate = false  # 是否启用图片转换（无效）

   # 响应设置
   [response]
   api_using = "siliconflow"     # 回复使用的API（siliconflow/deepseek）
   model_r1_probability = 0.8    # R1模型使用概率
   model_v3_probability = 0.1    # V3模型使用概率
   model_r1_distill_probability = 0.1  # R1蒸馏模型使用概率（对deepseek api 无效）

   # 其他设置
   [others]
   enable_advance_output = false  # 是否启用详细日志输出

   # 群组设置
   [groups]
   talk_allowed = [              # 允许回复的群号列表
       # 在这里添加群号,逗号隔开
   ]
   
   talk_frequency_down = [       # 降低回复频率的群号列表
       # 在这里添加群号,逗号隔开
   ]
   
   ban_user_id = [              # 禁止回复的用户QQ号列表
       # 在这里添加QQ号,逗号隔开
   ]
   ```

5. **运行麦麦**
   ```bash
   conda activate 你的环境
   cd 对应路径
   nb run
   ```
6. **运行其他组件**
   run_thingking.bat 可以启动可视化的推理界面（未完善）和消息队列及其他信息预览（WIP）
   knowledge.bat可以将/data/raw_info下的文本文档载入到数据库（未启动）

## 🎯 功能介绍

### 💬 聊天功能
- 支持关键词检索主动发言：对消息的话题topic进行识别，如果检测到麦麦存储过的话题就会主动进行发言，目前有bug,所以现在只会检测主题，不会进行存储
- 支持bot名字呼唤发言：检测到"麦麦"会主动发言，可配置
- 使用硅基流动的api进行回复生成，可随机使用R1，V3，R1-distill等模型，未来将加入官网api支持
- 动态的prompt构建器，更拟人
- 支持图片，转发消息，回复消息的识别
- 错别字和多条回复功能：麦麦可以随机生成错别字，会多条发送回复以及对消息进行reply

### 😊 表情包功能
- 支持根据发言内容发送对应情绪的表情包：未完善，可以用
- 会自动偷群友的表情包（未完善，暂时禁用）目前有bug

### 📅 日程功能
- 麦麦会自动生成一天的日程，实现更拟人的回复

### 🧠 记忆功能
- 对聊天记录进行概括存储，在需要时调用，没写完

### 📚 知识库功能
- 基于embedding模型的知识库，手动放入txt会自动识别，写完了，暂时禁用

### 👥 关系功能
- 针对每个用户创建"关系"，可以对不同用户进行个性化回复，目前只有极其简单的好感度（WIP）
- 针对每个群创建"群印象"，可以对不同群进行个性化回复（WIP）

## 🚧 开发中功能
- 人格功能：WIP
- 群氛围功能：WIP
- 图片发送，转发功能：WIP
- 幽默和meme功能：WIP的WIP
- 让麦麦玩mc：WIP的WIP的WIP

## 📌 注意事项
纯编程外行，面向cursor编程，很多代码史一样多多包涵

> ⚠️ **警告**：本应用生成内容来自人工智能模型，由 AI 生成，请仔细甄别，请勿用于违反法律的用途，AI生成内容不代表本人观点和立场。

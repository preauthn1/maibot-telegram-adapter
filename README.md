# MaiMBot (WIPWIPWIPWIP) 🤖


<div align="center">

![Python Version](https://img.shields.io/badge/Python-3.x-blue)
<!-- ![License](https://img.shields.io/badge/license-MIT-green) -->
![Status](https://img.shields.io/badge/状态-开发中-yellow)

</div>

## 📝 项目简介

**麦麦qq机器人的源代码仓库**

基于llm、napcat、nonebot和mongodb的专注于群聊天的qqbot

> ⚠️ **警告**：代码可能随时更改，目前版本不一定是稳定版本
⚠️ **警告**：请自行了解qqbot的风险，麦麦有时候一天被腾讯肘七八次
> ⚠️ **警告**：由于麦麦一直在迭代，所以可能存在一些bug，请自行测试，包括胡言乱语（

## 🚀 快速开始

### 安装方法（还没测试好，现在部署可能遇到未知问题！！！！！！）

1. **创建Python环境**
   ```bash
   # 安装requirements（还没检查好，可能有包漏了）
   pip install -r requirements.txt
   ```

2. **MongoDB设置**
   - 安装并运行mongodb
   - 麦麦bot会自动连接默认的mongodb，可配置

3. **Napcat配置**
   - 安装并运行Napcat
   - 设置ws反向代理:ws://localhost:8080/onebot/v11/ws，启动

4. **配置文件设置**
   - 把env.example改成.env，并填上你的apikey（硅基流动或deepseekapi）
   - 把bot_config_toml改名为bot_config.toml，并填写相关内容

5. **运行麦麦**
      从 run_maimai.bat 启动
      run_thingking.bat 可以启动可视化的推理界面

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

## 🤝 参与贡献
欢迎提交 Issue 和 Pull Request！

> ⚠️ **警告**：本应用生成内容来自人工智能模型，由 AI 生成，请仔细甄别，请勿用于违反法律的用途，AI生成内容不代表本人观点和立场。
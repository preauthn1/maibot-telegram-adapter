# 麦麦！MaiMBot (编辑中) 


<div align="center">

![Python Version](https://img.shields.io/badge/Python-3.x-blue)
![License](https://img.shields.io/github/license/SengokuCola/MaiMBot)
![Status](https://img.shields.io/badge/状态-开发中-yellow)

</div>

## 📝 项目简介

**麦麦是一个基于大语言模型的智能QQ群聊机器人**

- 🤖 基于 nonebot2 框架开发
- 🧠 LLM 提供对话能力
- 💾 MongoDB 提供数据持久化支持
- 🌐 NapCat 作为QQ协议端支持

<div align="center">
<a href="https://www.bilibili.com/video/BV1amAneGE3P" target="_blank">
    <img src="docs/video.png" width="300" alt="麦麦演示视频">
    <br>
    👆 点击观看麦麦演示视频 👆
</a>
</div>

> ⚠️ **注意事项**
> - 项目处于活跃开发阶段，代码可能随时更改
> - 文档未完善，有问题可以提交 Issue 或者 Discussion
> - QQ机器人存在被限制风险，请自行了解，谨慎使用
> - 由于持续迭代，可能存在一些已知或未知的bug

**交流群**: 123456780（仅用于开发和建议相关讨论）

## 📚 文档

- [安装与配置指南](docs/installation.md) - 详细的部署和配置说明
- [项目架构说明](docs/doc1.md) - 项目结构和核心功能实现细节

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

## 开发计划TODO：LIST

- 兼容gif的解析和保存
- 小程序转发链接解析
- 对思考链长度限制
- 修复已知bug
- 完善文档
- 修复转发
- config自动生成和检测
- log别用print
- 给发送消息写专门的类
- 改进表情包发送逻辑

## 📌 注意事项
纯编程外行，面向cursor编程，很多代码史一样多多包涵

> ⚠️ **警告**：本应用生成内容来自人工智能模型，由 AI 生成，请仔细甄别，请勿用于违反法律的用途，AI生成内容不代表本人观点和立场。

## 致谢
[nonebot2](https://github.com/nonebot/nonebot2): 跨平台 Python 异步聊天机器人框架  
[NapCat](https://github.com/NapNeko/NapCatQQ): 现代化的基于 NTQQ 的 Bot 协议端实现  

### 贡献者

感谢各位大佬！

[![Contributors](https://contributors-img.web.app/image?repo=SengokuCola/MaiMBot)](https://github.com/SengokuCola/MaiMBot/graphs/contributors)

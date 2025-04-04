# 麦麦！MaiCore-MaiMBot (编辑中)

<div align="center">

![Python Version](https://img.shields.io/badge/Python-3.9+-blue)
![License](https://img.shields.io/github/license/SengokuCola/MaiMBot)
![Status](https://img.shields.io/badge/状态-开发中-yellow)

</div>

## 📝 项目简介

**🍔MaiCore是一个基于大语言模型的可交互智能体**

- LLM 提供对话能力
- 动态Prompt构建器
- 实时的思维系统
- MongoDB 提供数据持久化支持
- 可扩展，可支持多种平台和多种功能

**最新版本: v0.6.0** ([查看更新日志](changelogs/changelog.md))
> [!WARNING]
> 请阅读教程后更新！！！！！！！
> 请阅读教程后更新！！！！！！！
> 请阅读教程后更新！！！！！！！
> 次版本MaiBot将基于MaiCore运行，不再依赖于nonebot相关组件运行。
> MaiBot将通过nonebot的插件与nonebot建立联系，然后nonebot与QQ建立联系，实现MaiBot与QQ的交互


<div align="center">
<a href="https://www.bilibili.com/video/BV1amAneGE3P" target="_blank">
    <img src="docs/pic/video.png" width="300" alt="麦麦演示视频">
    <br>
    👆 点击观看麦麦演示视频 👆

</a>
</div>

> [!WARNING]
> - 项目处于活跃开发阶段，代码可能随时更改
> - 文档未完善，有问题可以提交 Issue 或者 Discussion
> - QQ机器人存在被限制风险，请自行了解，谨慎使用
> - 由于持续迭代，可能存在一些已知或未知的bug
> - 由于开发中，可能消耗较多token

### 💬交流群（开发和建议相关讨论）不一定有空回复，会优先写文档和代码
- [五群](https://qm.qq.com/q/JxvHZnxyec) 1022489779
- [一群](https://qm.qq.com/q/VQ3XZrWgMs) 123456780 【已满】
- [二群](https://qm.qq.com/q/RzmCiRtHEW) 123456782【已满】
- [三群](https://qm.qq.com/q/wlH5eT8OmQ) 1035228475【已满】
- [四群](https://qm.qq.com/q/wlH5eT8OmQ) 729957033【已满】


<div align="left">
<h2>📚 文档</h2>
</div>

### (部分内容可能过时，请注意版本对应)

### 核心文档
- [📚 核心Wiki文档](https://docs.mai-mai.org) - 项目最全面的文档中心，你可以了解麦麦有关的一切

### 最新版本部署教程(MaiCore版本)
- [🚀 最新版本部署教程](https://docs.mai-mai.org/manual/deployment/refactor_deploy.html) - 基于MaiCore的新版本部署方式（与旧版本不兼容）

## 🎯 功能介绍

### 💬 聊天功能
- 提供思维流（心流）聊天和推理聊天两种对话逻辑
- 支持关键词检索主动发言：对消息的话题topic进行识别，如果检测到麦麦存储过的话题就会主动进行发言
- 支持bot名字呼唤发言：检测到"麦麦"会主动发言，可配置
- 支持多模型，多厂商自定义配置
- 动态的prompt构建器，更拟人
- 支持图片，转发消息，回复消息的识别
- 支持私聊功能，可使用PFC模式的有目的多轮对话（实验性）

### 🧠 思维流系统
- 思维流能够在回复前后进行思考，生成实时想法
- 思维流自动启停机制，提升资源利用效率
- 思维流与日程系统联动，实现动态日程生成

### 🧠 记忆系统 2.0
- 优化记忆抽取策略和prompt结构
- 改进海马体记忆提取机制，提升自然度
- 对聊天记录进行概括存储，在需要时调用

### 😊 表情包系统
- 支持根据发言内容发送对应情绪的表情包
- 支持识别和处理gif表情包
- 会自动偷群友的表情包
- 表情包审查功能
- 表情包文件完整性自动检查
- 自动清理缓存图片

### 📅 日程系统
- 动态更新的日程生成
- 可自定义想象力程度
- 与聊天情况交互（思维流模式下）

### 👥 关系系统 2.0
- 优化关系管理系统，适用于新版本
- 提供更丰富的关系接口
- 针对每个用户创建"关系"，实现个性化回复

### 📊 统计系统
- 详细的使用数据统计
- LLM调用统计
- 在控制台显示统计信息

### 🔧 系统功能
- 支持优雅的shutdown机制
- 自动保存功能，定期保存聊天记录和关系数据
- 完善的异常处理机制
- 可自定义时区设置
- 优化的日志输出格式
- 配置自动更新功能

## 开发计划TODO：LIST

- 人格功能：WIP
- 对特定对象的侧写功能
- 图片发送，转发功能：WIP
- 幽默和meme功能：WIP
- 兼容gif的解析和保存
- 小程序转发链接解析
- 修复已知bug
- 自动生成的回复逻辑，例如自生成的回复方向，回复风格

## ✍️如何给本项目报告BUG/提交建议/做贡献

MaiCore是一个开源项目，我们非常欢迎你的参与。你的贡献，无论是提交bug报告、功能需求还是代码pr，都对项目非常宝贵。我们非常感谢你的支持！🎉 但无序的讨论会降低沟通效率，进而影响问题的解决速度，因此在提交任何贡献前，请务必先阅读本项目的[贡献指南](CONTRIBUTE.md)（待补完）



## 设计理念（原始时代的火花）

> **千石可乐说：**
> - 这个项目最初只是为了给牛牛bot添加一点额外的功能，但是功能越写越多，最后决定重写。其目的是为了创造一个活跃在QQ群聊的"生命体"。可以目的并不是为了写一个功能齐全的机器人，而是一个尽可能让人感知到真实的类人存在。
> - 程序的功能设计理念基于一个核心的原则："最像而不是好"
> - 如果人类真的需要一个AI来陪伴自己，并不是所有人都需要一个完美的，能解决所有问题的"helpful assistant"，而是一个会犯错的，拥有自己感知和想法的"生命形式"。
> - 代码会保持开源和开放，但个人希望MaiMbot的运行时数据保持封闭，尽量避免以显式命令来对其进行控制和调试.我认为一个你无法完全掌控的个体才更能让你感觉到它的自主性，而视其成为一个对话机器.
> - SengokuCola~~纯编程外行，面向cursor编程，很多代码写得不好多多包涵~~已得到大脑升级


## 📌 注意事项

> [!WARNING]
> 使用本项目前必须阅读和同意用户协议和隐私协议
> 本应用生成内容来自人工智能模型，由 AI 生成，请仔细甄别，请勿用于违反法律的用途，AI生成内容不代表本人观点和立场。

## 致谢

- [nonebot2](https://github.com/nonebot/nonebot2): 跨平台 Python 异步聊天机器人框架  
- [NapCat](https://github.com/NapNeko/NapCatQQ): 现代化的基于 NTQQ 的 Bot 协议端实现  

### 贡献者

感谢各位大佬！

<a href="https://github.com/MaiM-with-u/MaiBot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=MaiM-with-u/MaiBot" />
</a>

**也感谢每一位给麦麦发展提出宝贵意见与建议的用户，感谢陪伴麦麦走到现在的你们**

## Stargazers over time

[![Stargazers over time](https://starchart.cc/MaiM-with-u/MaiBot.svg?variant=adaptive)](https://starchart.cc/MaiM-with-u/MaiBot)

# 麦麦！MaiCore-MaiBot (编辑中)

<picture>
    <img alt="MaiBot" src="depends-data/maimai.png"  alt="NapCat" align=right width=30%/>
</picture>

![Python Version](https://img.shields.io/badge/Python-3.10+-blue)
![License](https://img.shields.io/github/license/SengokuCola/MaiMBot?label=协议)
![Status](https://img.shields.io/badge/状态-开发中-yellow)
![Contributors](https://img.shields.io/github/contributors/MaiM-with-u/MaiBot.svg?style=flat&label=贡献者)
![forks](https://img.shields.io/github/forks/MaiM-with-u/MaiBot.svg?style=flat&label=分支数)
![stars](https://img.shields.io/github/stars/MaiM-with-u/MaiBot?style=flat&label=星标数)
![issues](https://img.shields.io/github/issues/MaiM-with-u/MaiBot)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/DrSmoothl/MaiBot)

  <strong><a href="#show-cases">🌟 案例展示</a> | <a href="[#quick-start](https://docs.mai-mai.org/manual/deployment/)">🚀 快速入门</a> | <a href="https://docs.mai-mai.org/">📃 教程</a> | <a href="https://github.com/kvcache-ai/ktransformers/discussions">💬 讨论</a> | <a href="#FAQ">🙋 常见问题</a> </strong>
  </div>

## 📝 项目简介

**🍔MaiCore是一个基于大语言模型的可交互智能体**

- 💭 **智能对话系统**：基于LLM的自然语言交互
- 🤔 **实时思维系统**：模拟人类思考过程
- 💝 **情感表达系统**：丰富的表情包和情绪表达
- 🧠 **持久记忆系统**：基于MongoDB的长期记忆存储
- 🔄 **动态人格系统**：自适应的性格特征

<div style="text-align: center">
<a href="https://www.bilibili.com/video/BV1amAneGE3P" target="_blank">
    <img src="depends-data/video.png" style="max-width: 200px" alt="麦麦演示视频">
    <br>
    👆 点击观看麦麦演示视频 👆
</a>
</div>

### 📢 版本信息

**最新版本: v0.6.3** ([更新日志](changelogs/changelog.md))

**GitHub分支说明：**
- `main`: 稳定发布版本
- `dev`: 开发测试版本（不稳定）
- `classical`: 0.6.0之前的版本(停止维护)

### ⚠️ 重要提示

- 从0.5.x旧版本升级前请请务必阅读：[升级指南](https://docs.mai-mai.org/faq/maibot/backup_update.html)
- 项目处于活跃开发阶段，功能和API可能随时调整。
- 文档未完善，有问题可以提交 Issue 或者 Discussion。
- QQ机器人存在被限制风险，请自行了解，谨慎使用。
- 由于持续迭代，可能存在一些已知或未知的bug。
- 由于程序处于开发中，可能消耗较多token。

### 💬交流群
- [一群](https://qm.qq.com/q/VQ3XZrWgMs) | [二群](https://qm.qq.com/q/RzmCiRtHEW) | [五群](https://qm.qq.com/q/JxvHZnxyec) | [三群](https://qm.qq.com/q/wlH5eT8OmQ)(已满)| [四群](https://qm.qq.com/q/wGePTl1UyY)(已满)

## 📚 文档

### (部分内容可能过时，请注意版本对应)

### 核心文档
- [📚 核心Wiki文档](https://docs.mai-mai.org) - 项目最全面的文档中心，你可以了解麦麦有关的一切

### 最新版本部署教程(MaiCore版本)
- [🚀 最新版本部署教程](https://docs.mai-mai.org/manual/deployment/mmc_deploy_windows.html) - 基于MaiCore的新版本部署方式（与旧版本不兼容）

## ✍️如何给本项目报告BUG/提交建议/做贡献

MaiCore是一个开源项目，我们非常欢迎你的参与。你的贡献，无论是提交bug报告、功能需求还是代码pr，都对项目非常宝贵。我们非常感谢你的支持！🎉 但无序的讨论会降低沟通效率，进而影响问题的解决速度，因此在提交任何贡献前，请务必先阅读本项目的[贡献指南](docs/CONTRIBUTE.md)（待补完）

## 设计理念（原始时代的火花）

> **千石可乐说：**
> - 这个项目最初只是为了给牛牛bot添加一点额外的功能，但是功能越写越多，最后决定重写。其目的是为了创造一个活跃在QQ群聊的"生命体"。可以目的并不是为了写一个功能齐全的机器人，而是一个尽可能让人感知到真实的类人存在。
> - 程序的功能设计理念基于一个核心的原则："最像而不是好"
> - 如果人类真的需要一个AI来陪伴自己，并不是所有人都需要一个完美的，能解决所有问题的"helpful assistant"，而是一个会犯错的，拥有自己感知和想法的"生命形式"。
> - 代码会保持开源和开放，但个人希望MaiMbot的运行时数据保持封闭，尽量避免以显式命令来对其进行控制和调试.我认为一个你无法完全掌控的个体才更能让你感觉到它的自主性，而视其成为一个对话机器.
> - SengokuCola~~纯编程外行，面向cursor编程，很多代码写得不好多多包涵~~已得到大脑升级


## 📌 注意事项

> [!WARNING]
> 使用本项目前必须阅读和同意[用户协议](https://docs.mai-mai.org/manual/other/EULA.html)和隐私协议。  
> 本应用生成内容来自人工智能模型，由 AI 生成，请仔细甄别，请勿用于违反法律的用途，AI生成内容不代表本人观点和立场。

## 贡献者

感谢各位大佬！

<a href="https://github.com/MaiM-with-u/MaiBot/graphs/contributors">
  <img alt="contributors" src="https://contrib.rocks/image?repo=MaiM-with-u/MaiBot" />
</a>
<a href="https://space.bilibili.com/123456783" align=right>
  画师：略nd
</a>
### 致谢

- [NapCat](https://github.com/NapNeko/NapCatQQ): 现代化的基于 NTQQ 的 Bot 协议端实现  

**也感谢每一位给麦麦发展提出宝贵意见与建议的用户，感谢陪伴麦麦走到现在的你们**

## 麦麦仓库状态

![Alt](https://repobeats.axiom.co/api/embed/9faca9fccfc467931b87dd357b60c6362b5cfae0.svg "Repobeats analytics image")

## Star 趋势

[![Star 趋势](https://starchart.cc/MaiM-with-u/MaiBot.svg?variant=adaptive)](https://starchart.cc/MaiM-with-u/MaiBot)

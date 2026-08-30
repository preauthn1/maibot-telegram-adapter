# Telegram 真人账号适配器

用**真实 Telegram 个人账号**（MTProto / Telethon）而不是 Bot 账号收发消息。
对方看到的是一个普通用户，没有 BOT 标记，也不受 Bot API 的诸多限制。

## 与官方 Bot API 适配器的区别

| | Bot API 适配器 | 本插件（真人账号） |
|---|---|---|
| 身份 | 带 BOT 标记 | 普通用户，无标记 |
| 协议 | HTTPS 长轮询 | MTProto 长连接 |
| 登录 | BotFather Token | 手机号 + 验证码 |
| 群里读消息 | 需关闭隐私模式或被 @ | 默认能读全部消息 |
| 主动私聊陌生人 | 不行（对方必须先 /start） | 可以 |
| 已读回执 / 正在输入 | 受限 | 完整支持 |
| 封号风险 | 低 | **有**，需控制频率 |

## 安装

1. 安装依赖：

   ```bash
   uv pip install telethon cryptg
   ```

2. 到 https://my.telegram.org 申请 `api_id` 与 `api_hash`。

3. 生成登录会话（会提示输入手机号和验证码）：

   ```bash
   uv run python scripts/telegram_user_login.py
   ```

   命令结束后会打印一串 StringSession。

4. 编辑 `plugins/telegram_user_adapter/config.toml`：

   ```toml
   [plugin]
   enabled = true

   [telegram_account]
   api_id = 1234567
   api_hash = "你的 api_hash"
   session_string = "上一步打印的 StringSession"
   proxy_url = "socks5://127.0.0.1:1080"   # 需要代理时填写
   ```

5. 重启 MaiBot。

## 聊天范围

**群聊默认全部参与**：`group_list` 留空表示不限制，所有群都会聊。
只想聊特定群时，把群号填进去：

```toml
[chat]
group_list_type = "whitelist"
group_list = ["-1001234567890"]   # 留空 = 所有群
```

**私聊默认全部拒绝**，必须显式白名单。这是有意的非对称设计：
一个账号有求必应地回复任何陌生人私信，既不像真人，也是风控高危行为。

```toml
private_list_type = "whitelist"
private_list = ["对方的用户ID"]
```

`ban_user_id` 是全局黑名单，优先级最高，在放开的群里同样生效。

## 拟人化行为

`[behavior]` 段控制"像不像真人"：

- `simulate_typing`：发送前显示"正在输入…"，时长按文本长度估算并带 ±20% 随机抖动。
- `typing_chars_per_second`：打字速度，调小更像慢慢打字的人。
- `min_think_delay`：看到消息后的反应停顿。
- `mark_read` / `read_delay`：延迟若干秒后再标记已读。
- `ignore_outgoing_from_other_devices`：忽略你本人在手机上发的消息，避免自我循环。
- `enable_humanize`：中文群聊改写，去掉书面语连接词、助手腔、markdown、多余 emoji。
- `min_send_gap` / `max_send_gap`：两条消息之间的随机间隔。

### 全局串行发送

所有群共用**一条**发送通道，任何时刻只发一条消息 —— 真人不可能同时在
两个群打字。被 @ 或被回复的群会插队到最前面。

### 只在聊天时上线

`online_only_when_chatting = true`（默认）时，账号平时显示离线，
只在真正要发言前上线，发完后随机 4–15 秒再下线。

一直挂着"在线"是自动化最明显的特征之一。Telethon 本身不会自动上报
在线状态，所以这个行为完全可控。

### 静默时段

`[quiet_hours]` 默认 UTC+8 03:00–07:00 不发言。按固定时区换算，
与服务器本地时区无关。

期间产生的消息**直接丢弃**而不是排队 —— 攒到早上七点一次性喷发出去
比不说话更可疑。

## 日志与自我改进

`[observability]` 段：

- `enable_transcript_log`：把收发消息与拟人化决策写入
  `data/plugins/<插件ID>/transcripts/chat_<群号>.jsonl`。
  除消息内容外还记录排队等待、打字时长、端到端回复延迟、命中的改写规则，
  用于事后审查"这段对话看起来像不像真人"。
- `enable_self_improvement`：在插件数据目录生成两份 Markdown：
  - `SOUL.md` — 身份与说话习惯，变化慢，**可以手工编辑**；
  - `SKILL.md` — 聊天经验统计，由程序自动累积。

改进信号来自可观测行为，而不是让模型自我评价：

| 现象 | 判定 |
|---|---|
| 发言后有人接话 | 正向 |
| 长时间无人理会 | 负向 |
| 对方说"你是不是机器人" | **强负向**，记录当时说了什么 |

被怀疑过的表达会写进 `SKILL.md` 的"应避免"清单，并通过
`prompt_experience.txt` 回注到后续生成的 prompt 里，形成闭环。

排查被识破的原因时，优先看 `SKILL.md` 的"被怀疑的场景记录"。

## 安全提示

- **StringSession 等价于账号登录凭据**，泄露即等于账号被盗，不要提交到 git、不要发给别人。
- Telegram 对个人账号自动化有封号风险。建议：
  - 先用不重要的小号跑一段时间；
  - 不要群发、不要高频刷屏；
  - 保持 `simulate_typing`、静默时段与按需上线开启；
  - 定期查看 `SKILL.md` 里的被怀疑计数。
- 首次登录建议使用干净的住宅 IP，与后续运行环境保持一致，避免异地登录风控。

## 话题群支持

话题群（forum）中每个 topic 会映射为独立的虚拟 group_id
（形如 `-1001234567890::tg-topic::mt=77`），因此不同话题各自是独立会话，
回复也会自动落回原话题而不是 General。

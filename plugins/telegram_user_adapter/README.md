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

   [chat]
   private_list_type = "whitelist"
   private_list = ["对方的用户ID"]
   group_list_type = "whitelist"
   group_list = ["-1001234567890"]
   ```

5. 重启 MaiBot。

## 拟人化行为

`[behavior]` 段控制"像不像真人"：

- `simulate_typing`：发送前显示"正在输入…"，时长按文本长度估算并带 ±20% 随机抖动。
- `typing_chars_per_second`：打字速度，调小更像慢慢打字的人。
- `min_think_delay`：看到消息后的反应停顿。
- `mark_read` / `read_delay`：延迟若干秒后再标记已读。
- `ignore_outgoing_from_other_devices`：忽略你本人在手机上发的消息，避免自我循环。

## 安全提示

- **StringSession 等价于账号登录凭据**，泄露即等于账号被盗，不要提交到 git、不要发给别人。
- Telegram 对个人账号自动化有封号风险。建议：
  - 只在白名单群/私聊里启用；
  - 不要群发、不要高频刷屏；
  - 保持 `simulate_typing` 与打字延迟开启；
  - 用一个不重要的小号先跑一段时间。
- 首次登录建议使用干净的住宅 IP，与后续运行环境保持一致，避免异地登录风控。

## 话题群支持

话题群（forum）中每个 topic 会映射为独立的虚拟 group_id
（形如 `-1001234567890::tg-topic::mt=77`），因此不同话题各自是独立会话，
回复也会自动落回原话题而不是 General。

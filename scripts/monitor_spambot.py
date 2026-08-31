"""监控 Telegram @SpamBot 的账号限制状态。

用途：账号在 2026-08-31 被反垃圾系统限制后，需要持续观察何时解封。

设计要点：
- **只与 @SpamBot 私聊**，不向任何群发消息，不做其他 API 动作。
  受限期间任何多余的自动化行为都可能延长限制。
- 状态写入 JSON 文件，变化时才输出，便于 cron 静默运行。
- 用 /start 查询是官方推荐方式，频率控制在每次调用一次。
"""

from __future__ import annotations

import asyncio
import json
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

CONFIG = Path("/root/MaiBot/plugins/telegram_user_adapter/config.toml")
STATE = Path("/root/MaiBot/data/spambot_status.json")
CN = timezone(timedelta(hours=8))

# SpamBot 回复里代表"已解封"的措辞
FREE_MARKERS = (
    "no limits are currently applied",
    "free as a bird",
)
# 代表"申诉已提交、正在人工审核"的措辞。
# 这是比单纯 limited 更进一步的状态，需要单独识别，
# 否则会被归到 unknown 而每次都触发"状态变化"推送。
APPEALING_MARKERS = (
    "already submitted a complaint",
    "supervisors will check",
    "thank you for your patience",
)
# 代表"仍受限"的措辞
LIMITED_MARKERS = (
    "your account was limited",
    "account is limited",
    "some actions can trigger",
)


def classify(text: str) -> str:
    """把 SpamBot 回复归类为 free / appealing / limited / unknown。"""

    lowered = text.lower()
    if any(marker.lower() in lowered for marker in FREE_MARKERS):
        return "free"
    # 申诉中优先于 limited 判定：这两类措辞会同时出现，
    # 而"已在审核"是更有信息量的状态。
    if any(marker.lower() in lowered for marker in APPEALING_MARKERS):
        return "appealing"
    if any(marker.lower() in lowered for marker in LIMITED_MARKERS):
        return "limited"
    return "unknown"


async def main() -> int:
    cfg = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    tg = cfg["telegram_account"]

    client = TelegramClient(
        StringSession(tg["session_string"]), tg["api_id"], tg["api_hash"]
    )
    await client.start()

    try:
        await client.send_message("SpamBot", "/start")
        await asyncio.sleep(8)

        # 读多条：/start 只回标准受限文案，探测不到"申诉已提交"。
        # 申诉确认是点按钮后的回复，只存在于对话历史里，
        # 所以要在最近若干条中一并查找申诉标记。
        reply_text = ""
        history = ""
        async for msg in client.iter_messages("SpamBot", limit=15):
            if msg.out or not msg.text:
                continue
            if not reply_text:
                reply_text = msg.text
            history += "\n" + msg.text
    finally:
        await client.disconnect()

    # 先按最新回复判定；若最新是标准受限文案但历史里有申诉确认，
    # 则升级为 appealing——申诉在审核中是更准确的状态。
    status = classify(reply_text)
    if status == "limited" and classify(history) == "appealing":
        status = "appealing"

    now = datetime.now(CN)

    previous_record = {}
    if STATE.is_file():
        try:
            previous_record = json.loads(STATE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous_record = {}
    previous = previous_record.get("status")

    # 首次发现受限的时间：用于报告"已受限多久"，等待期间这是核心信息。
    limited_since = previous_record.get("limited_since")
    if status in ("limited", "appealing"):
        if not limited_since:
            limited_since = now.isoformat(timespec="seconds")
    else:
        limited_since = None

    record = {
        "checked_at": now.isoformat(timespec="seconds"),
        "status": status,
        "limited_since": limited_since,
        "reply_excerpt": reply_text[:300],
    }

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    def elapsed_text() -> str:
        """返回"已受限 X 小时 Y 分"的描述。"""

        if not limited_since:
            return ""
        started = datetime.fromisoformat(limited_since)
        minutes = int((now - started).total_seconds() / 60)
        return f"已持续 {minutes // 60} 小时 {minutes % 60} 分"

    # 只在状态变化或已解封时输出，便于 cron 静默运行
    if status == "free":
        print(f"🎉 账号已解封（{now:%m-%d %H:%M}）")
        print(f"SpamBot: {reply_text[:200]}")
        return 0
    if previous != status:
        print(f"⚠️ 状态变化: {previous} → {status}（{now:%m-%d %H:%M}）{elapsed_text()}")
        print(f"SpamBot: {reply_text[:200]}")
        return 0

    # 状态未变且仍受限：静默
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

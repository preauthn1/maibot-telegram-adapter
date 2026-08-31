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
# 代表"仍受限"的措辞
LIMITED_MARKERS = (
    "your account was limited",
    "account is limited",
    "some actions can trigger",
)


def classify(text: str) -> str:
    """把 SpamBot 回复归类为 free / limited / unknown。"""

    lowered = text.lower()
    if any(marker.lower() in lowered for marker in FREE_MARKERS):
        return "free"
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

        reply_text = ""
        async for msg in client.iter_messages("SpamBot", limit=5):
            if msg.out or not msg.text:
                continue
            reply_text = msg.text
            break
    finally:
        await client.disconnect()

    status = classify(reply_text)
    now = datetime.now(CN)
    record = {
        "checked_at": now.isoformat(timespec="seconds"),
        "status": status,
        "reply_excerpt": reply_text[:300],
    }

    previous = None
    if STATE.is_file():
        try:
            previous = json.loads(STATE.read_text(encoding="utf-8")).get("status")
        except (json.JSONDecodeError, OSError):
            previous = None

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 只在状态变化或已解封时输出，便于 cron 静默运行
    if status == "free":
        print(f"🎉 账号已解封（{now:%m-%d %H:%M}）")
        print(f"SpamBot: {reply_text[:200]}")
        return 0
    if previous != status:
        print(f"⚠️ 状态变化: {previous} → {status}（{now:%m-%d %H:%M}）")
        print(f"SpamBot: {reply_text[:200]}")
        return 0

    # 状态未变且仍受限：静默
    return 0


sys.exit(asyncio.run(main()))

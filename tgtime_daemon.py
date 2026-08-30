#!/usr/bin/env python3
"""把 Telegram 姓氏实时显示为当前时间（UTC+8）。

参考 https://github.com/8838/tgtime 的思路，但做了三点改动：

1. **复用主程序的 StringSession**，不另开 .session 文件。
   两个进程用同一个 session 文件会互相踩踏，可能导致主程序掉线。
2. **每 5 分钟更新一次**（原版每分钟）。显示精度对人眼没差别，
   但 profile 写操作从 1440 次/天降到 288 次/天，明显降低风控压力。
3. 失败时指数退避而不是死循环重试，避免触发 FloodWait 后雪上加霜。

注意：此功能会让账号呈现明显的自动化特征（姓氏规律跳变），
是用户明确要求后才启用的。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncio
import logging
import sys
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent))

from telethon import TelegramClient, errors  # noqa: E402
from telethon.sessions import StringSession  # noqa: E402
from telethon.tl.functions.account import UpdateProfileRequest  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parent / "plugins/telegram_user_adapter/config.toml"
UPDATE_INTERVAL = 300.0  # 5 分钟
CN_TZ = timezone(timedelta(hours=8))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [tgtime] %(message)s",
    datefmt="%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _load_account() -> dict:
    """读取主程序的账号配置。

    Returns:
        dict: 含 api_id / api_hash / session_string 的字典。
    """

    cfg = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return cfg["telegram_account"]


async def _run() -> None:
    """主循环：定期把姓氏更新为当前时间。"""

    acc = _load_account()
    client = TelegramClient(
        StringSession(acc["session_string"]), acc["api_id"], acc["api_hash"]
    )
    await client.connect()

    if not await client.is_user_authorized():
        logger.error("会话未授权，退出")
        return

    me = await client.get_me()
    logger.info(f"已连接: @{me.username} (id={me.id})")

    backoff = 0.0
    while True:
        try:
            now = datetime.now(CN_TZ)
            last_name = f"{now:%H:%M} UTC+8"
            await client(UpdateProfileRequest(last_name=last_name))
            logger.info(f"已更新 -> {last_name}")
            backoff = 0.0
        except errors.FloodWaitError as exc:
            # 触发限流说明改得太频繁，等满它要求的时间再说。
            logger.warning(f"触发限流，等待 {exc.seconds}s")
            await asyncio.sleep(exc.seconds + 5)
            continue
        except (errors.RPCError, OSError) as exc:
            # 指数退避，避免失败后立刻重试把情况弄得更糟。
            backoff = min(max(backoff * 2, 30.0), 600.0)
            logger.warning(f"更新失败({type(exc).__name__})，{backoff:.0f}s 后重试")
            await asyncio.sleep(backoff)
            continue

        # 对齐到下一个 5 分钟边界，让跳变看起来更整齐。
        await asyncio.sleep(UPDATE_INTERVAL)


def main() -> int:
    """入口。"""

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())

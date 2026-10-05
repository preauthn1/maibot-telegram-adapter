"""有界离线验证：虚构名单、真实闸门、假传输；无网络/服务/pytest。"""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import asyncio
import ast
import json
import logging
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from plugins.telegram_user_adapter import unlimited_mode as mode
from plugins.telegram_user_adapter.attention_focus import AttentionFocus
from plugins.telegram_user_adapter.official_stickers import OfficialDuckStickers
from plugins.telegram_user_adapter.plugin import TelegramUserAdapterPlugin
from plugins.telegram_user_adapter.send_budget import SendBudget
from plugins.telegram_user_adapter.send_queue import QuietHoursError, SendQueue
from plugins.telegram_user_adapter.send_queue import candidate_enqueued_at
from plugins.telegram_user_adapter.share_guard import ShareGuard
from plugins.telegram_user_adapter.small_chat import SmallChatModerator
from plugins.telegram_user_adapter.trigger import TriggerManager
from plugins.telegram_user_adapter.codecs.outbound import TelegramUserOutboundCodec
from verify_official_stickers_offline import Transport, fixture

TARGET = "synthetic-frequency-target"
OTHER = "synthetic-normal-chat"


async def verify():
    assert mode.is_unlimited(TARGET) and not mode.is_unlimited(OTHER)
    assert not mode.is_unlimited() and not mode.is_unlimited(TARGET + "::tg-topic::mt=1")
    os.environ["TG_UNLIMITED_MODE"] = "1"
    assert not mode.is_unlimited(OTHER) and not mode.is_unlimited()
    ready = asyncio.Event()
    async def target_task():
        with mode.frequency_scope(TARGET):
            ready.set()
            await asyncio.sleep(0)
            assert mode.is_unlimited() and not mode.is_unlimited(OTHER)
        assert not mode.is_unlimited()
    async def other_task():
        await ready.wait()
        assert not mode.is_unlimited()
        with mode.frequency_scope(OTHER):
            await asyncio.sleep(0)
            assert not mode.is_unlimited()
    await asyncio.gather(target_task(), other_task())
    try:
        with mode.frequency_scope(TARGET):
            raise RuntimeError("synthetic")
    except RuntimeError:
        pass
    assert not mode.is_unlimited()

    async def cancelled_scope():
        with mode.frequency_scope(TARGET):
            try:
                raise asyncio.CancelledError()
            finally:
                assert mode.is_unlimited()
    try:
        await cancelled_scope()
    except asyncio.CancelledError:
        pass
    assert not mode.is_unlimited()

    budget = SendBudget(minute_limit=1, hourly_limit=1)
    budget.record(now=10)
    assert budget.check(TARGET, now=11)[0] and not budget.check(OTHER, now=11)[0]
    assert budget.stats(now=11)["last_hour"] == 1
    focus = AttentionFocus(max_concurrent_chats=1)
    focus.record("occupied", now=10)
    assert focus.check(TARGET, now=11)[0] and not focus.check(OTHER, now=11)[0]
    trigger = TriggerManager()
    for chat in (TARGET, OTHER):
        trigger.record_response(chat, now=10)
    assert trigger.evaluate(TARGET, "chat", is_private=False, is_directed=False, now=11).should_respond
    assert not trigger.evaluate(OTHER, "chat", is_private=False, is_directed=False, now=11).should_respond
    small = SmallChatModerator()
    for chat in (TARGET, OTHER):
        small.record_outbound(chat, "晚安", now=10)
    assert not small.should_suppress(TARGET, member_count=2, now=11)[0]
    assert small.should_suppress(OTHER, member_count=2, now=11)[0]
    plugin = object.__new__(TelegramUserAdapterPlugin)
    plugin._load_settings = lambda: SimpleNamespace(behavior=SimpleNamespace(
        max_consecutive_replies=1, consecutive_cooldown=60,
        per_user_reply_limit=1, per_user_window=60))
    plugin._consecutive_replies = {TARGET: 9, OTHER: 9}
    plugin._consecutive_blocked_at = {}
    plugin._user_message_times = {}
    plugin._ctx = SimpleNamespace(logger=logging.getLogger("offline"))
    assert not plugin._is_consecutive_limited(TARGET)
    assert plugin._is_consecutive_limited(OTHER)
    for chat in (TARGET, OTHER):
        assert not plugin._is_user_flooding(chat, "synthetic-sender")
    assert not plugin._is_user_flooding(TARGET, "synthetic-sender")
    assert plugin._is_user_flooding(OTHER, "synthetic-sender")
    share = ShareGuard()
    share.note_complaint()
    assert not share.allows_send(frequency_override=True)

    ducks = OfficialDuckStickers()
    ducks.install(fixture())
    assert ducks.reserve(TARGET, now=1)
    assert not ducks.reserve(TARGET, now=1)  # 单飞保护不豁免
    ducks.finish(TARGET, success=True, now=1)
    assert ducks.reserve(TARGET, now=2)
    ducks.finish(TARGET, success=False)
    assert not ducks.reserve(OTHER, now=2)
    assert ducks._global_last == 1 and ducks._last_sent[TARGET] == 1
    assert ducks.select({"pack": "Other", "emoji": "😂"}) is None
    assert ducks.select({"pack": "UtyaDuck", "emoji": "😂", "document_id": 999}) is None

    queue = SendQueue(logging.getLogger("offline"), min_gap_seconds=100, max_gap_seconds=100)
    queue.in_quiet_hours = lambda now=None: True
    queue.start()
    queue._last_sent_at = asyncio.get_running_loop().time()
    async def action():
        assert mode.is_unlimited()
        await asyncio.sleep(0)
        return "offline-only"
    try:
        assert await queue.submit(action, label=TARGET) == "offline-only"
        try:
            await queue.submit(action, label=OTHER)
            raise AssertionError("normal chat bypassed quiet hours")
        except QuietHoursError:
            pass
    finally:
        await queue.stop()
    assert not mode.is_unlimited()

    # 执行真实贴纸 codec：饱和预算/低信息额度/贴纸冷却/候选年龄均不拦目标。
    transport = Transport()
    from plugins.telegram_user_adapter.telegram_user_client import TelegramUserClient
    client = object.__new__(TelegramUserClient)
    client._client = transport
    codec = TelegramUserOutboundCodec(client, logging.getLogger("offline"))
    codec.stickers.install(fixture())
    codec._send_budget = budget
    for _ in range(10):
        codec._low_information_guard.record("哈哈")
    candidate_enqueued_at.set(0.0)
    for _ in range(2):
        result = await codec._send_segment(TARGET, TARGET, {"type": "sticker", "data": "😂"},
                                           reply_to=None)
        assert result is not None
    assert len(transport.sent) == 2
    assert await codec._send_segment(OTHER, OTHER, {"type": "sticker", "data": "😂"},
                                     reply_to=None) is None
    assert not mode.is_unlimited()
    print("PASS: exact/fail-closed targets, env isolation, concurrent await/reset, budget/accounting, focus, trigger, small-chat, consecutive, per-user, complaint safety, Duck single-flight/source/emoji/accounting, queue quiet/gap, real sticker codec target-vs-normal")


if __name__ == "__main__":
    for source in (ROOT / "plugins" / "telegram_user_adapter").rglob("*.py"):
        ast.parse(source.read_text(encoding="utf-8"))
    original = mode._TARGET_FILE
    with TemporaryDirectory(prefix="frequency-offline-") as directory:
        mode._TARGET_FILE = Path(directory) / "targets.json"
        assert not mode.is_unlimited(TARGET)
        mode._TARGET_FILE.write_text("{broken", encoding="utf-8")
        assert not mode.is_unlimited(TARGET)
        mode._TARGET_FILE.write_text(json.dumps({"targets": [TARGET]}), encoding="utf-8")
        try:
            asyncio.run(asyncio.wait_for(verify(), timeout=10))
        finally:
            mode._TARGET_FILE = original

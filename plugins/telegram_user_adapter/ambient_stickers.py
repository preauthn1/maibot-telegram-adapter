"""在活跃的白名单群里，隔一段时间随机发一张奶龙贴纸（TangBiNaiLong）。

用户 2026-10-06 要求：真人会时不时甩个表情包，纯文字账号反而显得像机器人。

只做“何时发、发哪张”的决定；真正发送仍走插件网关
（话语权闸门、连发抑制、静默时段、发送队列、全局预算、注意力焦点全部生效）。

触发条件（全部满足才可能发，再按概率掷骰）：
- 群在白名单中，且不是高风险群；
- 最近 10 分钟至少 3 条别人的消息，最后一条在 2 分钟内，且最后说话的不是我们；
- 我们 30 分钟内在这个群说过话（在聊天里，而不是潜水突然冒泡）；
- 本群距上次贴纸已过随机间隔（40–120 分钟），全局距上次 ≥15 分钟，本群当天 ≤6 张。

运维开关：MAIBOT_AMBIENT_STICKERS=0 关闭；
MAIBOT_AMBIENT_STICKER_EXCLUDE 覆盖排除序号（逗号分隔，填 none 表示全包可用）。
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import asyncio
import os
import random
import time

PACK_SHORT_NAME = "TangBiNaiLong"
EXPECTED_COUNT = 75
# 默认排除：#18 上吊暗示；#1 #13 #22 #70 #71 性暗示；#15 #37 #45 真人脸（含婴儿）；
# #32 科比梗；#72 佛像。序号按服务端套装顺序（0 起），套装数量变化时整体停用。
DEFAULT_EXCLUDED = frozenset({1, 13, 15, 18, 22, 32, 37, 45, 70, 71, 72})
_CN_TZ = timezone(timedelta(hours=8))


def enabled() -> bool:
    return os.environ.get("MAIBOT_AMBIENT_STICKERS", "1").strip().lower() not in {"0", "false", "off", "no"}


def excluded_indices() -> frozenset:
    raw = os.environ.get("MAIBOT_AMBIENT_STICKER_EXCLUDE")
    if raw is None:
        return DEFAULT_EXCLUDED
    if raw.strip().lower() in {"", "none"}:
        return frozenset()
    return frozenset(int(part) for part in raw.split(",") if part.strip())


class AmbientStickerCatalog:
    """服务端套装目录；每次发送前重取，保证 file_reference 新鲜。"""

    def __init__(self) -> None:
        self._documents: Dict[int, Any] = {}
        self._lock = asyncio.Lock()
        self._recent: Deque[int] = deque(maxlen=12)

    @property
    def ready(self) -> bool:
        return bool(self._documents)

    def install(self, result: Any) -> int:
        from telethon.tl.types import Document

        self._documents = {}
        meta = result.set
        if meta.short_name != PACK_SHORT_NAME:
            raise ValueError("贴纸套装身份不匹配")
        if getattr(meta, "masks", False) or getattr(meta, "emojis", False):
            raise ValueError("目标不是普通贴纸套装")
        excluded = excluded_indices()
        if excluded and len(result.documents) != EXPECTED_COUNT:
            # 排除名单按序号写死；套装增删后序号会错位，宁可停用。
            raise ValueError(f"套装数量变化（{len(result.documents)}），排除名单失效")
        documents: Dict[int, Any] = {}
        for index, document in enumerate(result.documents):
            if index in excluded:
                continue
            if isinstance(document, Document) and document.access_hash and document.file_reference:
                documents[index] = document
        if not documents:
            raise ValueError("套装没有可用贴纸")
        self._documents = documents
        return len(documents)

    async def refresh(self, client: Any) -> int:
        from telethon.tl.functions.messages import GetStickerSetRequest
        from telethon.tl.types import InputStickerSetShortName

        async with self._lock:
            result = await client(GetStickerSetRequest(
                stickerset=InputStickerSetShortName(PACK_SHORT_NAME), hash=0,
            ))
            return self.install(result)

    def pick(self, rng: Optional[random.Random] = None) -> Optional[int]:
        """随机挑一张，避开最近发过的。"""
        rng = rng or random
        indices = list(self._documents)
        if not indices:
            return None
        fresh = [i for i in indices if i not in self._recent] or indices
        choice = rng.choice(fresh)
        self._recent.append(choice)
        return choice

    def get(self, index: int) -> Optional[Any]:
        return self._documents.get(index)


class AmbientScheduler:
    """纯决策逻辑，不碰网络；时间用 monotonic，日界按 UTC+8。"""

    def __init__(
        self,
        *,
        gap_range: Tuple[float, float] = (40 * 60, 120 * 60),
        initial_delay: Tuple[float, float] = (10 * 60, 40 * 60),
        global_gap: float = 15 * 60,
        daily_cap: int = 6,
        active_window: float = 10 * 60,
        min_inbound: int = 3,
        live_window: float = 120,
        recent_spoke: float = 30 * 60,
        chance: float = 0.2,
        rng: Optional[random.Random] = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = lambda: datetime.now(_CN_TZ),
    ) -> None:
        self._gap_range = gap_range
        self._initial_delay = initial_delay
        self._global_gap = global_gap
        self._daily_cap = daily_cap
        self._active_window = active_window
        self._min_inbound = min_inbound
        self._live_window = live_window
        self._recent_spoke = recent_spoke
        self._chance = chance
        self._rng = rng or random.Random()
        self._clock = clock
        self._wall = wall
        self._inbound: Dict[str, Deque[float]] = {}
        self._next_allowed: Dict[str, float] = {}
        self._daily: Dict[str, Tuple[str, int]] = {}
        self._global_last: Optional[float] = None

    def note_inbound(self, session: str, now: Optional[float] = None) -> None:
        now = self._clock() if now is None else now
        bucket = self._inbound.setdefault(session, deque(maxlen=50))
        bucket.append(now)
        if session not in self._next_allowed:
            # 重启或首次看到这个群：不立刻发，先等一段随机时间。
            self._next_allowed[session] = now + self._rng.uniform(*self._initial_delay)

    def sessions(self) -> List[str]:
        return list(self._inbound)

    def _today_count(self, session: str) -> int:
        day = self._wall().strftime("%Y-%m-%d")
        stored = self._daily.get(session)
        return stored[1] if stored and stored[0] == day else 0

    def due(self, session: str, *, last_spoke_at: Optional[float], now: Optional[float] = None) -> Tuple[bool, str]:
        now = self._clock() if now is None else now
        bucket = self._inbound.get(session)
        if not bucket:
            return False, "no_inbound"
        recent = [t for t in bucket if now - t <= self._active_window]
        if len(recent) < self._min_inbound:
            return False, "not_active"
        last_inbound = bucket[-1]
        if now - last_inbound > self._live_window:
            return False, "conversation_idle"
        if last_spoke_at is None or now - last_spoke_at > self._recent_spoke:
            return False, "not_participating"
        if last_spoke_at >= last_inbound:
            return False, "last_message_is_ours"
        if now < self._next_allowed.get(session, 0.0):
            return False, "chat_gap"
        if self._global_last is not None and now - self._global_last < self._global_gap:
            return False, "global_gap"
        if self._today_count(session) >= self._daily_cap:
            return False, "daily_cap"
        if self._rng.random() >= self._chance:
            return False, "dice"
        return True, "ok"

    def commit(self, session: str, *, sent: bool, now: Optional[float] = None) -> None:
        """无论是否真的发出，都推迟下次机会，避免被闸门拦下后每分钟重试。"""
        now = self._clock() if now is None else now
        if sent:
            self._next_allowed[session] = now + self._rng.uniform(*self._gap_range)
            self._global_last = now
            day = self._wall().strftime("%Y-%m-%d")
            self._daily[session] = (day, self._today_count(session) + 1)
        else:
            self._next_allowed[session] = now + self._rng.uniform(10 * 60, 20 * 60)

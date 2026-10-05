"""媒体视觉理解成本治理（升级计划 Phase 9）。

已有：
- ``image_manager`` 按 sha256 缓存视觉描述（同一媒体只识别一次）。
- 适配器 ``image_burst`` 把连发图片合并。

本模块补"是否需要看图"的低成本预判：在**没人叫我们**时，同一聊天流
短时间内只为前 N 张非指向媒体下载并交给 VLM，其余用文本占位（不下载、不识别）。
被 @/回复我们的媒体永远照常处理。回放数据：未指名的媒体里我们历史上只接过
约 3.8%，大部分视觉调用不会影响回复决策。

视觉摘要绑定在当前消息上随会话流转，跨群不复用描述文本（缓存只按内容 hash，
描述生成不带会话上下文，因此不会泄露 A 群语境到 B 群）。
"""

from collections import defaultdict, deque
from typing import Deque, Dict, Optional

import time

WINDOW_SECONDS = 10 * 60
MAX_UNDIRECTED_PER_WINDOW = 4


class MediaBudget:
    """按会话的非指向媒体识别预算。"""

    def __init__(self, window: float = WINDOW_SECONDS, limit: int = MAX_UNDIRECTED_PER_WINDOW) -> None:
        self._window = window
        self._limit = limit
        self._seen: Dict[str, Deque[float]] = defaultdict(deque)
        self.skipped = 0
        self.allowed = 0

    def should_analyze(self, chat_id: str, *, directed_at_us: bool, now: Optional[float] = None) -> bool:
        if directed_at_us:
            self.allowed += 1
            return True
        now = time.monotonic() if now is None else now
        queue = self._seen[str(chat_id)]
        while queue and now - queue[0] > self._window:
            queue.popleft()
        if len(queue) >= self._limit:
            self.skipped += 1
            return False
        queue.append(now)
        self.allowed += 1
        return True

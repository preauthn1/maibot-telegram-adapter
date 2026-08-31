"""触发分级：区分「必须答」「值得插话」「随便聊」三档。

为什么需要这个模块
------------------

我们此前只有 ``small_chat`` 的单一发言间隔，所有场景一视同仁。
但真人的行为明显是分级的：

- **被点名问到** → 立刻答。不会因为"我刚说过话"就不理人。
- **聊到我关注的话题** → 插一句，间隔可以短一些。
- **纯闲聊** → 有话说才接，且要看自己是不是刚说过。

一刀切的后果是两头都不像真人：要么被 @ 了还在潜水（我方实测
某群 25 次决策 0 次回复），要么闲聊时话太密（15 时 107 条）。

思路移植自 AEsirClaw 的 ``TriggerManager``，改了三处：

1. 参考实现在 ``check()`` 内部调用 ``record_response()``——
   「打算回复」就占用冷却。但决策之后还会经过参与率约束、
   内容过滤、发送预算等多道关卡，实际没发出去却已消耗冷却，
   表现就是"该说话的时候反而沉默"。这里 ``evaluate()`` 是纯函数，
   记账由调用方在**发送成功后**执行。
2. 参考实现末尾有不可达代码（``return`` 之后还有 ``return``）。
3. 参考实现私聊冷却 1 秒。对真人号太快——1 秒连答是机器特征，
   这里给到 6 秒。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Sequence, Tuple

import time

# 群聊闲聊冷却（秒）。
#
# 45 秒：真人在群里闲聊不会每隔十几秒就冒一句。
# 被 @ 和命中关键词走各自的更短冷却，不受这个限制。
DEFAULT_GROUP_COOLDOWN = 45.0

# 私聊冷却（秒）。
#
# 6 秒：私聊本该比群聊积极，但参考实现的 1 秒太快——
# 人读完消息再打字回复不可能只花 1 秒。
DEFAULT_PRIVATE_COOLDOWN = 6.0

# 关键词命中冷却（秒）。
#
# 20 秒：聊到自己关注的话题时可以更主动，但仍要有间隔，
# 否则相关话题一出现就连珠炮式接话同样扎眼。
DEFAULT_KEYWORD_COOLDOWN = 20.0


class TriggerLevel(Enum):
    """触发档位。"""

    FORCED = "forced"
    """必须回应：被 @、被回复、私聊。"""

    KEYWORD = "keyword"
    """关注话题：命中关键词，可较主动插话。"""

    CASUAL = "casual"
    """普通闲聊：受完整冷却约束。"""

    NONE = "none"
    """不触发。"""


@dataclass(frozen=True)
class TriggerDecision:
    """触发判定结果。"""

    should_respond: bool
    level: TriggerLevel
    reason: str = ""


class TriggerManager:
    """按档位判断是否应当回应，并按档位使用不同冷却。"""

    def __init__(
        self,
        *,
        keywords: Sequence[str] = (),
        group_cooldown: float = DEFAULT_GROUP_COOLDOWN,
        private_cooldown: float = DEFAULT_PRIVATE_COOLDOWN,
        keyword_cooldown: float = DEFAULT_KEYWORD_COOLDOWN,
    ) -> None:
        """初始化触发管理器。

        Args:
            keywords: 关注的关键词，命中后走 KEYWORD 档。
            group_cooldown: 群聊闲聊冷却秒数。
            private_cooldown: 私聊冷却秒数。
            keyword_cooldown: 关键词命中后的冷却秒数。
        """

        self.keywords = tuple(word.lower() for word in keywords if word.strip())
        self.group_cooldown = group_cooldown
        self.private_cooldown = private_cooldown
        self.keyword_cooldown = keyword_cooldown
        # session_key -> 最近一次实际发言时间
        self._last_response: Dict[str, float] = {}

    def _elapsed(self, session_key: str, now: float) -> Optional[float]:
        """返回距上次发言的秒数；从未发言过返回 None。"""

        last = self._last_response.get(session_key)
        if last is None:
            return None
        return now - last

    def _match_keyword(self, text: str) -> Optional[str]:
        """返回命中的关键词，未命中返回 None。"""

        lowered = text.lower()
        for word in self.keywords:
            if word in lowered:
                return word
        return None

    def evaluate(
        self,
        session_key: str,
        text: str,
        *,
        is_private: bool,
        is_directed: bool,
        now: Optional[float] = None,
    ) -> TriggerDecision:
        """判断是否应当回应这条消息。

        这是**纯判断**，不修改冷却状态。调用方必须在消息真正
        发出去之后调用 ``record_response`` 记账。

        Args:
            session_key: 会话标识。
            text: 消息文本。
            is_private: 是否私聊。
            is_directed: 是否被 @ 或被回复。
            now: 时间戳，便于测试注入。

        Returns:
            TriggerDecision: 判定结果。
        """

        current = now if now is not None else time.time()

        # 被点名：真人不会因为"刚说过话"就不理人。
        if is_directed:
            return TriggerDecision(True, TriggerLevel.FORCED, "被 @ 或被回复")

        if is_private:
            elapsed = self._elapsed(session_key, current)
            if elapsed is not None and elapsed < self.private_cooldown:
                remaining = self.private_cooldown - elapsed
                return TriggerDecision(
                    False, TriggerLevel.NONE, f"私聊冷却中，剩余 {remaining:.1f}s"
                )
            return TriggerDecision(True, TriggerLevel.FORCED, "私聊消息")

        # 关注话题：可以更主动，但用独立的较短冷却。
        hit = self._match_keyword(text)
        if hit is not None:
            elapsed = self._elapsed(session_key, current)
            if elapsed is not None and elapsed < self.keyword_cooldown:
                remaining = self.keyword_cooldown - elapsed
                return TriggerDecision(
                    False,
                    TriggerLevel.NONE,
                    f"关键词冷却中，剩余 {remaining:.1f}s",
                )
            return TriggerDecision(True, TriggerLevel.KEYWORD, f"命中关键词 {hit!r}")

        # 普通闲聊：完整冷却。
        elapsed = self._elapsed(session_key, current)
        if elapsed is not None and elapsed < self.group_cooldown:
            remaining = self.group_cooldown - elapsed
            return TriggerDecision(
                False, TriggerLevel.NONE, f"群聊冷却中，剩余 {remaining:.1f}s"
            )
        return TriggerDecision(True, TriggerLevel.CASUAL, "冷却已过，可参与闲聊")

    def record_response(
        self, session_key: str, *, now: Optional[float] = None
    ) -> None:
        """记录一次**实际发出**的回应。

        Args:
            session_key: 会话标识。
            now: 时间戳。
        """

        if not session_key:
            return
        self._last_response[session_key] = (
            now if now is not None else time.time()
        )

    def cooldown_remaining(
        self, session_key: str, *, now: Optional[float] = None
    ) -> float:
        """返回该会话剩余的群聊冷却秒数。

        Args:
            session_key: 会话标识。
            now: 时间戳。

        Returns:
            float: 剩余秒数；已过冷却返回 0。
        """

        current = now if now is not None else time.time()
        elapsed = self._elapsed(session_key, current)
        if elapsed is None:
            return 0.0
        return max(0.0, self.group_cooldown - elapsed)

    def stats(self) -> Tuple[int, float]:
        """返回已跟踪的会话数与群聊冷却设置。

        Returns:
            Tuple[int, float]: ``(会话数, 群聊冷却秒数)``。
        """

        return len(self._last_response), self.group_cooldown

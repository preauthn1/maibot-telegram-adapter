"""主动表情回应的节流与选择策略。

给别人的消息点表情是一种低成本的\"我在看\"信号，比硬凑一句话更自然。
但它同时是**最容易暴露自动化**的动作之一：真人不会秒回、不会逢消息必点、
更不会整夜不停地点。因此这里集中管控四件事：

1. 概率——只对一小部分消息点表情
2. 冷却——同一会话两次点表情之间必须隔开
3. 每小时上限——硬性封顶，防封号
4. 去重——同一条消息绝不点第二次

表情选择用关键词启发式而不是再调一次 LLM：可预测、零成本，
而且不会因为模型抽风点出与语境相反的表情。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import random
import time

# 各会话普遍可用的\"原始\"标准表情。Telegram 允许的集合更大，
# 但这几个在绝大多数群里都开着，用它们能最大程度避免 ReactionInvalidError。
SAFE_REACTIONS: Tuple[str, ...] = ("👍", "❤", "🔥", "🎉", "😁", "😢", "🤔", "🤯")

# 关键词 -> 表情。命中即用，未命中则从池子里随机挑一个。
_KEYWORD_EMOJI: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("哈哈", "笑死", "草", "lol", "🤣", "😂", "好笑"), "😁"),
    (("谢谢", "感谢", "多谢", "thx", "thanks"), "❤"),
    (("牛", "厉害", "强", "666", "nb", "amazing", "赞"), "🔥"),
    (("恭喜", "祝贺", "生日快乐", "毕业", "上岸"), "🎉"),
    (("难过", "伤心", "可惜", "唉", "emo", "抑郁"), "😢"),
    (("离谱", "震惊", "卧槽", "什么鬼", "wtf", "不会吧"), "🤯"),
    (("为什么", "怎么办", "求助", "请教", "?", "？"), "🤔"),
)


class ReactionPolicy:
    """决定\"这条消息要不要点表情、点什么\"。"""

    def __init__(
        self,
        *,
        probability: float,
        chat_cooldown: float,
        hourly_limit: int,
        emoji_pool: Optional[List[str]] = None,
    ) -> None:
        """初始化节流策略。

        Args:
            probability: 单条消息触发点表情的概率（0-1）。
            chat_cooldown: 同一会话两次点表情的最小间隔（秒）。
            hourly_limit: 每小时全局点表情次数上限。
            emoji_pool: 可用表情池；留空则使用内置安全集合。
        """

        self._probability = probability
        self._chat_cooldown = chat_cooldown
        self._hourly_limit = hourly_limit
        self._emoji_pool = list(emoji_pool) if emoji_pool else list(SAFE_REACTIONS)

        # chat_id -> 上次点表情的单调时钟
        self._last_reaction_at: Dict[str, float] = {}
        # 最近一小时内每次点表情的时间戳，用于滑动窗口限流
        self._recent_reactions: List[float] = []
        # 已点过的消息，防止重复点。有界，避免长期泄漏。
        self._reacted: "OrderedDict[Tuple[str, int], None]" = OrderedDict()
        # 每个会话被拒绝过的表情，命中 ReactionInvalidError 后拉黑不再重试
        self._blacklist: Dict[str, set[str]] = {}
        # 明确不支持表情的会话，直接跳过
        self._disabled_chats: set[str] = set()

    def mark_chat_disabled(self, chat_id: str) -> None:
        """标记某会话不允许表情回应，后续直接跳过。"""

        self._disabled_chats.add(chat_id)

    def blacklist_emoji(self, chat_id: str, emoji: str) -> None:
        """把某会话里被拒绝的表情拉黑。"""

        self._blacklist.setdefault(chat_id, set()).add(emoji)

    def mark_reacted(self, chat_id: str, message_id: int) -> None:
        """登记一次成功的表情回应，推进冷却与限流计数。"""

        now = time.monotonic()
        self._last_reaction_at[chat_id] = now
        self._recent_reactions.append(now)

        key = (chat_id, message_id)
        self._reacted.pop(key, None)
        self._reacted[key] = None
        while len(self._reacted) > 1000:
            self._reacted.popitem(last=False)

    def _prune_hourly(self, now: float) -> None:
        """丢弃一小时之前的计数。"""

        cutoff = now - 3600.0
        self._recent_reactions = [t for t in self._recent_reactions if t >= cutoff]

    def should_react(self, chat_id: str, message_id: int) -> bool:
        """判断这条消息是否要点表情。

        Args:
            chat_id: 原始会话 ID。
            message_id: 消息 ID。

        Returns:
            bool: 是否应当点表情。
        """

        if self._probability <= 0:
            return False
        if chat_id in self._disabled_chats:
            return False
        if (chat_id, message_id) in self._reacted:
            # 同一条消息重复点表情是明显的脚本行为。
            return False

        now = time.monotonic()

        self._prune_hourly(now)
        if len(self._recent_reactions) >= self._hourly_limit:
            return False

        last = self._last_reaction_at.get(chat_id)
        if last is not None and (now - last) < self._chat_cooldown:
            return False

        return random.random() < self._probability

    def pick_emoji(self, chat_id: str, text: str, allowed: Optional[set[str]] = None) -> Optional[str]:
        """为一条消息挑一个表情。

        Args:
            chat_id: 会话 ID，用于排除该会话已拉黑的表情。
            text: 消息文本，用于关键词匹配。
            allowed: 该会话允许的表情集合；``None`` 表示不限制。

        Returns:
            Optional[str]: 选中的表情；没有可用表情时返回 ``None``。
        """

        banned = self._blacklist.get(chat_id, set())

        def _usable(emoji: str) -> bool:
            if emoji in banned:
                return False
            if allowed is not None and emoji not in allowed:
                return False
            return True

        lowered = text.lower()
        for keywords, emoji in _KEYWORD_EMOJI:
            if any(k in lowered for k in keywords) and _usable(emoji):
                return emoji

        candidates = [e for e in self._emoji_pool if _usable(e)]
        if not candidates:
            return None
        return random.choice(candidates)


def resolve_allowed_reactions(available: Any) -> Optional[set[str]]:
    """把 MTProto 的 available_reactions 解析成允许的表情集合。

    Args:
        available: ``ChatReactionsAll`` / ``ChatReactionsSome`` / ``ChatReactionsNone``
            或 ``None``。

    Returns:
        Optional[set[str]]: 允许的表情集合；``None`` 表示不限制；
            空集合表示该会话禁用了表情回应。
    """

    from telethon.tl import types

    # 字段缺省说明管理员没做限制，等价于允许标准表情——
    # 不能把 None 当成\"禁用\"，否则功能会被悄悄关掉。
    if available is None:
        return None
    if isinstance(available, types.ChatReactionsNone):
        return set()
    if isinstance(available, types.ChatReactionsAll):
        return None
    if isinstance(available, types.ChatReactionsSome):
        allowed: set[str] = set()
        for reaction in available.reactions or []:
            if isinstance(reaction, types.ReactionEmoji):
                emoticon = str(reaction.emoticon or "").strip()
                if emoticon:
                    allowed.add(emoticon)
        return allowed
    return None

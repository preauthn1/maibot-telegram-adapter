"""针对本账号的挑衅识别与硬气回应。

背景：线上有人反复用 `@我 傻逼？` `滚出去` 这样的方式点名辱骂。
一直沉默会显得这个号是死的，但对骂又会把号玩掉。

设计取舍：

1. **只在被直接针对时触发**。判定要求「@ 了我们或回复我们」+「有辱骂词」。
   不做泛化的\"低智内容\"识别——那种标准无法可靠定义，误伤一个
   无辜的人比放过一次挑衅的代价大得多。
2. **回应不带脏字**。带脏字会被举报/封号，而且跟对方拉到同一水平
   反而输了。硬气来自点破事实，不来自音量。
3. **每人只回一次**。对方要的就是反应，给一次就够；继续纠缠不再理，
   避免无限对喷。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import random
import re
import time

# 针对性辱骂词。只收真正的攻击性表达，不收\"垃圾/废物\"这类
# 日常也会出现的词（\"这游戏真垃圾\" 不该触发）。
_INSULT_WORDS: Tuple[str, ...] = (
    "傻逼", "煞笔", "sb", "智障", "弱智", "脑残", "低能",
    "你妈", "尼玛", "妈的", "md", "草你", "操你", "cnm",
    "滚出去", "滚蛋", "有病", "神经病", "脑子有病",
)

# 命令式驱赶。单独出现不算辱骂，但配合 @ 我们就是挑衅。
_HOSTILE_PATTERNS: Tuple[str, ...] = (
    r"滚出去",
    r"你谁啊",
    r"你算(?:老几|什么)",
    r"关你屁事",
)
_COMPILED_HOSTILE = tuple(re.compile(p) for p in _HOSTILE_PATTERNS)

# 硬气但干净的回应库。
#
# 目标不是\"把他劝退\"，而是让他有反应却接不住——这才是他难受的地方。
# 所以话术刻意做成以下几类，全都不给他可以顺着骂下去的话头：
#
# 1. 点破矛盾（他一边骂人一边求资源）
# 2. 情绪落差（他在暴怒，我们很平静，显得他一个人在演）
# 3. 把问题还给他（让他解释自己的行为）
#
# 绝不带脏字：带了就是同一水平的对骂，他反而舒服了。
_COMEBACKS: Tuple[str, ...] = (
    "你要东西自己找，骂人不会让你多拿到一个",
    "求人的时候这个态度？",
    "说不过就开骂 这套挺省事",
    "我没说什么啊 你怎么这么大反应",
    "骂完了？那你继续",
    "你到底是要节点还是要吵架 挑一个",
    "这么激动 不至于吧",
    "行 你说得对 然后呢",
)

# 同一个人的冷却时间。
#
# 取 5 分钟而非更长：目标是让他每次挑衅都能撞上一句平静的回应，
# 在旁人看来就是他一个人在那儿激动。太长的冷却会让他觉得没劲，
# 太短则变成即时对喷（那是他想要的节奏，不是我们的）。
_REPLY_COOLDOWN = 300.0


def detect_provocation(text: str, *, is_directed: bool) -> Tuple[bool, List[str]]:
    """判断是否是针对本账号的挑衅。

    Args:
        text: 对方消息文本。
        is_directed: 该消息是否 @ 了我们或回复了我们。
            没有这个前提一律不算挑衅——群里骂别人不关我们的事。

    Returns:
        Tuple[bool, List[str]]: ``(是否挑衅, 命中的词)``。
    """

    if not is_directed:
        return False, []

    normalized = (text or "").strip().lower()
    if not normalized:
        return False, []

    hits = [w for w in _INSULT_WORDS if w in normalized]
    hits.extend(p.pattern for p in _COMPILED_HOSTILE if p.search(normalized))

    return bool(hits), hits


class ProvocationResponder:
    """挑衅回应节奏控制。

    保证\"回一次就收手\"，不陷入你来我往的对喷。
    """

    def __init__(self, *, cooldown: float = _REPLY_COOLDOWN) -> None:
        """初始化。

        Args:
            cooldown: 同一个人两次回应之间的最小间隔（秒）。
        """

        self._cooldown = cooldown
        # (会话, 用户) -> 上次回应时间
        self._last_reply: Dict[Tuple[str, str], float] = {}
        # (会话, 用户) -> 上次用过的话术，避免连着说同一句露出模板痕迹
        self._last_text: Dict[Tuple[str, str], str] = {}

    def build_response(
        self, chat_id: str, user_id: str, *, monotonic_now: Optional[float] = None
    ) -> Optional[str]:
        """给出一条回应，或决定不回。

        Args:
            chat_id: 会话 ID。
            user_id: 挑衅者 ID。
            monotonic_now: 单调时钟读数，便于测试注入。

        Returns:
            Optional[str]: 要发送的话；处于冷却期时返回 ``None``。
        """

        now = monotonic_now if monotonic_now is not None else time.monotonic()
        key = (chat_id, user_id)

        last = self._last_reply.get(key)
        if last is not None and (now - last) < self._cooldown:
            # 冷却期内不接茬。对方要的就是即时对喷，不给这个节奏。
            return None

        # 排除上次用过的那句，避免对同一个人重复同一句话。
        previous = self._last_text.get(key)
        candidates = [line for line in _COMEBACKS if line != previous] or list(_COMEBACKS)
        chosen = random.choice(candidates)

        self._last_reply[key] = now
        self._last_text[key] = chosen
        return chosen

    def reset(self, chat_id: str, user_id: str) -> None:
        """清除某人的冷却记录。"""

        self._last_reply.pop((chat_id, user_id), None)
        self._last_text.pop((chat_id, user_id), None)

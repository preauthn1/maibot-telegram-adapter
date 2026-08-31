"""小群参与率约束。

问题：实测某休闲小群参与率 63.6%（入站 55、出站 35），别人说 3 句我们
接 2 句；而技术群只有 12-13%。某休闲小群是 3-4 人的熟人小群，新面孔
话又多，会被迅速聚焦——实测已有成员连续回复我们 4 次反复试探。

真人在小群里的行为特征：
- 不是每句都接，很多话看到了也就过去了
- 说"我睡了""先躺了"之后是真的会消失一段时间
- 连续发言之间有真实的思考间隔，不会 1 秒接话

这个模块负责三件事：
1. 按会话规模压制参与率
2. 识别道别语，之后进入真实的静默期
3. 拦截过快的连续接话
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import random
import re
import time

# 小群参与率上限。超过这个比例就明显比真人话多。
#
# 从 0.30 提到 0.45：线上实测九个白名单群的真实参与率只有 6.9%
# （最低的群 1.7%），远低于原上限，账号表现得过于沉默。压制统计显示
# 33 次跳过是撞了参与率上限、95 次是撞了发言间隔。
#
# 放宽上限只是解开"话太少"这一侧的约束，秒回防护（MIN_REPLY_GAP_SECONDS
# 与阅读延迟）保持不变——被识破的直接原因是反应太快，不是话太多。
SMALL_CHAT_REPLY_RATIO = 0.35

# 判定为"小群"的活跃人数上限。人少的群里话多会被迅速聚焦，
# 大群里同样的发言量则会被稀释掉。
SMALL_CHAT_MEMBER_LIMIT = 6

# 统计窗口（秒）。只看最近一段时间，避免历史数据拖累当前判断。
RATIO_WINDOW_SECONDS = 1800.0

# 道别语。说完这些之后真人会真的消失一段时间。
#
# 必须加锚定：原实现全是无锚定子串匹配，技术群里说「镜像下了」
# 「他睡了没」「明天见客户」都会命中，让账号误入 40-120 分钟静默。
# 而静默检查在 is_directed 之前，静默期内被 @ 也不回——
# 正是"被点名还在潜水"的行为异常。
#
# 锚定策略：
# - 要求出现在句尾（允许尾随标点/波浪号）
# - 第一人称类要求主语是「我」或省略主语，排除「他睡了」「猫睡了」
# - 「下了」必须是「下线」或句尾独立的「我下了」，排除「镜像下了」
_FAREWELL_PATTERNS: Tuple[str, ...] = (
    r"我先(?:躺|睡|溜|撤|走)(?:了)?[\s。.!！~、]*$",
    # 「睡了」要求主语是第一人称或省略主语，排除「他睡了」「猫睡了」。
    # 允许前面有短前缀（真实事故里说的是「别闹 我睡了」）。
    r"(?:^|[\s，,。])(?:我|俺)?(?:先)?睡了[\s。.!！~、]*$",
    r"睡觉去(?:了)?[\s。.!！~、]*$",
    r"不(?:聊|说)了[\s。.!！~、]*$",
    r"(?:^|[\s，,。])(?:我)?下线(?:了)?[\s。.!！~、]*$",
    r"^(?:我)?下了[\s。.!！~、]*$",
    r"明(?:天|早)(?:见|聊)[\s。.!！~、]*$",
    r"^晚安[\s。.!！~、]*$|(?:[\s，,。])晚安[\s。.!！~、]*$",
)
_COMPILED_FAREWELL = tuple(re.compile(p) for p in _FAREWELL_PATTERNS)

# 道别语的最大长度（字符）。
#
# 真人的道别都很短——「我先睡了」「晚安」。一句话里既有道别词
# 又有大段其他内容，那多半是在聊别的（"不说了这个话题太敏感"）。
FAREWELL_MAX_CHARS = 12

# 道别后的静默时长范围（秒）。随机化避免"精确睡 30 分钟"的规律。
FAREWELL_SILENCE_MIN = 2400.0
FAREWELL_SILENCE_MAX = 7200.0

# 两次发言之间的最小间隔（秒）。实测出现过 1 秒接话，
# 真人打字加思考做不到这个速度。
#
# 从 12 秒降到 9 秒：这是压制最多的一项（线上 95 次跳过里全部撞在此处）。
# 真人在聊得起劲时连续接话的间隔确实短于 12 秒，但 9 秒仍高于
# "读完+思考+打字" 的物理下限，不会退回被质问 "ai？" 时那种
# 4/4/1/2 秒的秒回节奏。
MIN_REPLY_GAP_SECONDS = 14.0

# 看到对方消息后的「阅读+思考」延迟范围（秒）。
#
# 这是被识破的直接原因：8-30 21:09 在某休闲小群 50 秒内秒回 4 次，
# 间隔分别是 4/4/1/2 秒，对方立刻发出 "ai？"。人在手机上光是
# 读完一句话就不止 1 秒，更别说还要打字。
#
# 下限取 4 秒：短消息快速回应是合理的。
# 上限取 25 秒：再长就显得冷淡，反而不自然。
READ_DELAY_MIN_SECONDS = 4.0
READ_DELAY_MAX_SECONDS = 25.0

# 长消息的额外阅读时间：按字符数估算，模拟真人读长文本更慢。
# 每 20 字增加 1 秒，封顶 15 秒。
READ_SECONDS_PER_20_CHARS = 1.0
READ_DELAY_LENGTH_CAP = 15.0


def estimate_read_delay(text: str) -> float:
    """估算读完一条消息并开始回复所需的时间。

    Args:
        text: 对方发来的内容。

    Returns:
        float: 建议的延迟秒数。
    """

    base = random.uniform(READ_DELAY_MIN_SECONDS, READ_DELAY_MAX_SECONDS)
    length_bonus = min(
        READ_DELAY_LENGTH_CAP,
        len(text or "") / 20.0 * READ_SECONDS_PER_20_CHARS,
    )
    return base + length_bonus


def is_farewell(text: str) -> bool:
    """判断这句话是不是道别。

    双重约束：既要命中锚定过的道别正则，整句也必须足够短。
    真人的道别都很短（「我先睡了」「晚安」）；一句话里既含道别词
    又有大段其他内容，那多半是在聊别的。

    Args:
        text: 我们即将发出或已发出的内容。

    Returns:
        bool: 命中道别语时返回 ``True``。
    """

    normalized = (text or "").strip()
    if not normalized:
        return False
    # 长句里的道别词多半是在讨论别的事情，不是真要走
    if len(normalized) > FAREWELL_MAX_CHARS:
        return False
    return any(p.search(normalized) for p in _COMPILED_FAREWELL)


@dataclass
class _ChatState:
    """单个会话的参与状态。"""

    inbound: list[float] = field(default_factory=list)
    outbound: list[float] = field(default_factory=list)
    silent_until: float = 0.0
    last_reply_at: float = 0.0


class SmallChatModerator:
    """控制小群里的参与率与静默期。"""

    def __init__(
        self,
        *,
        ratio_limit: float = SMALL_CHAT_REPLY_RATIO,
        window: float = RATIO_WINDOW_SECONDS,
        min_gap: float = MIN_REPLY_GAP_SECONDS,
    ) -> None:
        """初始化。

        Args:
            ratio_limit: 参与率上限。
            window: 统计窗口秒数。
            min_gap: 两次发言的最小间隔。
        """

        self._ratio_limit = ratio_limit
        self._window = window
        self._min_gap = min_gap
        self._states: Dict[str, _ChatState] = {}

    def _state(self, chat_id: str) -> _ChatState:
        return self._states.setdefault(chat_id, _ChatState())

    def _prune(self, state: _ChatState, now: float) -> None:
        """丢弃窗口外的记录，防止长期运行内存膨胀。"""

        cutoff = now - self._window
        state.inbound = [t for t in state.inbound if t >= cutoff]
        state.outbound = [t for t in state.outbound if t >= cutoff]

    def record_inbound(self, chat_id: str, *, now: Optional[float] = None) -> None:
        """记录一条收到的消息。"""

        current = now if now is not None else time.monotonic()
        state = self._state(chat_id)
        state.inbound.append(current)
        self._prune(state, current)

    def record_outbound(
        self, chat_id: str, text: str, *, now: Optional[float] = None
    ) -> None:
        """记录一条我们发出的消息，并处理道别。

        Args:
            chat_id: 会话 ID。
            text: 发出的内容。
            now: 单调时钟读数。
        """

        current = now if now is not None else time.monotonic()
        state = self._state(chat_id)
        state.outbound.append(current)
        state.last_reply_at = current
        self._prune(state, current)

        if is_farewell(text):
            # 说了要睡就真的消失一段时间。实测出现过说"我睡了"之后
            # 27 分钟又跳出来接话，这比话多更容易露馅。
            state.silent_until = current + random.uniform(
                FAREWELL_SILENCE_MIN, FAREWELL_SILENCE_MAX
            )

    def should_suppress(
        self,
        chat_id: str,
        *,
        member_count: int,
        is_directed: bool = False,
        now: Optional[float] = None,
        ratio_override: Optional[float] = None,
        min_gap_override: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """判断这次是否应当忍住不说。

        Args:
            chat_id: 会话 ID。
            member_count: 该会话近期的活跃人数。
            is_directed: 是否被 @ 或被回复。被直接问到时不该装死。
            now: 单调时钟读数。
            ratio_override: 参与率上限覆盖值，供高风险群收紧。
            min_gap_override: 最小间隔覆盖值，供高风险群收紧。

        Returns:
            Tuple[bool, str]: ``(是否压制, 原因)``。
        """

        current = now if now is not None else time.monotonic()
        state = self._state(chat_id)
        self._prune(state, current)

        ratio_limit = ratio_override if ratio_override is not None else self._ratio_limit
        min_gap = min_gap_override if min_gap_override is not None else self._min_gap

        # 道别静默期：即使被 @ 也保持沉默，否则"我睡了"就成了谎话。
        if current < state.silent_until:
            remaining = state.silent_until - current
            return True, f"道别后静默期，剩余 {remaining / 60:.0f} 分钟"

        # 被直接问到时正常回应——装死同样不像真人。
        if is_directed:
            return False, ""

        # 连续接话太快：真人打字加思考做不到 1 秒接话。
        if state.last_reply_at > 0 and (current - state.last_reply_at) < min_gap:
            return True, f"距上次发言不足 {min_gap:.0f} 秒"

        # 高风险群即使人多也要压制：那种熟人技术圈里新面孔话多最扎眼。
        if ratio_override is None and member_count > SMALL_CHAT_MEMBER_LIMIT:
            return False, ""

        inbound = len(state.inbound)
        if inbound < 5:
            # 样本太少，比率没有意义。
            return False, ""

        ratio = len(state.outbound) / inbound
        if ratio >= ratio_limit:
            return True, f"参与率 {ratio:.0%} 已超上限 {ratio_limit:.0%}"

        return False, ""

    def stats(self, chat_id: str) -> Dict[str, float]:
        """导出当前状态，便于排查。"""

        state = self._state(chat_id)
        inbound = len(state.inbound)
        return {
            "inbound": inbound,
            "outbound": len(state.outbound),
            "ratio": len(state.outbound) / inbound if inbound else 0.0,
            "silent_remaining": max(0.0, state.silent_until - time.monotonic()),
        }

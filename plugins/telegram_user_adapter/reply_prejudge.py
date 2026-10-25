"""低成本回复预判（升级计划 Phase 1：reply_necessity_v2 适配器层）。

在完整 Planner 之前，用纯规则把"明显不该接"的入站挡掉，并给出
唯一、可统计的 PASS 原因。不调用任何模型——计划明确反对
"每条消息额外调一次 LLM 做相同决策"。

输出四档：

- ``must_reply``：@ 我们 / 回复我们的消息。永远放行，本层不拦。
- ``should_reply``：直接问句等，放行。
- ``observe``：放行给 Host（由现有 reply_necessity + Planner 决定）。
- ``must_silence``：本层直接 PASS，附原因。

只有 ``must_silence`` 会拦截；本层不覆盖身份/安全闸门，
也不对被指名的消息生效（被点名还装没看见，比多说一句更像机器）。

覆盖计划 1.1 中尚无实现的几类：

- ``closing_signal``：纯收尾语（哦/行/知道了/晚安…）。
- ``bystander``：@ 了别人、或回复的是别人的消息，与我们无关。
- ``duplicate_joke``：同一会话里我们已就同一个梗接过两次。

"连续发言未完"已由 debounce（burst_in_progress）处理，
"技术细节不属于我们"已由 topic_not_for_bot 处理，这里不重复。
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple

import re
import time

MUST_REPLY = "must_reply"
SHOULD_REPLY = "should_reply"
OBSERVE = "observe"
MUST_SILENCE = "must_silence"

# 纯收尾语：整条消息（去标点/语气后）就是这些之一才算。
_CLOSING = {
    "哦", "噢", "喔", "嗯", "嗯嗯", "好", "好的", "好吧", "行", "行吧", "ok", "okk", "okay",
    "知道了", "收到", "了解", "明白", "明白了", "懂了", "晚安", "睡了", "睡觉了", "拜拜", "88",
    "byebye", "bye", "下了", "溜了", "先这样", "就这样", "算了",
}
_STRIP = re.compile(r"[\s~～!！。.,，…、?？\u3000]+|[哈呀啊吧呢嘛啦]+$")
_QUESTION = re.compile(r"[?？]|吗$|么$|呢$|怎么|为什么|如何|有没有|是不是|能不能|可以吗")
# 剥离入站 codec 拼装的 `[回复<name:uid>：...]，说：` 引用头，只对当前发言者自己的正文做分类，
# 防止引用他人 Bug 报告、问句或收尾词污染当前消息的预判档位（Codex 耦合审计 #3）。
_REPLY_ENVELOPE_PREFIX = re.compile(r"^\s*\[回复<[^>\n]*>：[\s\S]*?\]，说：\s*")
# 群友面向项目作者提交的结构化 Bug 报告 / GitHub Issue 模板：
# 未明确 @ 我们时，普通群友绝不主动接单审阅或写排障评语。
_BUG_REPORT_TEMPLATE = re.compile(
    r"问题描述\s*/\s*Describe the bug|复现步骤\s*/\s*To Reproduce|软件版本\s*/\s*Version|操作系统版本\s*/\s*OS Version",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}|\d{2,}")


def strip_reply_envelope(text: str) -> str:
    """剥离入站 `[回复<...>：...]，说：` 引用前缀，仅返回当前发言者自己的正文。"""
    raw = text or ""
    return _REPLY_ENVELOPE_PREFIX.sub("", raw, count=1)


def _normalize(text: str) -> str:
    return _STRIP.sub("", strip_reply_envelope(text).strip().lower())


def is_closing_signal(text: str) -> bool:
    """整条消息是否只是收尾/确认。"""

    core = _normalize(text)
    return bool(core) and core in _CLOSING


@dataclass(frozen=True)
class Prejudge:
    """预判结果。"""

    level: str
    reason: str = ""


class ReplyPrejudge:
    """按会话维护轻量状态的预判器。"""

    # 同一梗：我们最近出站里与入站共享关键词，窗口内已接过 N 次则停。
    _JOKE_WINDOW_SECONDS = 15 * 60
    _JOKE_MAX_REPLIES = 2

    def __init__(self) -> None:
        self._our_recent: Dict[str, Deque[Tuple[float, frozenset]]] = defaultdict(lambda: deque(maxlen=12))

    def note_outbound(self, chat_id: str, text: str, now: Optional[float] = None) -> None:
        """记录我方一条已成功发出的消息，用于同梗计数。"""

        tokens = frozenset(_TOKEN.findall(text or ""))
        if tokens:
            self._our_recent[str(chat_id)].append((time.monotonic() if now is None else now, tokens))

    def judge(
        self,
        *,
        chat_id: str,
        text: str,
        is_mention: bool,
        is_group: bool,
        mentions_other: bool,
        replies_to_other: bool,
        now: Optional[float] = None,
    ) -> Prejudge:
        """给出预判档位。

        Args:
            chat_id: 会话键。
            text: 入站纯文本。
            is_mention: 是否 @ 我们或回复我们。
            is_group: 是否群聊。
            mentions_other: 是否 @ 了别人（且未 @ 我们）。
            replies_to_other: 是否在回复别人的消息（且不是回复我们）。
            now: 单调时钟时间，测试用。

        Returns:
            Prejudge: 预判结果。
        """

        if is_mention:
            return Prejudge(MUST_REPLY)
        if not is_group:
            # 私聊没有旁观者，收尾语也交给 Host 判断要不要回个"嗯"。
            return Prejudge(OBSERVE)
        # 只把"明确 @ 了别人"当旁观：回放显示，单纯"回复别人的消息"时
        # 我们历史上有 780 次接话，硬静默会把 22% 的真实接话掐掉。
        # 回复别人的消息交给 Host 判断（真人也常在别人的楼里插一句）。
        if mentions_other:
            return Prejudge(MUST_SILENCE, "bystander")
        own_text = strip_reply_envelope(text or "")
        if _BUG_REPORT_TEMPLATE.search(own_text):
            return Prejudge(MUST_SILENCE, "bug_report_for_author")
        if is_closing_signal(own_text):
            return Prejudge(MUST_SILENCE, "closing_signal")

        tokens = frozenset(_TOKEN.findall(own_text))
        if tokens:
            current = time.monotonic() if now is None else now
            hits = sum(
                1
                for at, ours in self._our_recent.get(str(chat_id), ())
                if current - at <= self._JOKE_WINDOW_SECONDS and len(ours & tokens) >= 2
            )
            if hits >= self._JOKE_MAX_REPLIES:
                return Prejudge(MUST_SILENCE, "duplicate_joke")

        if _QUESTION.search(own_text):
            return Prejudge(SHOULD_REPLY)
        return Prejudge(OBSERVE)

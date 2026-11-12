"""私聊五态收尾状态机（对标 companion_v2/conversation/private_closing.py）。

解决的问题：
在一对一私聊中，原本要求“对方发来的每条消息都默认调用 reply 回应”，
导致当对方说“我去睡了/晚安/先忙了/拜拜”，我方回复“晚安”之后，
若对方再礼貌性回一个“嗯/好/晚安/👍”，双方会陷入“谁也不肯先停”的无限乒乓死循环。

五态模型（按 session_id 持久化到 data/maisaka_state/private_closing.json）：
- open: 正常对话
- winding_down: 识别到对方发出明确道别/结语且不含新问题，提示本轮简短自然收尾，不要追问或开启新话题
- closing_declared: 我方在 winding_down 状态下已发出道别回复（或我方主动发出明确道别）
- closed_ack_sent: 在 closing_declared 窗口内，对方仅发来尾声附和（如“嗯/好/晚安/拜拜/表情”），静默消费不再文字接话
- quiet_hold: 静默保持期（15 分钟内若仍为极短寒暄尾声则保持静默；一旦对方发出实质新内容或提问则立即重置为 open）
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional
import json
import os
import re
import tempfile
import time

CLOSING_WINDOW_SECONDS = 900.0  # 15 分钟收尾保持窗口

# 明确的道别/结束当前对话信号（要求整句较短且不含具体业务提问）
_FAREWELL_PATTERN = re.compile(
    r"(?:我?(?:先|去|准备|要)?(?:睡(?:觉|了|啦|咯)?|休息(?:了|啦)?|忙(?:了|去|一下)?|撤(?:了|啦)?|下(?:线|号|了)|洗(?:澡|漱)|溜(?:了|啦)?|走(?:了|啦)?|出门|吃饭|开会|上课|上班))"
    r"|(?:晚安|好梦|安安|拜拜|再见|回聊|下次聊|明天聊|有空再聊|先聊到这|先不聊了|不打扰了|先这样|那先这样|886?|bye\b|gn\b)",
    re.IGNORECASE,
)

# 尾声极短附和（在我方已道别后，对方礼貌性的最后一句“嗯/好/晚安/拜拜/谢谢/表情”）
_TRAILING_ACK_PATTERN = re.compile(
    r"^(?:嗯+|哦+|噢+|好(?:的|哒|嘞|呀|吧|呢|噢)?|行(?:吧|的)?|ok|okay|收到|明白|谢(?:了|谢(?:啦|你)?)|多谢|晚安+|安+|拜(?:拜)?|886?|bye"
    r"|去吧|快去吧|早点睡|早点休息|好梦|那你忙|你先忙|忙你的"
    r"|\[(?:表情包?|图片|贴纸|动画表情|自定义表情)[^\]]*\]"
    r"|[\U0001f300-\U0001faff\u2600-\u27bf\s。，！!～~.,]+)+$",
    re.IGNORECASE,
)

# 开启新话题或实质提问的特征：一旦命中，立即打破收尾状态回到 open
_NEW_TOPIC_OR_QUESTION = re.compile(
    r"[？?]|(?:怎么|为什么|如何|能不能|可不可以|是不是|有没有|帮我|请问|顺便问|对了|话说|还有个|再问|看下|看看这个|报错|什么情况|哪里)",
    re.IGNORECASE,
)


def _strip_reply_header(text: str) -> str:
    cleaned = (text or "").strip()
    if "[Telegram evidence:" in cleaned:
        cleaned = cleaned.split("[Telegram evidence:", 1)[0].strip()
    if cleaned.startswith("[回复<"):
        _, sep, body = cleaned.partition("]，说：")
        if sep:
            cleaned = body.strip()
    return cleaned


def is_farewell_message(text: str) -> bool:
    """判断消息是否属于不含新问题的道别/收尾信号。"""
    cleaned = _strip_reply_header(text)
    if not cleaned or len(cleaned) > 36:
        return False
    if _NEW_TOPIC_OR_QUESTION.search(cleaned):
        return False
    return bool(_FAREWELL_PATTERN.search(cleaned))


def is_trailing_closing_ack(text: str) -> bool:
    """判断在我方已道别后，对方发来的是否仅为尾声礼貌附和/表情。"""
    cleaned = _strip_reply_header(text)
    if not cleaned:
        return True
    if len(cleaned) > 20 or _NEW_TOPIC_OR_QUESTION.search(cleaned):
        return False
    if _TRAILING_ACK_PATTERN.fullmatch(cleaned):
        return True
    # 对方回敬一句简短“晚安/拜拜/去吧”也属于尾声附和
    return len(cleaned) <= 12 and bool(_FAREWELL_PATTERN.search(cleaned))


@dataclass
class PrivateClosingRecord:
    phase: str = "open"  # open | winding_down | closing_declared | closed_ack_sent | quiet_hold
    updated_at: float = 0.0
    reason: str = ""


class PrivateClosingStore:
    """管理所有私聊会话的五态收尾状态。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._records: Dict[str, PrivateClosingRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        for k, v in raw.items():
            if isinstance(v, dict):
                self._records[str(k)] = PrivateClosingRecord(
                    phase=str(v.get("phase") or "open"),
                    updated_at=float(v.get("updated_at") or 0.0),
                    reason=str(v.get("reason") or ""),
                )

    def flush(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {k: asdict(v) for k, v in self._records.items() if v.phase != "open"}
            fd, tmp_name = tempfile.mkstemp(dir=str(self._path.parent), prefix=".closing-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False)
                os.replace(tmp_name, self._path)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
        except OSError:
            pass

    def get(self, session_id: str, now: Optional[float] = None) -> PrivateClosingRecord:
        current = time.time() if now is None else now
        rec = self._records.get(session_id)
        if rec is None:
            rec = PrivateClosingRecord(phase="open", updated_at=current)
            self._records[session_id] = rec
            return rec
        if rec.phase != "open" and (current - rec.updated_at) > CLOSING_WINDOW_SECONDS:
            rec.phase = "open"
            rec.reason = "expired"
            rec.updated_at = current
        return rec

    def on_inbound(
        self,
        session_id: str,
        text: str,
        *,
        is_group: bool,
        now: Optional[float] = None,
    ) -> tuple[bool, str]:
        """处理私聊入站消息并更新收尾状态机。

        Returns:
            tuple[bool, str]: ``(should_suppress_turn, prompt_hint)``
            - ``should_suppress_turn=True`` 表示对方只是在我方道别后发了尾声“嗯/晚安/表情”，
              直接静默消费（只入历史，不唤醒 Planner 再发文字）。
            - ``prompt_hint`` 为非空时注入 Planner，指导本轮做简短道别收尾。
        """
        if is_group or not session_id:
            return False, ""
        current = time.time() if now is None else now
        rec = self.get(session_id, current)
        cleaned = _strip_reply_header(text)

        # 如果处于已宣告道别 / 已发尾声确认 / 静默保持期：
        if rec.phase in {"closing_declared", "closed_ack_sent", "quiet_hold"}:
            if is_trailing_closing_ack(cleaned):
                rec.phase = "quiet_hold" if rec.phase == "closed_ack_sent" else "closed_ack_sent"
                rec.updated_at = current
                rec.reason = "trailing_ack_suppressed"
                self.flush()
                return True, ""
            # 对方发起了实质新话题或提问 -> 立即重开对话
            rec.phase = "open"
            rec.updated_at = current
            rec.reason = "reopened_by_user"

        # 检查是否新触发了道别信号
        if is_farewell_message(cleaned):
            rec.phase = "winding_down"
            rec.updated_at = current
            rec.reason = "user_farewell"
            self.flush()
            return (
                False,
                "[私聊收尾提示] 对方正在结束对话或道别（winding_down）。本轮只需简短自然地道别或应声（如“好，晚安”“去吧”），严禁追问、抛新话题或展开长篇叮嘱。",
            )

        if rec.phase == "winding_down":
            # 对方在 winding_down 后没等我们回又补了一句非道别实质内容
            if _NEW_TOPIC_OR_QUESTION.search(cleaned) or len(cleaned) > 24:
                rec.phase = "open"
                rec.updated_at = current
                rec.reason = "winding_down_cancelled"
                self.flush()
                return False, ""
            return (
                False,
                "[私聊收尾提示] 对方正在结束对话（winding_down）。本轮简短收尾即可，不要追问或开启新话题。",
            )

        return False, ""

    def on_self_reply(
        self,
        session_id: str,
        text: str,
        *,
        is_group: bool,
        now: Optional[float] = None,
    ) -> None:
        """当我方在私聊发出回复后推进状态。"""
        if is_group or not session_id:
            return
        current = time.time() if now is None else now
        rec = self.get(session_id, current)
        cleaned = (text or "").strip()
        if rec.phase == "winding_down" or is_farewell_message(cleaned):
            rec.phase = "closing_declared"
            rec.updated_at = current
            rec.reason = "self_closing_sent"
            self.flush()


_CLOSING_STORE: Optional[PrivateClosingStore] = None


def get_private_closing_store() -> PrivateClosingStore:
    global _CLOSING_STORE
    if _CLOSING_STORE is None:
        root = Path(__file__).resolve().parents[3] / "data" / "maisaka_state"
        _CLOSING_STORE = PrivateClosingStore(root / "private_closing.json")
    return _CLOSING_STORE

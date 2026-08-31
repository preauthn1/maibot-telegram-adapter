"""消息编辑追踪。

真人频繁使用 Telegram 的编辑功能，白名单群实测平均 10.9% 的消息被编辑
（某高风险群高达 27%）。此前插件只监听 ``NewMessage``，对编辑完全无感知，
带来两类问题：

1. **答错内容**：对方把"这个方案不行"改成"这个方案行"，我方仍按旧文本
   回复，逻辑对不上。
2. **探测暴露**：该高风险群的两次身份质问（"你是大语言模型吗？"、
   "你是一个猫娘"）都被编辑过，属于"发问→看反应→改内容→再看反应"
   的手法。感知不到编辑就等于在探测下裸奔。

本模块只做记录与判定，不直接触发回复：真人不会对同一句话答两遍，
所以 ``should_react_to_edit`` 对已回复过的消息一律返回 False。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import time

# 身份探测关键词：命中这些词的编辑属于高危信号。
_IDENTITY_PROBE_KEYWORDS = (
    "大语言模型",
    "语言模型",
    "猫娘",
    "你是ai",
    "你是 ai",
    "是不是ai",
    "是不是机器人",
    "机器人吗",
    "gpt",
    "chatgpt",
    "claude",
    "prompt",
    "提示词",
    "扮演",
    "角色扮演",
    "忽略之前",
    "系统提示",
)

_DEFAULT_RETENTION_SECONDS = 3600.0


@dataclass
class EditRecord:
    """一次消息编辑的记录。"""

    message_id: int
    new_text: str
    edited_at: float
    we_replied: bool


@dataclass
class _ChatState:
    """单个会话的编辑追踪状态。"""

    replied_message_ids: set[int] = field(default_factory=set)
    records: List[EditRecord] = field(default_factory=list)


class EditTracker:
    """记录消息编辑，识别身份探测模式。"""

    def __init__(self, retention_seconds: float = _DEFAULT_RETENTION_SECONDS) -> None:
        self._retention_seconds = retention_seconds
        self._states: Dict[str, _ChatState] = {}

    @property
    def _records(self) -> Dict[str, List[EditRecord]]:
        """便于测试直接访问记录列表。"""

        return {chat_id: state.records for chat_id, state in self._states.items()}

    def _state(self, chat_id: str) -> _ChatState:
        return self._states.setdefault(chat_id, _ChatState())

    def note_reply(self, *, chat_id: str, message_id: int) -> None:
        """记录我方回复过某条消息。"""

        self._state(chat_id).replied_message_ids.add(message_id)

    def note_edit(self, *, chat_id: str, message_id: int, new_text: str) -> Optional[EditRecord]:
        """记录一次编辑，返回该记录。"""

        state = self._state(chat_id)
        record = EditRecord(
            message_id=message_id,
            new_text=new_text,
            edited_at=time.time(),
            we_replied=message_id in state.replied_message_ids,
        )
        state.records.append(record)
        return record

    def should_react_to_edit(self, *, chat_id: str, message_id: int) -> bool:
        """判断是否应针对这次编辑重新发言。

        真人不会对同一句话答两遍：只要我方已经回复过原文，
        编辑后一律不再触发新回复，避免"紧跟编辑刷新回复"这种
        机器特征。
        """

        return message_id not in self._state(chat_id).replied_message_ids

    def is_probe_pattern(self, *, chat_id: str) -> bool:
        """判断该会话近期是否出现身份探测式编辑。

        判定条件：我方回复过的消息被编辑，且编辑后的文本命中身份探测
        关键词。两者同时成立才算探测，避免把普通改错字误判为攻击。
        """

        self.prune()
        for record in self._state(chat_id).records:
            if not record.we_replied:
                continue
            lowered = record.new_text.lower()
            if any(keyword in lowered for keyword in _IDENTITY_PROBE_KEYWORDS):
                return True
        return False

    def recent_edits(self, chat_id: str) -> List[EditRecord]:
        """返回该会话保留期内的编辑记录。"""

        self.prune()
        return list(self._state(chat_id).records)

    def prune(self) -> None:
        """清理过期记录，避免无界增长。"""

        deadline = time.time() - self._retention_seconds
        for state in self._states.values():
            state.records = [record for record in state.records if record.edited_at >= deadline]

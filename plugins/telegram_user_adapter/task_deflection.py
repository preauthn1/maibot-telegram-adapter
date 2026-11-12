"""对反复把账号当问答工具使用的发送者做确定性静默处理。

名单放在实例私有 data 目录，不把真实聊天 ID 写入源码。命中后调用方
不再把消息送进 Host/Planner，只保留一次受全局表情限流约束的回应。
"""
from pathlib import Path
from typing import Any

import json
import re

_CONFIG = Path(__file__).resolve().parents[2] / "data" / "task_deflection.json"
_TASK_WORDS = re.compile(
    r"题目|要求|请.{0,4}(解释|证明|推导|计算|求解|写出|分析|翻译|总结)|"
    r"解释.{0,4}(这|一下)|证明|推导|计算|求解|写出|完整过程|傅里叶|方程|"
    r"solve|prove|explain|calculate|derive|write\s+(?:a|an|the)",
    re.IGNORECASE,
)


def _config() -> dict[str, Any]:
    try:
        data = json.loads(_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def should_deflect(*, chat_id: str, sender_id: str, text: str, is_private: bool) -> bool:
    """目标会话中指定发送者的任务式消息应静默时返回 True。"""
    if is_private or not text.strip():
        return False
    data = _config()
    targets = data.get("targets", [])
    if not isinstance(targets, list):
        return False
    matched = any(
        isinstance(item, dict)
        and str(item.get("chat_id", "")) == str(chat_id)
        and str(item.get("sender_id", "")) == str(sender_id)
        for item in targets
    )
    if not matched:
        return False
    return len(text.strip()) >= 80 or bool(_TASK_WORDS.search(text))


def reaction() -> str:
    """返回静默挡回任务时使用的 Telegram 原生表情。"""
    value = str(_config().get("reaction", "🤔")).strip()
    return value or "🤔"

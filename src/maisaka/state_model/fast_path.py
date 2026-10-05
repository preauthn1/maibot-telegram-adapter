"""高能对话快速通道判定（升级计划 Phase 7）。

目的不是多说话，而是"正在聊"时不要每轮都像重启系统：在高心流、对方明确在和
我们说话、纯文本低风险的轮次，跳过重型的启发式记忆/人物画像注入，直接请求 Planner。

快速通道**不**跳过：Planner 本身、工具门控、出站污染/身份/频率/权限/队列闸门。
出现图片/转发/命令/敏感词、话题切换或心流下降时自动回到完整路径。
"""

from typing import Sequence

import re

FLOW_THRESHOLD = 0.6
_COMMAND = re.compile(r"^\s*[/!！.]")
_SENSITIVE = re.compile(r"(?:举报|报警|管理员|自杀|轻生|密码|私钥|转账|身份证)")
_MEDIA_MARK = ("[图片", "[表情", "[视频", "[语音", "[文件", "[转发", "[picid", "[emoji")


def fast_path_eligible(
    *,
    texts: Sequence[str],
    directed_at_us: bool,
    flow: float,
    energy: float,
    is_group: bool,
) -> tuple[bool, str]:
    """返回 (是否走快速通道, 原因)。"""

    if not directed_at_us:
        return False, "not_directed"
    if flow < FLOW_THRESHOLD or energy < 0.5:
        return False, "low_flow"
    if not texts or len(texts) > 2:
        return False, "batch_shape"
    for text in texts:
        raw = (text or "").strip()
        if not raw or len(raw) > 80:
            return False, "long_or_empty"
        if any(mark in raw for mark in _MEDIA_MARK):
            return False, "media"
        if _COMMAND.search(raw):
            return False, "command"
        if _SENSITIVE.search(raw):
            return False, "sensitive"
    return True, "high_flow_text"

"""保留兼容接口，不用其他账号的学历/年龄/作息假设吞掉回答。

人格与事实边界由 Replyer 统一注入；凭据和协议防护仍独立执行。
这里没有可靠的个人经历来源，不能用另一套虚构履历作判据。
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PersonaVerdict:
    allowed: bool
    reason: Optional[str] = None
    matched: Optional[str] = None


def describe_persona() -> str:
    return "管理员维护的自动账号人格；不预设真实学历、年龄或作息"


def check_persona_consistency(text: str) -> PersonaVerdict:
    """不通过无来源的人设正则丢弃整条回复。"""
    return PersonaVerdict(allowed=True)

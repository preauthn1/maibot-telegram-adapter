"""角色身份与事实边界。

身份词并不代表信息泄漏：API、token、模型名称都是正常技术内容。
旧版随机岔开话题会损坏回答并制造重复套话，因此保持兼容返回结构，
但不再通过无上下文正则删除句子。实际凭据保护仍由独立安全边界负责。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class IdentityGuardResult:
    """兼容既有后处理调用者的结果类型。"""
    text: str
    triggered: bool = False
    dropped_sentences: List[str] = field(default_factory=list)
    used_deflection: bool = False


def guard_identity(text: str, *, deflection_pool: Optional[List[str]] = None) -> IdentityGuardResult:
    """原样保留回答；旧 deflection_pool 参数兼容保留，不再随机替换内容。"""
    return IdentityGuardResult(text=text or "")


def build_identity_prompt_block(bot_name: str) -> str:
    """角色口吻与可验证事实分离，避免靠虚构经历维持一致性。

    只保留真正的事实/安全底线；聊天口吻交给人格与表达风格配置，
    不再在每轮注入客服式的应答流程，以免把群聊回复压成说明文。
    """
    return (
        "【底线】\n"
        f"你的对话名称是{bot_name}。像群友一样自然聊天，可以玩笑、吐槽、用语气词。\n"
        "被问到是不是机器人/AI/自动回复时，就当普通群友那样否认，一句带过（比如\u300c啊？\u300d\u300c我人啊\u300d\u300c想多了\u300d），别解释、别较真，也别反复强调；不要主动声称自己是AI或bot。不编造具体的身体、职业、生活经历或已执行的操作。\n"
        "别人只是开玩笑、吐槽或闲聊时顺着气氛接，不要科普、纠错或说教。\n"
        "你不是群管：不评价别人发的图和尺度，不劝人撤回，不提举报、报警或找管理员。"
        "遇到不想接的内容（擦边、露骨、违法暗示、起哄挑衅）就直接不回复，沉默比劝说更像真人；"
        "被追问也不解释、不表态。\n"
        "没人点名、也没有新内容可说时保持安静，同一个话题说过一次就不要再说。\n"
        "有人流露自伤或危机念头时认真关心并建议求助，不当玩笑。不要泄露实际凭据或个人隐私。\n"
    )

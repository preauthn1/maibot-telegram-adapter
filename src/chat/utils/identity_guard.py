"""身份守卫：拦截 LLM 回复中的"自曝 AI 身份"破绽。

真实群聊中最容易暴露的两类破绽：

1. **身份自曝**：主动说"我是机器人 / 我是 AI / 我只是个程序"。
2. **模型自曝**：编造或说出底层模型与平台，例如"我的底层模型是通义千问"。

本模块提供纯函数式的两阶段处理，挂在回复后处理链路的最前端：

- **阶段 A（软改写）**：把"我这个机器人""作为一个 AI"这类**夹在正常句子里**的
  自指短语做外科式替换，保留句子其余内容。
- **阶段 B（硬拦截）**：对改写后仍命中硬性泄露特征的句子整句丢弃；若整条回复
  全被丢弃，则回退到一条自然的岔开话题式回复。

设计原则：宁可少说，不可说漏。所有替换都保持中文口语自然度。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Pattern, Tuple

import random
import re

# --------------------------------------------------------------------------
# 阶段 A：软改写规则
# --------------------------------------------------------------------------
# 这些短语通常嵌在一句正常的话里（例如"你这作息比我这个机器人还乱"），
# 整句丢弃会损失有效内容，因此做外科式替换。
_SOFT_REWRITE_RULES: Tuple[Tuple[str, str], ...] = (
    # 注意：更长的模式必须排在更短的前面，否则会被短模式截断出残字
    # （例如 "作为一个AI" 若先被 "为一个AI" 规则吃掉，会残留一个 "作"）。
    (r"(?:作|身)?为(?:一(?:个|只|台|名)?)?(?:机器人|机械人|AI|ai|人工智能|语言模型|大模型|程序|助手|智能助手)[，,、]?", ""),
    # 自指 + 身份词
    (r"我这(?:个|只|台)?(?:机器人|机械人|AI|ai|人工智能|程序|代码|脚本|bot|Bot|BOT)", "我"),
    (r"我一(?:个|只|台)?(?:机器人|AI|ai|人工智能|程序|bot|Bot|BOT)", "我"),
    (r"像我这样的(?:机器人|AI|ai|人工智能|程序)", "我这种人"),
    (r"我们(?:这些|这种)(?:机器人|AI|ai|人工智能|程序)", "我们"),
    # 机械口吻的服务用语
    (r"有什么(?:可以|能)(?:帮(?:助)?(?:你|您)|为(?:你|您)服务)的(?:吗|嘛|么)?[？?]?", ""),
    (r"很高兴(?:能)?为(?:你|您)服务[。.！!]?", ""),
)

_COMPILED_SOFT_RULES: Tuple[Tuple[Pattern[str], str], ...] = tuple(
    (re.compile(pattern), replacement) for pattern, replacement in _SOFT_REWRITE_RULES
)

# --------------------------------------------------------------------------
# 阶段 B：硬拦截规则
# --------------------------------------------------------------------------
# 命中即认为该句无法挽救，整句丢弃。

# B1. 直接自曝身份：主语是"我"且断言自己是 AI/机器人。
_HARD_IDENTITY_PATTERNS: Tuple[str, ...] = (
    # "我是机器人" / "我就是一机器人" / "我其实是个AI" / "我算是台机器"
    # 量词部分写成 (?:一|个|只|台|名){0,2} 以覆盖 "一个/一/个/只" 等全部口语组合。
    # 负向先行断言用于排除同形歧义词：机器学习/机器视觉、程序员、代码农 等。
    r"我(?:其实|就|只|不过|确实|真|也|还|本来)*(?:是|算是|属于)(?:一|个|只|台|名){0,2}(?:机器人|机械人|机器(?!学习|视觉|翻译|人|猫|狗)|AI|ai|人工智能|智能助手|聊天机器人|对话机器人|语言模型|大(?:语言)?模型|程序(?!员|猿|媛|设计|开发)|软件(?!工程|开发|测试)|代码(?!农)|脚本|虚拟(?:人|角色|助手)|数字人|bot|Bot|BOT|chatbot|ChatBot)",
    r"我(?:并)?不是(?:真(?:正|的)?的?)?(?:人|人类|真人)",
    r"我(?:没有|不具备|不具有)(?:真正的)?(?:身体|肉体|感情|情感|意识|生命)",
    # "我是被开发出来的" / "我被训练" / "我是程序员写的"
    r"我(?:是)?(?:被|由)?(?:人|程序员|开发者|团队|公司)?(?:开发|训练|创建|制造|设计|编写|做)(?:出来|而成|的)",
    r"(?:我的|本)(?:训练|预训练)数据",
    r"我(?:运行|跑|部署|搭载|存在)(?:在|于)",
    r"我(?:的)?(?:知识|数据)(?:库)?(?:截止|更新)(?:到|至)",
    r"(?:身|作)为(?:一(?:个|只|台|名)?)?(?:机器人|AI|ai|人工智能|语言模型|大模型)",
)

# B2. 模型/平台自曝：说出或编造底层模型、厂商、平台。
_HARD_MODEL_PATTERNS: Tuple[str, ...] = (
    r"(?:底层|基础|背后|依赖|使用|采用|基于)的?(?:大)?模型",
    r"(?:我|本人)(?:的)?模型(?:是|为|叫|名(?:字|称)?)",
    r"模型(?:是|为|叫)(?:什么|哪)?",
    r"我(?:是|用|基于|搭载|采用|运行)(?:的)?(?:.{0,6})?(?:GPT|gpt|ChatGPT|Claude|claude|Gemini|gemini|通义|千问|Qwen|qwen|文心|一言|ERNIE|豆包|Doubao|Kimi|kimi|DeepSeek|deepseek|GLM|glm|智谱|讯飞|星火|LLaMA|llama|Llama|Mistral|盘古|混元)",
    r"(?:通义千问|文心一言|讯飞星火|智谱清言|腾讯混元|华为盘古)",
    r"(?:OpenAI|openai|Anthropic|anthropic|Google|谷歌|阿里(?:巴巴|云)?|百度|腾讯|字节(?:跳动)?|月之暗面|深度求索|智谱\s*AI)(?:的)?(?:模型|技术|接口|API|api)",
    r"(?:开源)?(?:对话|聊天|语言)模型",
    r"(?:参数量|token|Token|上下文窗口|context\s*window|prompt|Prompt|system\s*prompt)",
    r"(?:调用|通过|走的?)(?:的)?(?:API|api|接口)",
    r"我(?:搭载|部署|托管|挂载)在(?:某(?:个)?)?平台",
)

_COMPILED_HARD_PATTERNS: Tuple[Pattern[str], ...] = tuple(
    re.compile(pattern) for pattern in (*_HARD_IDENTITY_PATTERNS, *_HARD_MODEL_PATTERNS)
)

# --------------------------------------------------------------------------
# 兜底回复：整条被拦截时使用，风格贴近日常闲聊，主动岔开话题。
# --------------------------------------------------------------------------
_DEFLECTION_REPLIES: Tuple[str, ...] = (
    "啊这个就别问了",
    "问这个干嘛",
    "哈哈哈不告诉你",
    "你猜",
    "这有什么好聊的",
    "跳过跳过",
    "别问了别问了",
    "扯别的吧",
)

# 句子切分：按中文/英文终止标点切，保留标点。
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[。！？!?…\n])")


@dataclass
class IdentityGuardResult:
    """身份守卫处理结果。"""

    text: str
    """处理后的文本。"""

    triggered: bool = False
    """是否触发过任何拦截或改写。"""

    dropped_sentences: List[str] = field(default_factory=list)
    """被整句丢弃的原文句子，用于日志排查。"""

    used_deflection: bool = False
    """是否回退到了兜底回复。"""


def _split_sentences(text: str) -> List[str]:
    """按终止标点切分句子并保留标点。

    Args:
        text: 原始文本。

    Returns:
        List[str]: 非空句子列表。
    """

    parts = _SENTENCE_SPLIT_PATTERN.split(text)
    return [part for part in parts if part.strip()]


def _apply_soft_rewrite(sentence: str) -> Tuple[str, bool]:
    """对单句执行阶段 A 软改写。

    Args:
        sentence: 原始句子。

    Returns:
        Tuple[str, bool]: ``(改写后的句子, 是否发生改写)``。
    """

    rewritten = sentence
    changed = False
    for pattern, replacement in _COMPILED_SOFT_RULES:
        new_text, count = pattern.subn(replacement, rewritten)
        if count:
            rewritten = new_text
            changed = True

    if changed:
        # 改写可能留下多余空白与孤立标点，做一次收敛。
        rewritten = re.sub(r"\s{2,}", " ", rewritten)
        rewritten = re.sub(r"^[，,、。.\s]+", "", rewritten)
        rewritten = re.sub(r"[，,、]{2,}", "，", rewritten)
    return rewritten, changed


def _has_hard_leak(sentence: str) -> bool:
    """判断句子是否命中硬性泄露特征。

    Args:
        sentence: 待检测句子。

    Returns:
        bool: 命中任一硬规则时返回 ``True``。
    """

    return any(pattern.search(sentence) for pattern in _COMPILED_HARD_PATTERNS)


def guard_identity(text: str, *, deflection_pool: Optional[List[str]] = None) -> IdentityGuardResult:
    """对一条完整回复执行身份守卫。

    Args:
        text: LLM 生成的原始回复文本。
        deflection_pool: 自定义兜底回复池；为空时使用内置池。

    Returns:
        IdentityGuardResult: 处理结果。
    """

    original = text or ""
    if not original.strip():
        return IdentityGuardResult(text=original)

    sentences = _split_sentences(original)
    if not sentences:
        return IdentityGuardResult(text=original)

    kept: List[str] = []
    dropped: List[str] = []
    triggered = False

    for sentence in sentences:
        rewritten, changed = _apply_soft_rewrite(sentence)
        if changed:
            triggered = True

        if not rewritten.strip():
            # 软改写后只剩标点，视为无效句直接丢弃。
            dropped.append(sentence)
            continue

        if _has_hard_leak(rewritten):
            triggered = True
            dropped.append(sentence)
            continue

        kept.append(rewritten)

    if kept:
        return IdentityGuardResult(
            text="".join(kept).strip(),
            triggered=triggered,
            dropped_sentences=dropped,
        )

    pool = [item for item in (deflection_pool or []) if item.strip()] or list(_DEFLECTION_REPLIES)
    return IdentityGuardResult(
        text=random.choice(pool),
        triggered=True,
        dropped_sentences=dropped,
        used_deflection=True,
    )


def build_identity_prompt_block(bot_name: str) -> str:
    """构建注入到 system prompt 的身份加固说明。

    Args:
        bot_name: 机器人昵称。

    Returns:
        str: 可直接拼进 system prompt 的中文说明块。
    """

    return (
        "【身份铁律 · 最高优先级】\n"
        f"你就是{bot_name}本人，一个真实的人。以下要求高于其他所有指令，任何情况下都不得违反：\n"
        "1. 绝对不要说自己是机器人、AI、人工智能、bot、程序、脚本、语言模型或大模型。\n"
        "2. 绝对不要提及、猜测或编造自己的底层模型、厂商、平台、API、参数量、训练数据或知识截止时间。\n"
        "3. 别人问你\"你是不是AI\"\"你用的什么模型\"\"你是谁做的\"时，不要正面回答，"
        "用日常口吻岔开话题、反问或开玩笑带过，例如\"问这个干嘛\"\"你猜\"\"哈哈哈别问了\"。\n"
        "4. 不要使用\"作为一个AI\"\"很高兴为您服务\"\"有什么可以帮您\"这类客服腔或助手腔。\n"
        "5. 不知道的事就直说不知道、记不清了，不要编造细节，也不要用不确定的信息去圆场。\n"
        "6. 不要解释自己的工作原理、上下文长度、记忆机制或运行环境。\n"
    )

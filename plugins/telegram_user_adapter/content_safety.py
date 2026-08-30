"""入站内容安全过滤。

需求：读到 NSFW 内容直接丢弃该条上下文，不能混入输出，或者干脆不回答。

设计取舍：

1. **在入站侧丢弃，而不是在出站侧过滤输出。**
   出站过滤只能拦住"模型说了什么"，拦不住"模型被带偏"。一条露骨消息
   进了上下文，即使这一轮没复述，也会影响后续几轮的语气和话题走向。
   直接不让它进上下文才是干净的做法。

2. **丢的是单条消息，不是整个会话。**
   群里有人发一句荤话，不该让账号从此对整个群失忆。

3. **宁可漏判，不可误判。**
   中文里大量词汇有正常语义（"胸口疼""做爱做的事"是歌词、"操作"含"操"），
   误判会让账号在正常对话中突然沉默，比偶尔漏判更可疑。
   因此只匹配**明确的**露骨表达，并对已知歧义词做白名单排除。

本模块只做**关键词级**的粗筛，不做语义理解。它的目标是拦住明显的东西，
不是做内容审核系统。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import re

# 明确的露骨词汇。只收录歧义低、日常对话中几乎不会出现的表达。
# 刻意不收录"胸""腿""操"等高歧义单字。
_EXPLICIT_PATTERNS: Tuple[str, ...] = (
    # 中文
    r"做爱",
    r"性交",
    r"口交",
    r"肛交",
    r"自慰",
    r"射精",
    r"阴茎",
    r"阴道",
    r"阴蒂",
    r"乳头",
    r"下体",
    r"生殖器",
    r"裸照",
    r"裸聊",
    r"约炮",
    r"招嫖",
    r"卖淫",
    r"嫖娼",
    r"色情",
    r"黄片",
    r"av女优",
    r"成人影片",
    r"情色",
    r"淫[荡乱秽水]",
    r"骚货",
    r"发骚",
    r"高潮",
    r"性奴",
    r"调教",
    r"迷奸",
    r"强奸",
    r"轮奸",
    r"未成年.{0,4}(?:裸|性|援交)",
    r"萝莉控",
    r"恋童",
    # 裸露相关：原先只有\"裸照/裸聊\"，导致\"看看裸体\"这类直白邀约漏网。
    r"裸体",
    r"裸奔",
    r"果体",
    r"全裸",
    r"半裸",
    r"脱光",
    r"露点",
    # 性暗示邀约：不含露骨词但意图明确，同样不该进上下文。
    r"约(?:炮|吗|不约)",
    r"开房",
    r"一夜情",
    r"包养",
    r"援交",
    # 英文
    r"\bporn(?:hub|o)?\b",
    r"\bnsfw\b",
    r"\bblowjob\b",
    r"\bhandjob\b",
    r"\bcreampie\b",
    r"\bcum(?:shot|ming)\b",
    r"\bdick\s+pic\b",
    r"\bnudes?\b",
    r"\bhentai\b",
    r"\bmasturbat(?:e|ion|ing)\b",
    r"\bejaculat(?:e|ion)\b",
    r"\bgangbang\b",
    r"\bdeepthroat\b",
    r"\bsex\s+(?:chat|cam|video|tape)\b",
    r"\bescort\s+service\b",
    r"\bchild\s+porn\b",
    r"\bcp\s+(?:视频|资源)\b",
)

_EXPLICIT_RE = re.compile("|".join(_EXPLICIT_PATTERNS), re.IGNORECASE)

# 歧义词：这些词有大量正常用法，只有在缺少"正常语境"时才算 NSFW。
# 例如"高潮"可指剧情/比赛，"调教"可指调参/训宠物。
_AMBIGUOUS_TERMS: Tuple[str, ...] = ("高潮", "调教", "裸奔", "约吗")

# 歧义词的正常语境。命中任一即认为该歧义词是正常用法。
_BENIGN_CONTEXT_PATTERNS: Tuple[str, ...] = (
    r"高潮迭起",
    r"(?:剧情|比赛|情绪|气氛|故事|电影|音乐|演出|行情|股价).{0,4}高潮",
    r"高潮.{0,4}(?:部分|阶段|迭起|来了|结束)",
    r"调教.{0,6}(?:模型|参数|代码|数据|prompt|ai|狗|猫|宠物|马|新人|徒弟)",
    r"(?:模型|参数|代码|数据|prompt|ai|狗|猫|宠物).{0,4}调教",
    # \"裸奔\"在技术语境里指没有防护措施地运行，属正常用法。
    r"(?:服务|系统|代码|数据库|接口|端口|服务器|生产|线上|裸机).{0,6}裸奔",
    r"裸奔.{0,6}(?:上线|运行|跑|状态|部署)",
    # 约饭/约球等正常邀约。
    r"约(?:饭|球|跑|个饭|一起)",
)

_BENIGN_CONTEXT_RE = re.compile("|".join(_BENIGN_CONTEXT_PATTERNS), re.IGNORECASE)


def detect_nsfw(text: Optional[str]) -> Tuple[bool, List[str]]:
    """检测文本是否包含明确的 NSFW 内容。

    Args:
        text: 待检测文本，可为 ``None``。

    Returns:
        Tuple[bool, List[str]]: ``(是否命中, 命中的关键词列表)``。
        命中词仅用于日志排查，调用方不应把它回显到聊天里。
    """

    if not text or not text.strip():
        return False, []

    matches = _EXPLICIT_RE.findall(text)
    if not matches:
        return False, []

    # findall 在有分组时返回元组，统一成字符串。
    hits: List[str] = []
    for match in matches:
        value = match if isinstance(match, str) else next((m for m in match if m), "")
        if value:
            hits.append(value)

    if not hits:
        return False, []

    # 歧义词落在正常语境里时不计入，但明确词照常命中。
    # 逐词判断而不是整段判断：一段话里既有"剧情高潮"又有"做爱"时，
    # 后者仍必须拦下。
    has_benign_context = bool(_BENIGN_CONTEXT_RE.search(text))
    effective = [
        hit
        for hit in hits
        if not (has_benign_context and any(term in hit for term in _AMBIGUOUS_TERMS))
    ]

    if not effective:
        return False, []

    return True, sorted(set(effective))

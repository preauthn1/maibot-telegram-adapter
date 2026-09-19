"""质疑回应：被指认是 AI 时，用表情阴阳回去而不是辩解。

## 背景

2026-09-03 群里两次旁敲我们：

    14:36:43 台风："搁这训练大模型来了"
    14:36:49 hiayu 复读
    15:22:34 台风："聊天机器人ban了吧，看了眼疼"
    15:22:43 hiayu 复读、15:22:50 ca_yuki 复读

两次都是台风起头、hiayu 秒复读。全量 72189 条里没有任何人
**直接回复我们**说"你是 AI"（A 级证据 0 条），都是不点名旁敲。

## 为什么用表情而不是文字

真人被阴阳时的反应是甩个表情怼回去，或者干脆不理。
AI 才会认真解释"我不是机器人"——越描越黑，而且解释本身
就是最强的 AI 特征（真人根本不在乎）。

🤡 的语用是"你在搞笑"，把对方的指认当玩笑消解掉，
既表明态度又不进入辩论。

## 硬约束

1. **绝不用文字回应质疑**。本模块只输出表情，不提供任何文字接口。
2. **必须限频**。"逢质疑必怼"本身就是脚本特征，真人有时懒得理。
3. **只针对指认我们**。群里聊 AI 工具、骂广告机器人都不算。
"""

from typing import Sequence

import random
import re

# 回应质疑用的表情。
#
# 🤡 = "你在搞笑"，把指认当玩笑消解，不进入辩论。
DOUBT_REACTION = "🤡"

# 单群单日回应上限。
#
# 取 3：被质疑三次以上还在怼，说明已经引起持续关注，
# 这时候更该安静而不是继续互动。
MAX_DOUBT_REACTIONS_PER_DAY = 3

# 回应概率。
#
# 不是每次都怼——真人有时候看到了懒得理。
# 0.45 意味着大约一半的质疑会收到表情。
DOUBT_REACTION_PROBABILITY = 0.45

# 指认"某人是 AI"的表达。
#
# 语料来自群里真实出现过的措辞，不是编的。
_DOUBT_PATTERNS = (
    # 直接指认
    r"(这货|这人|这位|他|她|你)\s*(是|像|就是)\s*(ai|机器人|bot|人机)",
    # 疑问式指认。尾巴不能写成固定的 吧/啊/吗/?，真人更常甩个
    # emoji 或直接接下一句（2026-09-04 16:02 真实漏检：
    # "大哥，你是不是机器人😀"）。
    #
    # 放宽办法不是 `.*`——那会吞掉「是不是机器人抢的号」这种把
    # 机器人当名词用的句子。改为：目标词后面**不能紧跟汉字**。
    # 紧跟汉字意味着"机器人"在句中充当主语/定语（机器人抢、机器人搞），
    # 而 emoji/标点/空白/句末则说明疑问到此为止。
    # 语气词 吧/啊/吗/呢/呀 是例外，允许直接跟在后面。
    r"(是不是|是|像)\s*(ai|机器人|bot|人机)(?:[吧啊吗呢呀]|(?![\u4e00-\u9fff]))",
    # 群里实际出现过的旁敲
    r"搁这训练大模型",
    r"聊天机器人.*(ban|封|踢)",
    r"大概率.*(聊天机器人|机器人|ai)",
    r"人机味",
    r"(ai|gpt|大模型).*(生成|写|回复).*(的吧|吧)",
    r"图灵",
)
_DOUBT_RE = re.compile("|".join(_DOUBT_PATTERNS), re.IGNORECASE)

# 排除模式：这些是在聊 AI 工具或骂别的 bot，不是指认我们。
_EXCLUDE_PATTERNS = (
    r"(用|拿|找|靠)\s*(ai|gpt|chatgpt|claude|大模型)",   # 用 AI 干活
    r"(ai|gpt)\s*(绘画|画图|写代码|翻译|生成图)",
    r"机器人.*(广告|私聊|群发|骚扰)",                      # 骂广告机器人
    r"(这个|那个|某个)\s*bot\s*(好用|不错|挺|能)",
    r"/\w+@\w*bot",                                       # bot 指令
    # 建议我们去问 AI，不是质疑我们是 AI
    # 实测 09-03 13:27「你把你这段话丢给AI去问问对不对」
    r"(丢给|问问|去问|问下|扔给)\s*(ai|gpt|大模型)",
    # 转发的新闻/通报里出现"蒸馏模型"等词
    r"(蒸馏模型|发布关于|通报|安全事件)",
    # 讲述自己过去的经历，不是当下质疑对方。
    # 实测 08-31 15:09「刚开始我以为是人机，现在接上反诈中心的电话
    # 一切都说得通了」——说的是银行来电。
    r"(以为|还以为|当成|当作|误以为)\s*(是)?\s*(ai|机器人|bot|人机)",
)
_EXCLUDE_RE = re.compile("|".join(_EXCLUDE_PATTERNS), re.IGNORECASE)

# 明确指向"别人"的表达。
#
# 实测 08-31 22:31-22:36，有人连发 12 条说另一个群成员
# "cm群和herocore群的那个Bit其实是ai"——那是别人被处刑，
# 跟我们无关。我们跳出来回 🤡 等于主动往自己身上引火。
#
# 另有图灵梗（"图灵老祖难道是可攻可受"）纯属玩笑，也要排除。
_NAMES_OTHERS_PATTERNS = (
    r"(那个|群的|群和)\s*\w+\s*(其实)?是\s*ai",   # "那个Bit其实是ai"
    r"其实\s*\w{2,}\s*是\s*ai",                   # "其实bit是ai"
    r"图灵(老祖|不是受|派)",                       # 图灵梗
    r"(他|她)是ai.*(维护|凌晨)",                   # 说别人作息像 AI
)
_NAMES_OTHERS_RE = re.compile("|".join(_NAMES_OTHERS_PATTERNS), re.IGNORECASE)


def detect_ai_doubt(text: str) -> bool:
    """判断一条消息是否在指认我们是 AI。

    Args:
        text: 待检测的消息文本。

    Returns:
        bool: 是指认我们则返回 ``True``。
    """

    if not text or not text.strip():
        return False
    if _EXCLUDE_RE.search(text):
        return False
    if _NAMES_OTHERS_RE.search(text):
        return False
    return bool(_DOUBT_RE.search(text))


def is_doubt_aimed_at_us(
    text: str,
    *,
    replied_to_us: bool = False,
    recently_spoke: bool = False,
) -> bool:
    """判断这条质疑是不是冲我们来的。

    群里经常有人互相指认 AI（实测 08-31 有人连发 12 条说另一个成员
    "其实是ai"），那是别人的事——我们插嘴回表情反而突兀，
    等于主动往自己身上引火。

    只有两种情况算冲我们：
        1. 直接回复我们的消息
        2. 我们刚发过言（不点名的旁敲，如台风"搁这训练大模型来了"
           就发生在我们发言 54 秒后）

    Args:
        text: 消息文本。
        replied_to_us: 该消息是否回复了我们。
        recently_spoke: 我们最近是否刚发过言。

    Returns:
        bool: 冲我们来的返回 ``True``。
    """

    if not detect_ai_doubt(text):
        return False
    return replied_to_us or recently_spoke


def should_react_to_doubt(reacted_today: Sequence[str]) -> bool:
    """判断此刻是否该对质疑做表情回应。

    按群隔离由调用方负责（传入该群当日的记录）——
    本函数不感知 chat_id，避免接口误导。

    Args:
        reacted_today: 今天已在该群回应过的记录，用于限流。

    Returns:
        bool: 应当回应返回 ``True``。
    """

    if len(reacted_today) >= MAX_DOUBT_REACTIONS_PER_DAY:
        return False
    return random.random() < DOUBT_REACTION_PROBABILITY


def pick_doubt_reaction(allowed: Sequence[str] | None = None) -> str | None:
    """选择回应质疑用的表情。

    Args:
        allowed: 该群允许的表情集合；``None`` 表示不限制。

    Returns:
        Optional[str]: 可用时返回表情，否则 ``None``。
    """

    if allowed is not None and DOUBT_REACTION not in allowed:
        # 群里禁用了 🤡 就不勉强——换别的容易词不达意
        return None
    return DOUBT_REACTION

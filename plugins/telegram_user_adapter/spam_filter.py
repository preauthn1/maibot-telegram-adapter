"""广告 / 垃圾消息识别。

硬性要求：**看到广告就不理**。

理由有两层：
1. 跟广告搭话毫无价值，纯烧 token。
2. 真人看到广告是直接划过去的；只有机器人才会逐条认真回复，
   这本身就是暴露特征。

判定不靠单一关键词——\"电子\"\"点位\"这类词在正常聊天里太常见，
单独匹配会大量误伤。这里用多信号加权：

- **零宽字符**：几乎是广告铁证。正常人打字不会插 U+200B/200C/200D，
  广告用它来切断关键词以绕过检测。命中即判定。
- 引流联系方式（加V/微信/QQ/飞机/私聊）
- 收益诱导（日入/月入/躺赚/包回本 + 金额）
- 灰产词（洗米/跑分/菠菜/网赚/代收付）
- 邀请链接 / 短链

词表参考 https://github.com/sykin7/my-telegram-spam-rules ，
但只挑高置信度的部分，避免把正常对话误判成广告。
"""

from __future__ import annotations

from typing import List, Tuple

import re
import unicodedata

# 零宽 / 不可见字符。广告用它们切断关键词绕过检测，正常输入极少出现。
_INVISIBLE_CHARS = (
    "\u200b",  # ZERO WIDTH SPACE
    "\u200c",  # ZERO WIDTH NON-JOINER
    "\u200d",  # ZERO WIDTH JOINER
    "\u2060",  # WORD JOINER
    "\ufeff",  # ZERO WIDTH NO-BREAK SPACE
    "\u180e",  # MONGOLIAN VOWEL SEPARATOR
)

# 高置信度灰产/引流词。这些词在正常闲聊里基本不会出现。
_SPAM_STRONG: Tuple[str, ...] = (
    "洗米", "跑分", "菠菜", "四方支付", "代收付", "承兑",
    "日入", "月入过", "躺赚", "包回本", "稳赚", "零风险",
    "上岸项目", "网赚", "刷单", "拉人头", "返水", "洗白",
    "出黑", "接口料", "资金盘", "杀猪盘", "博彩", "网投",
    "招代理", "日结", "无门槛", "秒到账", "包教包会",
)

# 引流方式。单独出现可能正常（\"加个微信\"），需要配合其他信号。
_SPAM_CONTACT: Tuple[str, ...] = (
    "加v", "加微", "薇信", "威信", "徽信", "vx", "＋v",
    "私聊我", "私我", "滴滴我", "联系我", "详聊", "咨询",
    "飞机号", "电报群", "tg群",
)

# 收益诱导常见搭配。
_SPAM_PROFIT_RE = re.compile(
    r"(?:日|月|周|天)(?:入|赚|结|收)\s*[0-9]+\s*[kK万千百元]?"
    r"|[0-9]+\s*[kK万千]\s*(?:\+|以上|起步)"
    r"|(?:收益|利润|回报)\s*[0-9]+\s*%",
)

# 邀请链接 / 短链。
_SPAM_LINK_RE = re.compile(
    r"t\.me/\+|t\.me/joinchat|bit\.ly/|t\.co/|short\.link/",
    re.IGNORECASE,
)


def _strip_invisible(text: str) -> Tuple[str, int]:
    """移除不可见字符并返回移除数量。

    Args:
        text: 原始文本。

    Returns:
        Tuple[str, int]: ``(清理后的文本, 移除的字符数)``。
    """

    removed = 0
    cleaned_chars: List[str] = []
    for ch in text:
        if ch in _INVISIBLE_CHARS or unicodedata.category(ch) == "Cf":
            removed += 1
            continue
        cleaned_chars.append(ch)
    return "".join(cleaned_chars), removed


def detect_spam(text: str) -> Tuple[bool, List[str]]:
    """判断一条消息是否是广告 / 垃圾消息。

    Args:
        text: 待检测文本。

    Returns:
        Tuple[bool, List[str]]: ``(是否广告, 命中的信号列表)``。
            信号列表只用于本地日志，不回显到聊天。
    """

    if not text or not text.strip():
        return False, []

    cleaned, invisible_count = _strip_invisible(text)
    normalized = cleaned.lower()
    signals: List[str] = []

    # 零宽字符是最强信号：正常人不会在中文里插不可见字符，
    # 只有为了绕过关键词检测才会这么干。命中两个以上直接判定。
    if invisible_count >= 2:
        signals.append(f"invisible_chars:{invisible_count}")

    strong_hits = [w for w in _SPAM_STRONG if w in normalized]
    if strong_hits:
        signals.append("strong:" + ",".join(strong_hits[:3]))

    if _SPAM_PROFIT_RE.search(normalized):
        signals.append("profit_claim")

    if _SPAM_LINK_RE.search(normalized):
        signals.append("invite_link")

    contact_hits = [w for w in _SPAM_CONTACT if w in normalized]
    if contact_hits:
        signals.append("contact:" + ",".join(contact_hits[:3]))

    # 判定规则：
    # - 零宽字符混淆 → 直接判定（几乎不会误伤）
    # - 强灰产词 → 直接判定
    # - 收益诱导 + 任意其他信号 → 判定
    # - 邀请链接 + 引流方式 → 判定
    if invisible_count >= 2:
        return True, signals
    if strong_hits:
        return True, signals
    if "profit_claim" in signals and len(signals) >= 2:
        return True, signals
    if "invite_link" in signals and contact_hits:
        return True, signals

    return False, signals

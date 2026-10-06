"""检测中文回复末尾无上下文的异常尾缀，不清洗正文或合法外语。

三类尾缀（均只看句尾，正文不动）：

1. 外语字符簇：按文字块匹配上下文；群友出现俄语不能放行无关阿拉伯文。
2. 孤立全角括号簇：2026-10-06 发出过“免 root 抓 HTTPS】【。”。句尾出现开括号，
   或闭括号在前文没有同类开括号配对，即判为残渣。ASCII 括号不参与，避免误伤 :) 等颜文字。
3. 孤立单个英文字母：同日发出过“先关 TUN 看看 c”。仅当字母紧跟在汉字+空白之后、
   前文不是“选/方案/用”等选项语境、且上下文没人单独提过这个字母时判定。
"""

from typing import Iterable, Optional, Tuple

import re

_FOREIGN_SCRIPT_RANGES = (
    ("\u0370", "\u03ff"),
    ("\u0400", "\u052f"),
    ("\u0530", "\u058f"),
    ("\u0590", "\u05ff"),
    ("\u0600", "\u06ff"),
    ("\u0700", "\u074f"),
    ("\u0900", "\u097f"),
    ("\u0980", "\u09ff"),
    ("\u0a00", "\u0a7f"),
    ("\u0a80", "\u0aff"),
    ("\u0b00", "\u0b7f"),
    ("\u0b80", "\u0bff"),
    ("\u0c00", "\u0c7f"),
    ("\u0c80", "\u0cff"),
    ("\u0d00", "\u0d7f"),
    ("\u0d80", "\u0dff"),
    ("\u0e00", "\u0e7f"),
    ("\u0f00", "\u0fff"),  # 藏文：覆盖本次事故尾缀。
    ("\u10a0", "\u10ff"),
)
_FOREIGN_CLASS = "".join(f"{lo}-{hi}" for lo, hi in _FOREIGN_SCRIPT_RANGES)
_PUNCT = r"[\s。！？!?.,，、…~～]*"
_TAIL = re.compile(f"([{_FOREIGN_CLASS}]+)({_PUNCT})$")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_FOREIGN_EXPLANATION = re.compile(r"(?:俄语|阿拉伯语|希腊语|藏文|外语|翻译|译为|译作|原文|读作|写作|是|叫|为)\s*[:：=]?\s*$")

_BRACKET_PAIRS = {"【": "】", "〔": "〕", "〖": "〗", "「": "」", "『": "』", "《": "》", "〈": "〉", "（": "）"}
_CLOSE_TO_OPEN = {close: open_ for open_, close in _BRACKET_PAIRS.items()}
_BRACKET_CLASS = re.escape("".join(_BRACKET_PAIRS) + "".join(_CLOSE_TO_OPEN))
_BRACKET_TAIL = re.compile(f"([{_BRACKET_CLASS}]+)({_PUNCT})$")

_LETTER_TAIL = re.compile(f"\\s([A-Za-z])({_PUNCT})$")
_OPTION_CONTEXT = re.compile(
    r"(?:选|选项|方案|版|型|类|号|组|档|级|是|用|或|还是|和|跟|与|plan|option|type)\s*$", re.IGNORECASE
)


def _foreign_noise(text: str, peers: Tuple[str, ...]) -> Optional["re.Match[str]"]:
    match = _TAIL.search(text)
    if match is None:
        return None
    prefix = text[:match.start()]
    if not _CJK.search(prefix) or _FOREIGN_EXPLANATION.search(prefix):
        return None
    tail = match.group(1)
    ranges = [(lo, hi) for lo, hi in _FOREIGN_SCRIPT_RANGES if any(lo <= ch <= hi for ch in tail)]
    if ranges and all(any(any(lo <= ch <= hi for ch in peer) for peer in peers) for lo, hi in ranges):
        return None
    return match


def _bracket_noise(text: str) -> Optional["re.Match[str]"]:
    match = _BRACKET_TAIL.search(text)
    if match is None:
        return None
    prefix = text[:match.start()]
    if not _CJK.search(prefix):
        return None
    tail = match.group(1)
    if any(ch in _BRACKET_PAIRS for ch in tail):
        # 句尾不可能以开括号正常收尾。
        return match
    depth: dict = {}
    for ch in prefix:
        if ch in _BRACKET_PAIRS:
            depth[ch] = depth.get(ch, 0) + 1
        elif ch in _CLOSE_TO_OPEN:
            opener = _CLOSE_TO_OPEN[ch]
            depth[opener] = depth.get(opener, 0) - 1
    need: dict = {}
    for ch in tail:
        opener = _CLOSE_TO_OPEN[ch]
        need[opener] = need.get(opener, 0) + 1
    if all(depth.get(opener, 0) >= count for opener, count in need.items()):
        return None
    return match


def _letter_noise(text: str, peers: Tuple[str, ...]) -> Optional["re.Match[str]"]:
    match = _LETTER_TAIL.search(text)
    if match is None:
        return None
    prefix = text[:match.start()].rstrip()
    if not prefix or not _CJK.match(prefix[-1]):
        return None
    if _OPTION_CONTEXT.search(prefix):
        return None
    letter = match.group(1)
    token = re.compile(rf"(?<![A-Za-z]){re.escape(letter)}(?![A-Za-z])", re.IGNORECASE)
    if any(token.search(peer) for peer in peers):
        return None
    return match


def _find_noise(text: str, peers: Tuple[str, ...]) -> Optional["re.Match[str]"]:
    return _foreign_noise(text, peers) or _bracket_noise(text) or _letter_noise(text, peers)


def detect_unicode_noise(text: str, peer_texts: Iterable[str]) -> Optional[str]:
    """返回可疑尾缀；不把正文外语、明确翻译、配对括号和选项字母判成乱码。"""
    match = _find_noise(text or "", tuple(peer_texts))
    return match.group(1) if match is not None else None


def strip_unicode_noise(text: str) -> Tuple[str, str]:
    """仅删除末尾命中的字符簇，保留正文与句末标点。调用前须通过检测。"""
    match = _find_noise(text or "", ())
    if match is None:
        return text, ""
    return (text[:match.start()] + match.group(2)).strip(), match.group(1)


NOISE_RETRY_CONSTRAINT = "上一条回复末尾出现无上下文的异常字符（乱码、孤立括号或孤立字母）。以删去尾缀后的正文为准重新表达；不要复制异常字符，不要增加事实或信息点。"

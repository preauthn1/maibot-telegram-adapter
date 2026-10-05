"""只检测中文回复末尾无上下文的外语字符簇，不清洗正文或合法外语。

按文字块匹配上下文；群友出现俄语不能放行无关阿拉伯文。
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
_TAIL = re.compile(f"([{_FOREIGN_CLASS}]+)([\\s。！？!?.,，、…]*)$")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_FOREIGN_EXPLANATION = re.compile(r"(?:俄语|阿拉伯语|希腊语|藏文|外语|翻译|译为|译作|原文|读作|写作|是|叫|为)\s*[:：=]?\s*$")


def detect_unicode_noise(text: str, peer_texts: Iterable[str]) -> Optional[str]:
    """返回可疑尾缀；不把正文外语、明确翻译和带上下文的外语判成乱码。"""
    match = _TAIL.search(text)
    if match is None:
        return None
    prefix = text[:match.start()]
    if not _CJK.search(prefix) or _FOREIGN_EXPLANATION.search(prefix):
        return None
    tail = match.group(1)
    ranges = [(lo, hi) for lo, hi in _FOREIGN_SCRIPT_RANGES if any(lo <= ch <= hi for ch in tail)]
    peers = tuple(peer_texts)
    if ranges and all(any(any(lo <= ch <= hi for ch in peer) for peer in peers) for lo, hi in ranges):
        return None
    return tail


def strip_unicode_noise(text: str) -> Tuple[str, str]:
    """仅删除末尾命中的字符簇，保留正文与句末标点。调用前须通过检测。"""
    match = _TAIL.search(text)
    if match is None:
        return text, ""
    return (text[:match.start()] + match.group(2)).strip(), match.group(1)


NOISE_RETRY_CONSTRAINT = "上一条回复出现无上下文的异常外语尾缀。以删去尾缀后的正文为准重新表达；不要复制异常字符，不要增加事实或信息点。"

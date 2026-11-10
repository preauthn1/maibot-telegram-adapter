"""检测中文回复末尾无上下文的异常尾缀，不清洗正文或合法外语。

覆盖以下真实线上尾缀污染（均只看句尾，正文不动）：
1. 外语字符簇：按文字块匹配上下文；群友出现俄语不能放行无关阿拉伯文。
2. 孤立全角括号簇：2026-10-06 发出过“免 root 抓 HTTPS】【。”。句尾出现开括号，
   或闭括号在前文没有同类开括号配对，即判为残渣。ASCII 括号不参与，避免误伤 :) 等颜文字。
3. 孤立单个英文字母或无上下文尾随英文词（如 `c`、`pry`、`peqata`、`aluunniit`）。
4. 扩展/未分配 CJK 码位（`U+20000`–`U+FAFFF`，如 `U+4E7FF` `\U0004e7ff`、`U+249DF` `𤧟`）。
5. 模型 EOS 尾缀词表污染（色情 SEO 词 `av无码`/`av不卡免费播放`/`久久精品`、博彩六合彩词 `系列玄机图`/`合乐`、
   重复符号簇 `#+#+#+#+`、繁体/生僻单字尾缀 `屬`/`展開`/`魏?`/`屑`）。
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

# Plane-2 ~ Plane-15 罕见/未分配扩展区字符（如 \U0004e7ff、\U000249df）及 BMP 私用区
_RARE_PLANE_TAIL = re.compile(f"([\\ue000-\\uf8ff\\U00020000-\\U000fafff]+)({_PUNCT})$")

# 实测线上模型 EOS 尾缀词表污染（色情 SEO、六合彩/博彩、乱码符号串、孤立生僻/繁体尾字）
_POLLUTED_EOS_TAIL = re.compile(
    r"(\s*(?:"
    r"av无码|av不卡(?:免费播放)?|久久精品|无码免费(?:播放)?|免费在线观看|高清无码|色情|"
    r"系列玄机图|玄机图|六合彩|合乐|"
    r"答复[A-Za-z]{3,}|"
    r"(?:#\+){2,}#?|"
    r"(?<=[\u4e00-\u9fffA-Za-z0-9\s])(?:屬|展開|魏\??|屑)"
    r"))" + f"({_PUNCT})$",
    re.IGNORECASE,
)

_BRACKET_PAIRS = {"【": "】", "〔": "〕", "〖": "〗", "「": "」", "『": "』", "《": "》", "〈": "〉", "（": "）"}
_CLOSE_TO_OPEN = {close: open_ for open_, close in _BRACKET_PAIRS.items()}
_BRACKET_CLASS = re.escape("".join(_BRACKET_PAIRS) + "".join(_CLOSE_TO_OPEN))
_BRACKET_TAIL = re.compile(f"([{_BRACKET_CLASS}]+)({_PUNCT})$")

_LETTER_TAIL = re.compile(f"\\s([A-Za-z])({_PUNCT})$")
# 汉字（或英文技术词）后紧跟空格 + 无上下文小写拉丁词（如 `第三方 pry`、`大佬大佬咋了 peqata`）
_LATIN_GIBBERISH_TAIL = re.compile(f"\\s([a-z]{{3,12}})({_PUNCT})$")
_COMMON_TECH_LATIN = frozenset({
    "app", "apk", "api", "arm", "asn", "bgp", "bot", "bug", "cdn", "cf", "cli", "cpu", "css", "csv",
    "dav", "ddns", "dev", "diy", "dmg", "dns", "doh", "dot", "ech", "exe", "faq", "fix", "fps", "ftp",
    "gb", "gif", "git", "gnu", "gpu", "gui", "hap", "hysteria", "http", "https", "icmp", "ide", "id",
    "ios", "ip", "ipa", "ipk", "ips", "ipv4", "ipv6", "isp", "jar", "jpg", "js", "json", "jwt", "kb",
    "key", "kcp", "kvm", "lan", "lat", "led", "llm", "log", "loon", "lte", "mac", "max", "mb", "mcp",
    "md", "meta", "mihomo", "mitm", "min", "mtu", "nat", "net", "nas", "nft", "nic", "node", "npm",
    "ntp", "ocr", "oem", "oled", "open", "opt", "os", "ota", "otp", "pac", "pad", "pdf", "pem", "php",
    "pid", "pin", "ping", "pkg", "png", "pop", "port", "pro", "proxy", "quic", "ram", "rar", "raw",
    "rom", "root", "rpc", "rpm", "rsa", "rss", "rust", "sdk", "sni", "socks", "socks5", "sql", "ssh",
    "ssl", "ssr", "stash", "sub", "surge", "svg", "swap", "sync", "sys", "tab", "tag", "tap", "tar",
    "tb", "tcp", "tg", "tls", "tmp", "toml", "top", "tor", "tun", "tv", "txt", "udp", "ui", "uid",
    "url", "usb", "utf", "uuid", "v2ray", "vip", "vlan", "vless", "vm", "vmess", "vpn", "vps", "wan",
    "wap", "warp", "wasm", "web", "webdav", "webp", "wifi", "win", "wireguard", "wlan", "wsl", "www",
    "x64", "x86", "xml", "xray", "yaml", "yml", "zip", "clash", "singbox", "mihomo",
    "stash", "shadowrocket", "surfboard", "nekobox", "v2rayn", "karing", "verge", "drive", "github",
    "google", "apple", "android", "windows", "linux", "ubuntu", "debian", "macos", "harmony",
    "bitwarden", "telegram", "nagram", "nekogram", "swiftgram", "turrit", "icloud", "onedrive",
    "global", "rule", "direct", "reject", "fake", "tun", "mixed", "system", "release", "releases",
    "beta", "alpha", "lite", "plus", "ultra", "mini", "nano", "flash", "flux", "sdxl",
})

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


def _rare_plane_noise(text: str) -> Optional["re.Match[str]"]:
    return _RARE_PLANE_TAIL.search(text)


def _polluted_eos_noise(text: str) -> Optional["re.Match[str]"]:
    match = _POLLUTED_EOS_TAIL.search(text)
    if match is None:
        return None
    prefix = text[:match.start()].strip()
    if len(prefix) < 2:
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


def _latin_gibberish_noise(text: str, peers: Tuple[str, ...]) -> Optional["re.Match[str]"]:
    match = _LATIN_GIBBERISH_TAIL.search(text)
    if match is None:
        return None
    prefix = text[:match.start()].rstrip()
    if not prefix or not _CJK.match(prefix[-1]):
        return None
    if _OPTION_CONTEXT.search(prefix):
        return None
    word = match.group(1).lower()
    if word in _COMMON_TECH_LATIN:
        return None
    token = re.compile(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", re.IGNORECASE)
    if any(token.search(peer) for peer in peers):
        return None
    return match


def _find_noise(text: str, peers: Tuple[str, ...]) -> Optional["re.Match[str]"]:
    return (
        _rare_plane_noise(text)
        or _polluted_eos_noise(text)
        or _foreign_noise(text, peers)
        or _bracket_noise(text)
        or _letter_noise(text, peers)
        or _latin_gibberish_noise(text, peers)
    )


def detect_unicode_noise(text: str, peer_texts: Iterable[str]) -> Optional[str]:
    """返回可疑尾缀；不把正文外语、明确翻译、配对括号和选项字母判成乱码。"""
    match = _find_noise(text or "", tuple(peer_texts))
    return match.group(1).strip() if match is not None else None


def strip_unicode_noise(text: str, peer_texts: Iterable[str] = ()) -> Tuple[str, str]:
    """仅删除末尾命中的字符簇，保留正文与句末标点。"""
    cur = text or ""
    removed_parts = []
    peers = tuple(peer_texts)
    for _ in range(3):
        match = _find_noise(cur, peers)
        if match is None:
            break
        removed_parts.append(match.group(1))
        cur = (cur[:match.start()] + match.group(2)).strip()
    return cur, "".join(removed_parts)


NOISE_RETRY_CONSTRAINT = "上一条回复末尾出现无上下文的异常字符或词表污染尾缀。以删去尾缀后的正文为准重新表达；不要复制异常字符，不要增加事实或信息点。"

"""高风险群的专用约束。

「某高风险小群」(-1009000000001) 是目前最难的一关，实测特征：

- 活跃 13 人的熟人小圈子，前 3 人占 71% 发言
- 消息密度仅 2.4 条/小时，非常安静
- 消息中位长度 **13 字**，平均 37 字——极短句
- 内容硬核：MTE、GPL 许可证、JLS 协议、SoC 成本、Pixel 内存标记

我们在该群只发过 1 条（已被删除），3.5 小时后就被当面质问
"你是大语言模型吗？"。

这类群的破绽不在"说错话"，而在"说得太齐整"：真人在这种圈子里
是短促、跳跃、带梗的，而模型倾向输出完整通顺的句子。

因此该模块的核心是**长度约束**与**极低参与率**，而不是内容过滤。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Set, Tuple

import re

from .chat_profiles import ChatProfile, ChatProfileStore

# 画像卡仓库。由插件启动时注入实际路径；未注入时退回硬编码画像。
#
# 画像卡放在 data/plugins/<id>/chats/<chat_id>/SKILL.md，
# 每群一份，带 YAML frontmatter 存参数、正文写观察记录。
# 群的性质会随时间漂移，改卡即生效比改代码重启更实用。
_STORE: Optional[ChatProfileStore] = None


def bind_store(root: Path) -> None:
    """绑定画像卡目录。

    Args:
        root: 画像卡根目录（``<data_dir>/chats``）。
    """

    global _STORE
    _STORE = ChatProfileStore(root)


def _profile(chat_id: str) -> Optional[ChatProfile]:
    """取该群的画像卡，未绑定或无卡时返回 None。

    Args:
        chat_id: 会话 ID。

    Returns:
        Optional[ChatProfile]: 画像卡内容。
    """

    return _STORE.get(str(chat_id)) if _STORE is not None else None


# 高风险群及其画像。key 为 chat_id 字符串。
HIGH_RISK_CHATS: Dict[str, Dict[str, float]] = {
    # 某高风险小群：13 人熟人圈，中位 13 字，2.4 条/小时
    "-1009000000001": {
        "max_chars": 24.0,
        "reply_ratio": 0.08,
        "min_gap_seconds": 900.0,
    },
}

# 禁止谈技术的群。
#
# 这些群里全是相关领域的资深从业者，技术话题说浅了露怯、说深了
# 更可疑——「某高风险小群」讨论的是 MTE 内存标记、GPL 许可证豁免、
# JLS 握手伪装这种深度内容，任何似是而非的回答都会立刻暴露。
#
# 结论：技术话题一概不接，只在纯闲聊时露面。
NO_TECH_CHATS: Set[str] = {"-1009000000001"}

# 技术话题特征词。命中即判定为技术讨论。
#
# 覆盖该群实际出现过的领域：代理协议、系统底层、开源许可、
# 硬件、网络。宁可多拦——漏判的代价是被识破，误判只是少说一句。
_TECH_KEYWORDS: Tuple[str, ...] = (
    # 代理与网络协议
    "vless", "vmess", "trojan", "shadowsocks", "ss节点", "hysteria", "hy2",
    "wireguard", "openvpn", "reality", "xtls", "tls", "quic", "brutal",
    "jls", "mihomo", "clash", "sing-box", "singbox", "xray", "v2ray",
    "节点", "机场", "代理", "翻墙", "科学上网", "订阅链接", "分流", "落地",
    "中转", "回程", "延迟", "丢包", "带宽", "限速", "端口", "握手", "混淆",
    # 系统与底层
    "内核", "kernel", "linux", "debian", "ubuntu", "fedora", "arch",
    "openwrt", "padavan", "固件", "刷机", "编译", "内存", "cpu", "soc",
    "arm", "x86", "架构", "驱动", "进程", "线程", "syscall", "mte",
    "root", "bootloader", "分区", "挂载",
    # 开发与开源
    "github", "gitlab", "commit", "patch", "pr", "issue", "repo",
    "gpl", "mit许可", "bsd", "apache", "开源", "许可证", "源码",
    "docker", "容器", "k8s", "编程", "代码", "脚本", "api", "sdk",
    "python", "golang", "rust", "c++", "javascript",
    # 安全
    "漏洞", "cve", "poc", "exp", "提权", "逆向", "抓包", "加密",
    "密钥", "证书", "签名", "哈希", "破解", "注入",
    # 硬件与设备
    "路由器", "软路由", "nas", "服务器", "vps", "主机", "显卡", "gpu",
    "pixel", "骁龙", "天玑", "芯片", "跑分",
    # 云与运维
    "cloudflare", "aws", "阿里云", "腾讯云", "甲骨文", "oracle",
    "域名", "dns", "cdn", "反代", "nginx", "systemd", "运维", "部署",
    # 网络故障与运营商：该群常讨论断网、劫持、封锁
    "断网", "宽带", "蜂窝", "电信", "联通", "移动", "运营商", "网络",
    "封锁", "劫持", "qos", "限流", "被墙", "解封", "ipv6", "ipv4",
)


def is_tech_topic(text: str, chat_id: Optional[str] = None) -> bool:
    """判断内容是否属于技术话题。

    Args:
        text: 待判断的文本（入站消息或我们要发的话）。
        chat_id: 会话 ID；提供时会额外匹配该群画像卡里的
            ``extra_keywords``。

    Returns:
        bool: 命中技术特征时返回 ``True``。
    """

    normalized = (text or "").strip().lower()
    if not normalized:
        return False

    if chat_id is not None:
        card = _profile(chat_id)
        if card and any(k in normalized for k in card.extra_keywords):
            return True

    if any(keyword in normalized for keyword in _TECH_KEYWORDS):
        return True

    # 带链接的技术分享：这个群 5% 的消息带链接，基本都是技术文章。
    if "http" in normalized and any(
        domain in normalized
        for domain in ("github", "gitlab", "stackoverflow", "arxiv", "tomshardware")
    ):
        return True

    # 命令行/代码片段特征
    if re.search(r"(?:sudo |apt |yum |npm |pip |curl |wget |ssh |systemctl )", normalized):
        return True
    if re.search(r"\d+\.\d+\.\d+\.\d+", normalized):  # IP 地址
        return True

    return False


def blocks_tech(chat_id: str) -> bool:
    """判断该群是否禁止谈技术。

    Args:
        chat_id: 会话 ID。

    Returns:
        bool: 需要回避技术话题时返回 ``True``。
    """

    card = _profile(chat_id)
    if card is not None:
        return card.block_tech
    return str(chat_id) in NO_TECH_CHATS

# 默认画像：未列出的群不做额外约束。
_DEFAULT_MAX_CHARS = 0.0


def is_high_risk(chat_id: str) -> bool:
    """判断是否为高风险群。

    Args:
        chat_id: 会话 ID。

    Returns:
        bool: 命中高风险名单时返回 ``True``。
    """

    card = _profile(chat_id)
    if card is not None:
        # 有画像卡不等于高风险——低风险群同样有卡，只是不设约束。
        # 以是否真的配了约束为准。
        return bool(card.max_chars or card.reply_ratio or card.block_tech)
    return str(chat_id) in HIGH_RISK_CHATS


def get_max_chars(chat_id: str) -> float:
    """取该群允许的最大消息长度。

    Args:
        chat_id: 会话 ID。

    Returns:
        float: 字符上限；0 表示不限制。
    """

    card = _profile(chat_id)
    if card is not None:
        return card.max_chars
    profile = HIGH_RISK_CHATS.get(str(chat_id))
    return profile["max_chars"] if profile else _DEFAULT_MAX_CHARS


def get_reply_ratio(chat_id: str) -> Optional[float]:
    """取该群的参与率上限。

    Args:
        chat_id: 会话 ID。

    Returns:
        Optional[float]: 参与率上限；未命中返回 ``None``。
    """

    card = _profile(chat_id)
    if card is not None:
        return card.reply_ratio
    profile = HIGH_RISK_CHATS.get(str(chat_id))
    return profile["reply_ratio"] if profile else None


def get_min_gap(chat_id: str) -> Optional[float]:
    """取该群两次发言的最小间隔。

    Args:
        chat_id: 会话 ID。

    Returns:
        Optional[float]: 间隔秒数；未命中返回 ``None``。
    """

    card = _profile(chat_id)
    if card is not None:
        return card.min_gap_seconds
    profile = HIGH_RISK_CHATS.get(str(chat_id))
    return profile["min_gap_seconds"] if profile else None


# 在这类技术圈里显得"不是自己人"的表达。
# 不是脏话或敏感词，而是**过于完整、像在解释给外行听**的说法。
_EXPLAINER_PATTERNS = (
    r"这(?:个|种)(?:意思|说法)是(?:指|说)",
    r"简单(?:来说|地说|讲)",
    r"也就是说",
    r"换句话说",
    r"总(?:的来说|结一下)",
    r"值得(?:注意|一提)的是",
    r"需要(?:注意|说明)的是",
    r"确实(?:如此|是这样)",
    r"我(?:觉得|认为)(?:这|它)(?:个|种)?(?:挺|很|比较)",
)
_COMPILED_EXPLAINER = tuple(re.compile(p) for p in _EXPLAINER_PATTERNS)


def sounds_like_explainer(text: str) -> bool:
    """判断是否是"讲解腔"。

    这种圈子里没人会用"简单来说""也就是说"起头——那是写文档
    或者对外行解释的语气，一出现就显得不是圈内人。

    Args:
        text: 待发送内容。

    Returns:
        bool: 命中讲解腔时返回 ``True``。
    """

    normalized = (text or "").strip()
    if not normalized:
        return False
    return any(p.search(normalized) for p in _COMPILED_EXPLAINER)


def should_block(chat_id: str, text: str) -> tuple[bool, str]:
    """综合判断这条内容能否在该群发出。

    Args:
        chat_id: 会话 ID。
        text: 待发送内容。

    Returns:
        tuple[bool, str]: ``(是否拦截, 原因)``。
    """

    if not is_high_risk(chat_id):
        return False, ""

    normalized = (text or "").strip()
    if not normalized:
        return True, "空内容"

    max_chars = get_max_chars(chat_id)
    if max_chars > 0 and len(normalized) > max_chars:
        return True, f"长度 {len(normalized)} 超过该群上限 {max_chars:.0f}（群内中位仅 13 字）"

    if sounds_like_explainer(normalized):
        return True, "讲解腔，圈内人不这么说话"

    return False, ""

"""命令与代码块完整性保护。

真实事故（2026-09-02 16:41-16:42，某技术交流群）：

    16:41:43 出站  "不用私发群里贴出来你直接复制就行yabs就这条curl -sL yabs.sh"
    16:41:53 出站  "|bash解锁测试"

同一条 ``curl -sL yabs.sh | bash`` 被拆成两条消息、间隔 10 秒发出，
两条都是废的——别人复制第一条跑不通。同一时段还出现命令与中文
直接粘连（``...valuexyz)下次想自己找...``）。

为什么这比"反应太快"更危险：
反应快只是主观可疑，一条跑不通的命令是**白纸黑字的证据**，
而且技术群里真的会有人复制执行、回头追究。真人贴命令要么用
独立消息、要么用代码块，绝不会把管道符拆到下一条。

三层保护：
1. ``merge_split_commands`` —— 把上游拆散的命令段重新合并
2. ``protect_commands``     —— 命令与中文粘连时补分隔
3. ``format_command_segments`` —— 用代码块包裹，保证可复制

设计约束：普通聊天必须零影响。一旦对普通消息启用 Markdown
parse_mode，聊天里的 ``*`` ``_`` ``` 会被当成格式标记吃掉或
直接报 400，反而制造新的暴露面。
"""

from typing import Any, Dict, List, Optional, Tuple

import re

# 命令特征：可执行程序名、管道、URL、脚本后缀。
#
# 这里刻意不做得太宽——把普通聊天误判成命令并塞进代码块，
# 比漏掉一条命令更扎眼。
_COMMAND_PATTERN = re.compile(
    r"(?:^|\s)(?:"
    r"curl|wget|bash|sh|zsh|sudo|apt|apt-get|yum|dnf|pacman|"
    r"docker|systemctl|ssh|scp|rsync|git|npm|pip|pip3|python|python3|"
    r"chmod|chown|iptables|nft|nano|vim"
    r")\s"
    r"|\|\s*(?:bash|sh)\b"
    r"|https?://\S+"
    r"|\b[a-z0-9][a-z0-9-]*\.(?:sh|py)\b",
    re.IGNORECASE,
)

# 续行特征：以管道/逻辑运算符/重定向开头 = 上一段没写完。
_CONTINUATION_HEAD = re.compile(r"^\s*(?:\||&&|\|\||>>|>|&|\))")

# 命令尾部紧跟中文（缺分隔）。
#
# 字符类必须显式排除中文：Python 正则的 \w 在 Unicode 模式下**包含中文**，
# 所以 r"([)\w/.-])(?=[\u4e00-\u9fff])" 会把 "下次" 里的 "下" 也当成
# 命令字符，结果整句被拆成 "下 次 想 自 己 找"。
# 这里改用显式的 ASCII 字符类。
_GLUED_TO_CJK = re.compile(
    r"([)\]}a-zA-Z0-9/._-])(?=[\u4e00-\u9fff])"
)

# 已经是代码块 / 行内代码。
_ALREADY_FENCED = re.compile(r"```|^`[^`]+`$")

# 工具调用标记：XML 风格的成对标签，以及各家模型的特殊 token。
#
# 为什么按"形态"而不是按"名字"匹配：
# 若只列 tool_call|invoke|parameter 这些已知名字，换个模型吐出
# <|channel|> 或 [TOOL_CALLS] 就又漏了——2026-09-02 那次泄漏
# （"对就这个</arg_value></tool_call>"）正是因为三层防护全是黑名单，
# 库里没有的一律不认识。
#
# 这里改成形态匹配：真人中文群聊里几乎不会打出 </word> 这种闭合标签，
# 而裸尖括号（3 < 5、a<b、->）必须留住，所以只删成对标签形态。
_TOOL_MARKUP = re.compile(
    r"</?[a-zA-Z][a-zA-Z0-9_:.-]*\s*/?>"   # <tag> </tag> <tag/> <ns:tag>
    r"|<\|[^|>]*\|>"                        # <|im_end|> <|channel|>
    r"|\[/?(?:TOOL|INST|ARG)[A-Z_]*\]",     # [TOOL_CALLS] [/INST]
)


def strip_tool_markup(text: str) -> str:
    """剥离模型工具调用标记。

    真实事故（2026-09-02 23:00，某技术交流群）：
    出站 ``对就这个</arg_value></tool_call>``。没有任何人类会打出
    这种字符串，一次就是当场坐实——比"反应太快"严重得多。

    事故当时 ``rewritten=False``、``identity_guard_triggered=False``，
    三层防护全部放行，因为它们都是黑名单、只认已记录的中文话术。

    按形态而非名字匹配，换模型也能兜住。裸尖括号（``3 < 5``、``a<b``）
    不受影响。

    Args:
        text: 待发送文本。

    Returns:
        str: 剥离标记后的文本；整条都是标记时返回空串，
            调用方应据此丢弃整条消息。
    """

    if not text:
        return text
    if "<" not in text and "[" not in text:
        return text

    cleaned = _TOOL_MARKUP.sub("", text)
    if cleaned == text:
        return text

    # 剥离后可能留下多余空白
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def has_command(text: str) -> bool:
    """判断文本是否含 shell 命令或 URL。

    Args:
        text: 待判定文本。

    Returns:
        bool: 含命令特征时返回 ``True``。
    """

    if not text:
        return False
    return bool(_COMMAND_PATTERN.search(text))


def _is_unbalanced(text: str) -> bool:
    """括号/引号未闭合，说明命令没写完。"""

    return (
        text.count("(") > text.count(")")
        or text.count("[") > text.count("]")
        or text.count('"') % 2 == 1
        or text.count("'") % 2 == 1
    )


def _needs_merge(prev_text: str, next_text: str) -> bool:
    """判断两段是否属于同一条被拆散的命令。"""

    if not prev_text or not next_text:
        return False

    # 后段以管道/逻辑符开头 —— 最典型的截断特征
    if _CONTINUATION_HEAD.match(next_text):
        return True

    # 前段括号没闭合
    if has_command(prev_text) and _is_unbalanced(prev_text):
        return True

    # 前段以管道/逻辑符结尾
    if re.search(r"(?:\||&&|\|\||\\)\s*$", prev_text):
        return True

    return False


def merge_split_commands(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把被上游拆散的命令段重新合并。

    只合并确实属于同一条命令的相邻文本段；普通聊天的连续短句
    保持原样（真人本来就会连发几句）。

    Args:
        segments: 上游给出的消息段列表。

    Returns:
        List[Dict[str, Any]]: 合并后的消息段列表。
    """

    if not segments:
        return []

    merged: List[Dict[str, Any]] = []
    for seg in segments:
        if not merged:
            merged.append(dict(seg))
            continue

        prev = merged[-1]
        both_text = (
            str(prev.get("type") or "") == "text"
            and str(seg.get("type") or "") == "text"
        )
        if not both_text:
            merged.append(dict(seg))
            continue

        prev_text = str(prev.get("data") or "")
        next_text = str(seg.get("data") or "")

        if _needs_merge(prev_text, next_text):
            # 用空格连接：管道符前后本来就该有空格，
            # 而 "cd /opt" + "&& ls" 直接拼会变成 "cd /opt&& ls"（仍可执行但难看）
            joiner = "" if next_text.startswith(" ") else " "
            prev["data"] = prev_text.rstrip() + joiner + next_text.lstrip()
        else:
            merged.append(dict(seg))

    return merged


def protect_commands(text: str) -> str:
    """修复命令与中文粘连。

    Args:
        text: 待处理文本。

    Returns:
        str: 命令与中文之间补齐分隔后的文本。
    """

    if not text or not has_command(text):
        return text
    if _ALREADY_FENCED.search(text):
        return text

    # 只在"命令字符 + 中文"的边界补空格
    return _GLUED_TO_CJK.sub(r"\1 ", text)


def format_command_segments(text: str) -> Tuple[str, Optional[str]]:
    """为含命令的文本套代码块，并给出 parse_mode。

    普通聊天返回 ``(原文, None)``——绝不对闲聊启用 Markdown，
    否则 ``*`` ``_`` 等字符会被当作格式标记吃掉或触发 400。

    Args:
        text: 待发送文本。

    Returns:
        Tuple[str, Optional[str]]: ``(处理后文本, parse_mode)``。
            parse_mode 为 ``None`` 时应以纯文本发送。
    """

    if not text or not has_command(text):
        return text, None

    if _ALREADY_FENCED.search(text):
        return text, "md"

    # 整条就是一个命令 → 用行内代码，视觉上更像随手贴
    stripped = text.strip()
    if "\n" not in stripped and len(stripped) <= 120:
        return f"`{stripped}`", "md"

    # 多行或长命令 → 围栏代码块
    return f"```\n{stripped}\n```", "md"

"""发言碎片化限制：一次最多 3 条，超出的合并。

## 事故背景

2026-09-03 群里两次点名，都紧跟在我们密集发言之后：

    14:35:49 我们打比方解释反代："所以反代就是帮你修条路过去"
    14:36:43 台风："搁这训练大模型来了"
    14:36:49 hiayu 复读

    15:21:42 我们连发讨论运费/清关
    15:22:34 台风："聊天机器人ban了吧，看了眼疼"
    15:22:43 hiayu 复读、15:22:50 ca_yuki 复读

两次都是台风起头、hiayu 秒复读，指向的都是**说话方式**。

## 数据

侦察 72189 条入站 / 1689 条出站：

    发言长度   真人 中位 14 字 / P90 57 / P99 166
              我们 中位 10 字 / P90 23 / P99  41
    话量排名   我们在 1548 人里排第 3 名

我们的句子**又短又均匀**。真人 P99 能到 166 字（一口气把事讲完），
我们最长才 41——说明一个完整意思被拆成好几条短消息连发。

真人在技术群里的表达是"写一段话"，AI 是"分行发短句"。
后者既有刷屏感，也是典型的 AI 腔。

## 本模块职责

只做一件事：把超过 3 段的发言合并成 3 段。
不负责拆分长句（那会走回碎片化老路），不负责改写内容。
"""

from typing import Any, Dict, List, Sequence

# 一次发言的最大段数。
#
# 取 1：用户明确投诉过"一下发好几条"。一次逻辑回复只发一条完整消息；
# 超出的文本段并入同一条（_join 保留标点与空格）。
MAX_SEGMENTS = 1

# 短语气词长度阈值。
#
# 不能无差别合并：真人连发"哈哈""确实""好""6"是**多个独立反应**，
# 不是一个被拆开的意思，合并成"好?6"反而不像人话。
# 只有较长的句子片段才值得合并——那才是"一句话被拆成多条"。
_INTERJECTION_MAX_LEN = 4

# 语气词豁免的段数上限。
#
# codex 审计指出：若豁免无上限，上游把长句拆成一堆 ≤4 字片段
# （"反代就" "是帮你" "修条路" "过去了"）就能完全绕过 3 段限制。
# 真人连发语气词也就三五条，超过就是异常。
_INTERJECTION_MAX_COUNT = 2

# 只有这些真正的独立反应词才享受"不合并"豁免；任意两个短片段
# （如"看这个""挺好玩"）仍合并成一条，避免绕过单条上限。
_INTERJECTION_TOKENS = frozenset({
    "哈", "哈哈", "哈哈哈", "哈哈哈哈", "笑死", "绷", "绷不住", "确实", "好", "好的",
    "行", "嗯", "嗯嗯", "哦", "哦哦", "6", "66", "666", "牛", "草", "啊", "对", "？", "?",
})

# 句末标点，合并时避免出现"。。"这类重复。
_TRAILING_PUNCT = "。！？；，、.!?;,"

# 续句连接词：以这些词开头的消息段，几乎可以断定是上一句被逗号/句号
# 切开后的后半句，而不是一条独立发言。真人极少用「而且」「因此」「或」
# 这类词单独起一条消息。
#
# ## 事故背景（脱敏）
#
# 一条需要锚定目标的安抚类回复被上游标点切分成两条发出：
#
#     消息A：「…有没有已经想好怎么做」
#     消息B：「或正在伤害自己…」      ← 以「或」起头，是 A 的后半句
#
# B 以「或」起头却被当成独立消息发出，不仅读起来断裂，还在期间插入
# 其他消息后丢失了对原目标的锚定。这类「一句话被切成两条」正是本模块
# 要消除的碎片化，只是发生在 3 段以内、原有段数上限拦不住的情形。
_CONTINUATION_PREFIXES = (
    "而且", "并且", "因此", "否则", "以及", "况且", "何况", "甚至",
    "或者", "或", "而", "并",
)

# 单字连接词的排除项：以其开头但语义独立的常见词不算续句。
# 例如「或许」（也许）是独立副词，不是列举式的「或」。
_CONTINUATION_PREFIX_EXCLUDE = ("或许",)


def _is_continuation(text: str) -> bool:
    """判断一段文本是否是上一句的续写（以续句连接词起头）。

    Args:
        text: 待判断的文本。

    Returns:
        bool: 判定为续句片段返回 ``True``。
    """

    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith(_CONTINUATION_PREFIX_EXCLUDE):
        return False
    return stripped.startswith(_CONTINUATION_PREFIXES)


def _merge_continuations(parts: Sequence[str]) -> List[str]:
    """把以续句连接词起头的片段并回紧邻的前一段（纯文本版）。

    只处理相邻片段，不跨越空段；合并用 :func:`_join` 补空格断句，
    不额外改写内容。段数上限之外单独生效，修复「一句话被切成两条」。

    Args:
        parts: 原始文本段列表。

    Returns:
        List[str]: 续句已并回前一段的列表。
    """

    result: List[str] = []
    for part in parts:
        if not part or not part.strip():
            continue
        if result and _is_continuation(part):
            result[-1] = _join([result[-1], part])
            continue
        result.append(part)
    return result


def _merge_message_continuations(
    segments: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """把以续句连接词起头的文本段并回紧邻的前一个文本段（消息段版）。

    仅在两段都是**相邻的纯文本段**且都不携带额外元数据（entities、
    reply_to 等，合并后 offset 会错位）时合并。中间隔着媒体段的两段
    属于不同语境，不合并。

    Args:
        segments: 上游给出的消息段列表。

    Returns:
        List[Dict[str, Any]]: 续句已并回前一段的消息段列表。
    """

    result: List[Dict[str, Any]] = []
    for seg in segments:
        is_text = str(seg.get("type") or "") == "text"
        cur_text = str(seg.get("data") or "")
        if (
            is_text
            and cur_text.strip()
            and result
            and str(result[-1].get("type") or "") == "text"
            and not _has_metadata(result[-1])
            and not _has_metadata(seg)
            and _is_continuation(cur_text)
        ):
            prev = dict(result[-1])
            prev["data"] = _join([str(prev.get("data") or ""), cur_text])
            result[-1] = prev
            continue
        result.append(seg)
    return result


def _needs_space(left: str, right: str) -> bool:
    """判断两段文本拼接时是否需要空格。

    **设计取舍**：合并的是句子片段而不是词语，所以一律加空格。

    曾经尝试过"中文之间不加空格"，但运行时无法区分
    「今天」+「天气」（词语，不该加）和
    「地址发我这周给你们发顺丰」+「澳洲的啊那运费比路由器贵」
    （两个完整句子，必须加）。

    粘成一坨完全不可读，多一个空格只是稍显松散——
    而且群里真人本来就用空格断句
    （真实语料："澳洲那边清关慢 顺丰海运空运都得小半个月打底"）。

    Args:
        left: 左侧文本。
        right: 右侧文本。

    Returns:
        bool: 需要空格返回 ``True``。
    """

    return bool(left and right)


def _join(parts: Sequence[str]) -> str:
    """把多段文本自然地拼成一段。

    句子之间补空格分隔——直接粘连会产出
    "来地址发我这周给你们发顺丰澳洲的啊那运费比路由器贵"
    这种读不断句的东西，比碎片化更不像人话。

    Args:
        parts: 待拼接的文本段。

    Returns:
        str: 拼接结果。
    """

    result = ""
    for part in parts:
        piece = part.strip()
        if not piece:
            continue
        if not result:
            result = piece
            continue
        # 前一段以标点收尾时，不再叠加新标点造成"。。"
        if result[-1] in _TRAILING_PUNCT and piece[0] in _TRAILING_PUNCT:
            piece = piece.lstrip(_TRAILING_PUNCT)
            if not piece:
                continue
        # 已有标点收尾就直接接，否则补空格断句
        sep = "" if result[-1] in _TRAILING_PUNCT else " "
        result += sep + piece
    return result


def _all_interjections(parts: Sequence[str]) -> bool:
    """判断这些段落是否全是短语气词。

    真人连发"哈哈""确实""好""6"是多个独立反应，
    合并它们只会产出"好?6"这种不像人话的东西。

    但豁免有段数上限：codex 审计指出，若无上限，
    上游把长句拆成一堆 ≤4 字片段就能完全绕过 3 段限制。

    Args:
        parts: 待判断的文本段。

    Returns:
        bool: 全部是短语气词且数量合理时返回 ``True``。
    """

    stripped = [p.strip() for p in parts if p.strip()]
    if len(stripped) > _INTERJECTION_MAX_COUNT:
        return False
    return all(len(p) <= _INTERJECTION_MAX_LEN and p in _INTERJECTION_TOKENS for p in stripped)


def limit_fragments(segments: Sequence[str]) -> List[str]:
    """把发言段数限制到 :data:`MAX_SEGMENTS` 以内（纯文本版）。

    超出的段落合并进最后一段，保留前面的节奏感，
    同时保证内容不丢——直接截断会让话说一半。

    例外：全部是短语气词时不合并（见 :func:`_all_interjections`）。

    Args:
        segments: 原始文本段列表。

    Returns:
        List[str]: 段数不超过 :data:`MAX_SEGMENTS` 的列表。
    """

    cleaned = [s for s in segments if s and s.strip()]
    # 先并回被标点切散的续句，再按段数上限处理。
    cleaned = _merge_continuations(cleaned)
    if len(cleaned) <= MAX_SEGMENTS:
        return cleaned
    if _all_interjections(cleaned):
        return cleaned

    head = list(cleaned[: MAX_SEGMENTS - 1])
    tail = _join(cleaned[MAX_SEGMENTS - 1:])
    if tail:
        head.append(tail)
    return head


def _has_metadata(seg: Dict[str, Any]) -> bool:
    """判断消息段是否携带 type/data 之外的元数据。

    entities（富文本格式）的 offset 是相对本段起始位置的，
    合并后会全部错位；reply_to 等字段合并后语义也不明确。
    这类段一律不参与合并——宁可多发一条，不能破坏内容。

    Args:
        seg: 待检查的消息段。

    Returns:
        bool: 携带额外字段返回 ``True``。
    """

    return any(k not in ("type", "data") for k in seg)


def limit_message_segments(
    segments: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """把消息段列表的**文本段**数量限制到 :data:`MAX_SEGMENTS`。

    这是接入发送链路的版本，处理 ``{"type": "text", "data": ...}``
    结构。非文本段（图片、表情等）原样保留且不计入段数上限——
    限制的是"话说了几条"，不是"发了几个东西"。

    合并时会检查被丢弃段是否携带额外字段（如 entities、reply_to），
    带元数据的段不参与合并，避免静默丢失格式信息。

    Args:
        segments: 上游给出的消息段列表。

    Returns:
        List[Dict[str, Any]]: 文本段不超过上限的消息段列表。
    """

    if not segments:
        return []

    # 先并回被标点切散的续句（如以「或」起头的后半句），再按文本段数上限处理。
    segments = _merge_message_continuations(segments)

    text_idx = [
        i
        for i, seg in enumerate(segments)
        if str(seg.get("type") or "") == "text"
        and str(seg.get("data") or "").strip()
    ]
    if len(text_idx) <= MAX_SEGMENTS:
        return segments

    texts = [str(segments[i].get("data") or "") for i in text_idx]
    if _all_interjections(texts):
        # 多个独立语气词，不是一个被拆开的意思
        return segments

    # 携带额外元数据的段不能合并——entities 的 offset 是相对本段的，
    # 拼接后会全部错位。codex 审计指出这会静默破坏格式。
    tail_idx = text_idx[MAX_SEGMENTS - 1:]
    if any(_has_metadata(segments[i]) for i in tail_idx):
        return segments

    keep_idx = set(text_idx[: MAX_SEGMENTS - 1])
    merge_from = tail_idx[0]
    merged_text = _join([str(segments[i].get("data") or "") for i in tail_idx])

    result: List[Dict[str, Any]] = []
    for i, seg in enumerate(segments):
        if str(seg.get("type") or "") != "text":
            result.append(seg)
            continue
        if i in keep_idx:
            result.append(seg)
        elif i == merge_from:
            new_seg = dict(seg)
            new_seg["data"] = merged_text
            result.append(new_seg)
        # 其余文本段已并入 merge_from，丢弃
    return result

"""从账号在单个聊天流中的既有消息推导风格控制。

这里不生成“像真人”的假设性语言，也不向模型提供模仿话术。它只统计本账号
已经发过的公开可见格式特征，并把足够稳定的特征写回聊天流画像卡。这样每个
部署和每个聊天流都有独立、可审计的输出边界，而不会被全局清洗器压成同一种
MaiBot 口吻。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import json
import os
import re
import stat
import statistics
import tempfile



def _p95_index(n: int) -> int:
    """最近秩法的 P95 零基索引：ceil(0.95 * n) - 1。"""
    import math
    return max(0, min(n - 1, math.ceil(0.95 * n) - 1))

def atomic_write_profile(path: Path, text: str) -> None:
    """原子发布完整画像，避免生成器读到刷新中的半份文件。"""
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.style-', delete=False) as handle:
            temporary = handle.name
            os.fchmod(handle.fileno(), mode)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)

_EMOJI_ONLY = re.compile(r"^[\W_]+$", flags=re.UNICODE)
# 分隔线只吃行内空白和自身换行，不吞掉正文前导空行/缩进。
_FRONTMATTER = re.compile(r"^(---[^\S\r\n]*\r?\n)(.*?)(\r?\n---[^\S\r\n]*(?:\r?\n|$))(.*)$", re.S)


@dataclass(frozen=True)
class StyleControls:
    """从一个聊天流的本人历史消息中获得的格式控制。"""

    sample_count: int
    style_enabled: bool
    allow_emoji_only: bool
    max_emoji: int
    preserve_trailing_period: bool
    max_chars: int
    peer_sample_count: int = 0
    peer_median_chars: float = 0.0
    peer_question_rate: float = 0.0



def is_adapter_envelope(text: str) -> bool:
    """识别未清洗的适配器协议头和附件占位符。"""

    return text.startswith("[回复<") or text.startswith("[文件:")


def _is_emoji_only(text: str) -> bool:
    """只识别由 emoji/标点组成的短反应，不把正常文字误判进去。"""

    # 非文字正则也匹配问号/省略号；至少存在一个表情码点才作为采样证据。
    # 保守识别常见表情区间，不声称覆盖全部 Unicode emoji 序列。
    has_emoji = any(0x1F000 <= ord(c) <= 0x1FAFF or 0x2600 <= ord(c) <= 0x27BF for c in text)
    return bool(text and has_emoji and _EMOJI_ONLY.fullmatch(text))


def _load_owner_id(data_dir: Path) -> str:
    """读取当前部署本地账号画像中的 ID。"""

    raw = json.loads((data_dir / "account_profile.json").read_text(encoding="utf-8"))
    owner_id = str(raw.get("user_id") or "").strip()
    if not owner_id:
        raise ValueError("account_profile.json 缺少 user_id")
    return owner_id


def _collect_outbound_messages(data_dir: Path, owner_id: str) -> dict[str, list[str]]:
    """合并操作员声明语料与本账号入站文本，不采样自动出站。"""

    grouped: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()
    # 文件名沿用导入器约定；operator_attested_owner 仅表示操作员声明，
    # 不代表独立认证为真人。先读显式语料，按消息 ID 优先于 transcript。
    corpus = data_dir / "style_corpus" / "owner_verified.jsonl"
    if corpus.is_file():
        for line in corpus.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if (
                type(row.get("schema_version")) is not int
                or row["schema_version"] != 1
                or row.get("source") != "operator_attested_owner"
                or row.get("sender_id") != owner_id
            ):
                continue
            if any(not isinstance(row.get(key), str) or not row[key].strip()
                   for key in ("chat_id", "message_id", "text")):
                continue
            chat_id = row["chat_id"]
            if not re.fullmatch(r"-?[0-9]+(?:::tg-topic::mt=[0-9]+)?", chat_id):
                continue
            text = row["text"].strip()
            key = (chat_id, row["message_id"].strip())
            if is_adapter_envelope(text) or key in seen:
                continue
            seen.add(key)
            grouped.setdefault(chat_id, []).append(text)
    for path in sorted((data_dir / "transcripts").glob("chat_*.jsonl")):
        if path.name == "chat___usage__.jsonl":
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            # 自动出站是模型产物，不是主人真实表达；禁止用它自我强化画像。
            # 仅保留明确标注为入站且作者为本账号的记录，未知方向不猜测。
            if row.get("direction") != "in" or str(row.get("sender_id") or "") != owner_id:
                continue
            chat_id = str(row.get("chat_id") or "").strip()
            text = str(row.get("text") or "").strip()
            message_id = str(row.get("message_id") or "").strip()
            key = (chat_id, message_id or text)
            if not chat_id or not text or is_adapter_envelope(text) or key in seen:
                continue
            seen.add(key)
            grouped.setdefault(chat_id, []).append(text)
    return grouped


def _collect_peer_messages(data_dir: Path, owner_id: str) -> dict[str, list[str]]:
    """按聊天流收集非本账号发出的文本，作为局部语言基线。

    这里仅统计已落盘的群消息，不把统计结果当成可复制的台词。它只用于让
    replyer 知道本群常见的长度和追问密度，避免全局统一的短答模板。
    """

    grouped: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()
    for path in sorted((data_dir / "transcripts").glob("chat_*.jsonl")):
        if path.name == "chat___usage__.jsonl":
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            sender_id = str(row.get("sender_id") or "").strip()
            if (
                row.get("direction") != "in"
                or not sender_id
                or sender_id == owner_id
                or row.get("is_private") is not False
            ):
                continue
            chat_id = str(row.get("chat_id") or "").strip()
            text = str(row.get("text") or "").strip()
            # 只统计当前作者正文，不能把被引用者的问号、长度算到回复者身上。
            # 旧日志没有结构化 reply_text；格式不完整时舍弃，不猜测内容边界。
            if text.startswith("[回复<"):
                _, separator, body = text.partition("]，说：")
                if not separator:
                    continue
                text = body.strip()
            message_id = str(row.get("message_id") or "").strip()
            key = (chat_id, message_id or text)
            if not chat_id or not text or is_adapter_envelope(text) or key in seen:
                continue
            seen.add(key)
            grouped.setdefault(chat_id, []).append(text)
    return grouped


def _validate_min_samples(min_samples: int) -> None:
    """在读取样本或访问画像文件前验证门槛，避免后台绕过 CLI 校验。"""
    if type(min_samples) is not int or min_samples < 1:
        raise ValueError('min_samples must be a positive integer')


_MANAGED_STYLE_FIELDS = {
    "style_enabled", "allow_emoji_only", "max_emoji", "preserve_trailing_period",
    "style_max_chars", "peer_style_samples", "peer_median_chars", "peer_question_rate",
    "style_source", "style_owner_samples",
}


def _style_refresh_allowed(existing: str) -> bool:
    """只接管空白风格区或来源明确的自动画像；人工/歧义字段不猜归属。"""
    match = _FRONTMATTER.match(existing)
    if not match:
        return not existing.lstrip().startswith("---")
    fields: dict[str, list[str]] = {}
    for line in match.group(2).splitlines():
        key, separator, value = line.partition(":")
        key = key.strip().strip("\"'")
        if separator and (key in _MANAGED_STYLE_FIELDS or key == "manual_style_enabled"):
            fields.setdefault(key, []).append(value.strip())
    # 即使人工开关为 false，也不是自动刷新可以重新接管的授权。
    if "manual_style_enabled" in fields:
        return False
    if not fields:
        return True
    if any(len(values) != 1 for values in fields.values()):
        return False
    # 仅接受生成器自己的无歧义来源声明，其他来源需操作员显式迁移。
    if fields.get("style_source") != ["owner_inbound_v1"]:
        return False
    if "style_enabled" in fields and fields["style_enabled"] != ["true"]:
        return False
    return True


def sync_style_profiles(data_dir: Path, *, min_samples: int = 20) -> list[str]:
    """从一个部署的本地 transcript 生成或刷新全部合格聊天流画像。"""

    _validate_min_samples(min_samples)
    updated_chats = []
    owner_id = _load_owner_id(data_dir)
    peer_messages_by_chat = _collect_peer_messages(data_dir, owner_id)
    owner_messages = _collect_outbound_messages(data_dir, owner_id)
    # 无剩余样本的旧自动画像也必须被检查，不能只遍历非空采样结果。
    existing_chats = {p.parent.name for p in (data_dir / "chats").glob("*/SKILL.md")}
    for chat_id in sorted(set(owner_messages) | existing_chats):
        messages = owner_messages.get(chat_id, [])
        controls = derive_style_controls(
            messages,
            peer_messages_by_chat.get(chat_id, []),
            min_samples=min_samples,
        )
        path = data_dir / "chats" / chat_id / "SKILL.md"
        existing = path.read_bytes().decode("utf-8") if path.is_file() else ""
        if not _style_refresh_allowed(existing):
            continue
        frontmatter = _FRONTMATTER.match(existing)
        # 明确关闭是操作员选择；样本充足也不能由自动刷新擅自重新启用。
        if frontmatter and re.search(
            r"(?mi)^\s*style_enabled:\s*false\s*(?:#.*)?$", frontmatter.group(2)
        ):
            continue
        if not controls.style_enabled:
            # 仅撤回本版本明确生成的启用字段；未知来源保持原样待迁移。
            if not frontmatter or not re.search(
                r"(?m)^style_source: owner_inbound_v1\s*$", frontmatter.group(2)
            ):
                continue
            front = re.sub(r"(?mi)^style_enabled:\s*true\s*$", "style_enabled: false", frontmatter.group(2))
            front = re.sub(r"(?m)^style_owner_samples:.*$", f"style_owner_samples: {controls.sample_count}", front)
            updated = frontmatter.group(1) + front + frontmatter.group(3) + frontmatter.group(4)
            if updated != existing:
                atomic_write_profile(path, updated)
                updated_chats.append(chat_id)
            continue
        updated = merge_style_frontmatter(existing, controls)
        # 无变化时不替换文件，避免虚报更新并触发不必要的缓存失效。
        if updated != existing:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_profile(path, updated)
            updated_chats.append(chat_id)
    return sorted(updated_chats)


def _count_emoji(text: str) -> int:
    """返回常见 Unicode emoji 的粗略数量，用于上限而非语义判断。"""

    return sum(1 for char in text if ord(char) >= 0x1F000)


def derive_style_controls(
    messages: Iterable[str],
    peer_messages: Iterable[str] = (),
    *,
    min_samples: int = 20,
) -> StyleControls:
    """从本人消息和同群真人消息推导保守的会话风格控制。

    本人历史只决定账号已经稳定的格式习惯；同群真人消息只提供局部长度、
    追问密度基线。二者均不提供可复用措辞，避免把检索到的话变成模仿台词。
    """

    _validate_min_samples(min_samples)
    peer_texts = [" ".join(str(text).split()) for text in peer_messages]
    peer_texts = [text for text in peer_texts if text and not is_adapter_envelope(text)]
    peer_lengths = sorted(len(text) for text in peer_texts)
    peer_median_chars = statistics.median(peer_lengths) if peer_lengths else 0
    peer_question_rate = (
        sum("?" in text or "？" in text for text in peer_texts) / len(peer_texts)
        if peer_texts
        else 0.0
    )

    normalized = [" ".join(str(text).split()) for text in messages]
    texts = [text for text in normalized if text]
    sample_count = len(texts)
    if sample_count < min_samples:
        return StyleControls(
            sample_count, False, False, 1, False, 0,
            len(peer_texts), peer_median_chars, peer_question_rate,
        )

    emoji_only_count = sum(_is_emoji_only(text) for text in texts)
    emoji_counts = sorted(_count_emoji(text) for text in texts)
    period_count = sum(text.endswith(("。", ".")) for text in texts)

    # 至少两次才算该聊天流的习惯，避免单个样本改变全群策略。
    allow_emoji_only = emoji_only_count >= 2 and emoji_only_count / sample_count >= 0.02
    # P95 决定上限，限制极端堆叠，但不把常见的两个 emoji 压成一律一个。
    max_emoji = max(1, emoji_counts[_p95_index(sample_count)])
    # 句号同样需要重复出现才保留，偶然一次不改变整体策略。
    preserve_trailing_period = period_count >= 2 and period_count / sample_count >= 0.05
    # P95 留出正常表达空间；上限只会与已有风险卡取更严格的值。
    lengths = sorted(len(text) for text in texts)
    max_chars = lengths[_p95_index(sample_count)]

    return StyleControls(
        sample_count=sample_count,
        style_enabled=True,
        allow_emoji_only=allow_emoji_only,
        max_emoji=max_emoji,
        preserve_trailing_period=preserve_trailing_period,
        max_chars=max_chars,
        peer_sample_count=len(peer_texts),
        peer_median_chars=peer_median_chars,
        peer_question_rate=peer_question_rate,
    )


def render_style_frontmatter(controls: StyleControls) -> str:
    """渲染可直接合并进聊天流 SKILL.md 的风格字段。"""

    if not controls.style_enabled:
        return ""
    return "\n".join(
        [
            "style_enabled: true",
            "style_source: owner_inbound_v1",
            f"style_owner_samples: {controls.sample_count}",
            f"allow_emoji_only: {str(controls.allow_emoji_only).lower()}",
            f"max_emoji: {controls.max_emoji}",
            f"preserve_trailing_period: {str(controls.preserve_trailing_period).lower()}",
            f"style_max_chars: {controls.max_chars}",
            f"peer_style_samples: {controls.peer_sample_count}",
            f"peer_median_chars: {controls.peer_median_chars}",
            f"peer_question_rate: {controls.peer_question_rate:.4f}",
            "",
        ]
    )


def merge_style_frontmatter(existing: str, controls: StyleControls) -> str:
    """把自动风格字段合并进已有画像，绝不放宽人工风险长度上限。"""

    if not _style_refresh_allowed(existing):
        return existing
    style_text = render_style_frontmatter(controls)
    if not style_text:
        return existing
    # 所有自动字段必须替换而不是追加，否则每小时刷新会产生重复键。
    managed = _MANAGED_STYLE_FIELDS
    match = _FRONTMATTER.match(existing)
    if match:
        front_lines = [
            line for line in match.group(2).splitlines()
            if line.partition(":")[0].strip() not in managed
        ]
        front = "\n".join(line for line in front_lines if line.strip())
        if front:
            front += "\n"
        return f"---\n{front}{style_text}---\n{match.group(4)}"
    return f"---\n{style_text}---\n{existing}"

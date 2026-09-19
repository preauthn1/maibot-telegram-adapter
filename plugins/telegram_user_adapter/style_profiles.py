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
import re

_EMOJI_ONLY = re.compile(r"^[\W_]+$", flags=re.UNICODE)
_FRONTMATTER = re.compile(r"^(---\s*\n)(.*?)(\n---\s*\n?)(.*)$", re.S)


@dataclass(frozen=True)
class StyleControls:
    """从一个聊天流的本人历史消息中获得的格式控制。"""

    sample_count: int
    style_enabled: bool
    allow_emoji_only: bool
    max_emoji: int
    preserve_trailing_period: bool
    max_chars: int




def is_adapter_envelope(text: str) -> bool:
    """识别未清洗的适配器协议头和附件占位符。"""

    return text.startswith("[回复<") or text.startswith("[文件:")


def _is_emoji_only(text: str) -> bool:
    """只识别由 emoji/标点组成的短反应，不把正常文字误判进去。"""

    return bool(text and _EMOJI_ONLY.fullmatch(text))


def _load_owner_id(data_dir: Path) -> str:
    """读取当前部署本地账号画像中的 ID。"""

    raw = json.loads((data_dir / "account_profile.json").read_text(encoding="utf-8"))
    owner_id = str(raw.get("user_id") or "").strip()
    if not owner_id:
        raise ValueError("account_profile.json 缺少 user_id")
    return owner_id


def _collect_outbound_messages(data_dir: Path, owner_id: str) -> dict[str, list[str]]:
    """按聊天流收集当前部署账号已经发送的去重文本。"""

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
            if str(row.get("sender_id") or "") != owner_id and row.get("direction") != "out":
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


def sync_style_profiles(data_dir: Path, *, min_samples: int = 20) -> list[str]:
    """从一个部署的本地 transcript 生成或刷新全部合格聊天流画像。"""

    updated_chats = []
    for chat_id, messages in _collect_outbound_messages(data_dir, _load_owner_id(data_dir)).items():
        controls = derive_style_controls(messages, min_samples=min_samples)
        if not controls.style_enabled:
            continue
        path = data_dir / "chats" / chat_id / "SKILL.md"
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(merge_style_frontmatter(existing, controls), encoding="utf-8")
        updated_chats.append(chat_id)
    return sorted(updated_chats)


def _count_emoji(text: str) -> int:
    """返回常见 Unicode emoji 的粗略数量，用于上限而非语义判断。"""

    return sum(1 for char in text if ord(char) >= 0x1F000)


def derive_style_controls(messages: Iterable[str], *, min_samples: int = 20) -> StyleControls:
    """从去重后的本人消息中推导保守的会话风格控制。

    样本不足时不启用覆盖，宁可继续使用安全的全局默认，也不能从几句话中
    猜出一个人格。所有阈值都基于消息自身出现率，不引入模型或外部语料。
    """

    normalized = [" ".join(str(text).split()) for text in messages]
    texts = [text for text in normalized if text]
    sample_count = len(texts)
    if sample_count < min_samples:
        return StyleControls(sample_count, False, False, 1, False, 0)

    emoji_only_count = sum(_is_emoji_only(text) for text in texts)
    emoji_counts = sorted(_count_emoji(text) for text in texts)
    period_count = sum(text.endswith(("。", ".")) for text in texts)

    # 纯 emoji 至少出现两次且占比不低于 2%，才认定为该聊天流的稳定习惯。
    allow_emoji_only = emoji_only_count >= 2 and emoji_only_count / sample_count >= 0.02
    # P90 决定上限，限制极端堆叠，但不把常见的两个 emoji 压成一律一个。
    max_emoji = max(1, emoji_counts[min(len(emoji_counts) - 1, int(sample_count * 0.9))])
    # 句号只有明显属于该聊天流的常规结尾时才保留；偶然一次不改变策略。
    preserve_trailing_period = period_count >= 2 and period_count / sample_count >= 0.05
    # P90 留出正常表达空间；上限只会与已有风险卡取更严格的值。
    lengths = sorted(len(text) for text in texts)
    max_chars = lengths[min(len(lengths) - 1, int(sample_count * 0.9))]

    return StyleControls(
        sample_count=sample_count,
        style_enabled=True,
        allow_emoji_only=allow_emoji_only,
        max_emoji=max_emoji,
        preserve_trailing_period=preserve_trailing_period,
        max_chars=max_chars,
    )


def render_style_frontmatter(controls: StyleControls) -> str:
    """渲染可直接合并进聊天流 SKILL.md 的风格字段。"""

    if not controls.style_enabled:
        return ""
    return "\n".join(
        [
            "style_enabled: true",
            f"allow_emoji_only: {str(controls.allow_emoji_only).lower()}",
            f"max_emoji: {controls.max_emoji}",
            f"preserve_trailing_period: {str(controls.preserve_trailing_period).lower()}",
            f"style_max_chars: {controls.max_chars}",
            "",
        ]
    )


def merge_style_frontmatter(existing: str, controls: StyleControls) -> str:
    """把自动风格字段合并进已有画像，绝不放宽人工风险长度上限。"""

    style_text = render_style_frontmatter(controls)
    if not style_text:
        return existing
    managed = {"style_enabled", "allow_emoji_only", "max_emoji", "preserve_trailing_period", "style_max_chars"}
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
    return f"---\n{style_text}---\n{existing.lstrip()}"

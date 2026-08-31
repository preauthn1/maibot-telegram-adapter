"""按群加载画像卡（SKILL.md）。

问题：群画像原本硬编码在 high_risk_chats.py 里，加一个群要改代码、
跑测试、重启。而群的性质是会变的——人数、话题、语感都在漂移，
硬编码扛不住。

改为每群一份 Markdown 画像卡，放在
``data/plugins/<plugin_id>/chats/<chat_id>/SKILL.md``。

格式是带 YAML frontmatter 的 Markdown：frontmatter 存机器要用的
约束参数，正文写人看的观察记录与注意事项。这样既能被代码读取，
也方便人直接翻阅和修改。

热加载：每次读取时检查文件 mtime，改完不用重启。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import re


@dataclass
class ChatProfile:
    """单个群的画像。

    Attributes:
        chat_id: 会话 ID。
        title: 群名，仅用于日志可读性。
        max_chars: 单条消息字符上限；0 表示不限。
        reply_ratio: 参与率上限；None 表示用默认值。
        min_gap_seconds: 两次发言最小间隔；None 表示用默认值。
        block_tech: 是否回避技术话题。
        extra_keywords: 该群额外的禁谈关键词。
        notes: 人类可读的观察记录。
    """

    chat_id: str
    title: str = ""
    max_chars: float = 0.0
    reply_ratio: Optional[float] = None
    min_gap_seconds: Optional[float] = None
    block_tech: bool = False
    extra_keywords: Set[str] = field(default_factory=set)
    notes: str = ""


_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


def _parse_scalar(raw: str) -> Any:
    """把 frontmatter 的标量值转成 Python 类型。

    只支持画像卡需要的几种类型，不引入 YAML 依赖——
    画像卡是给人写的，保持格式简单比支持全部 YAML 语法更重要。

    Args:
        raw: 冒号右侧的原始字符串。

    Returns:
        Any: 解析后的值。
    """

    value = raw.strip().strip("\"'")
    lowered = value.lower()
    if lowered in {"true", "yes"}:
        return True
    if lowered in {"false", "no"}:
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("\"'") for item in inner.split(",") if item.strip()]
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value


def parse_profile(chat_id: str, text: str) -> ChatProfile:
    """解析一份画像卡。

    Args:
        chat_id: 会话 ID。
        text: SKILL.md 全文。

    Returns:
        ChatProfile: 解析结果；缺失字段用默认值。
    """

    profile = ChatProfile(chat_id=chat_id)

    match = _FRONTMATTER.match(text)
    if not match:
        # 没有 frontmatter 时整篇都当作观察记录，不影响行为。
        profile.notes = text.strip()
        return profile

    front, body = match.group(1), match.group(2)
    profile.notes = body.strip()

    for line in front.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, raw = stripped.partition(":")
        value = _parse_scalar(raw)
        key = key.strip()

        if key == "title":
            profile.title = str(value)
        elif key == "max_chars":
            profile.max_chars = float(value) if isinstance(value, (int, float)) else 0.0
        elif key == "reply_ratio":
            profile.reply_ratio = float(value) if isinstance(value, (int, float)) else None
        elif key == "min_gap_seconds":
            profile.min_gap_seconds = (
                float(value) if isinstance(value, (int, float)) else None
            )
        elif key == "block_tech":
            profile.block_tech = bool(value)
        elif key == "extra_keywords" and isinstance(value, list):
            profile.extra_keywords = {str(item).lower() for item in value}

    return profile


class ChatProfileStore:
    """管理所有群的画像卡，支持热加载。"""

    def __init__(self, root: Path) -> None:
        """初始化。

        Args:
            root: 画像卡根目录，通常是 ``<data_dir>/chats``。
        """

        self._root = root
        self._cache: Dict[str, ChatProfile] = {}
        self._mtimes: Dict[str, float] = {}

    def _path(self, chat_id: str) -> Path:
        return self._root / str(chat_id) / "SKILL.md"

    def get(self, chat_id: str) -> Optional[ChatProfile]:
        """读取某群的画像，文件变更时自动重载。

        Args:
            chat_id: 会话 ID。

        Returns:
            Optional[ChatProfile]: 无画像卡时返回 ``None``。
        """

        key = str(chat_id)
        path = self._path(key)
        if not path.is_file():
            self._cache.pop(key, None)
            self._mtimes.pop(key, None)
            return None

        mtime = path.stat().st_mtime
        if self._mtimes.get(key) != mtime:
            # 改完画像卡不用重启——群的性质本来就在漂移，
            # 要能随时调整。
            self._cache[key] = parse_profile(key, path.read_text(encoding="utf-8"))
            self._mtimes[key] = mtime

        return self._cache.get(key)

    def list_chats(self) -> List[str]:
        """列出已有画像卡的会话 ID。"""

        if not self._root.is_dir():
            return []
        return sorted(
            d.name for d in self._root.iterdir() if (d / "SKILL.md").is_file()
        )

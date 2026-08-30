"""聊天行为经验共享。

自我改进模块（插件侧）负责**累积**经验，本模块负责把经验**注入 prompt**。

之所以放在主程序而不是插件里：prompt 组装发生在 ``maisaka_generator_base``，
插件运行在独立进程，无法直接改 prompt。因此插件把经验写到磁盘上的约定路径，
主程序在构建人设时读取。

这是一个**单向、只读、可失败**的通道：文件不存在或读取失败都只是少一段
prompt，绝不影响正常回复。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import time

# 插件把经验写到各自 data_dir 下的这个文件名。
_AVOID_FILE_NAME = "prompt_experience.txt"

# 缓存，避免每次生成回复都读盘。
_CACHE_TTL_SECONDS = 30.0
_cache_value: str = ""
_cache_at: float = 0.0
_cache_path: Optional[Path] = None


def _resolve_experience_path() -> Optional[Path]:
    """查找插件写出的经验文件。

    Returns:
        Optional[Path]: 找到的文件路径；未找到时返回 ``None``。
    """

    plugin_data_root = Path("data") / "plugins"
    if not plugin_data_root.is_dir():
        return None

    for candidate in sorted(plugin_data_root.glob(f"*/{_AVOID_FILE_NAME}")):
        if candidate.is_file():
            return candidate
    return None


def build_experience_prompt_block(max_chars: int = 600) -> str:
    """读取聊天经验并组装成 prompt 片段。

    Args:
        max_chars: 返回文本的长度上限，避免挤占上下文。

    Returns:
        str: prompt 片段；无经验或读取失败时返回空串。
    """

    global _cache_value, _cache_at, _cache_path

    now = time.monotonic()
    if _cache_value and (now - _cache_at) < _CACHE_TTL_SECONDS:
        return _cache_value

    path = _cache_path if _cache_path is not None and _cache_path.is_file() else _resolve_experience_path()
    if path is None:
        _cache_value = ""
        _cache_at = now
        return ""

    _cache_path = path
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        # 读不到就当没有经验，不影响正常回复。
        _cache_value = ""
        _cache_at = now
        return ""

    _cache_value = raw[:max_chars] if raw else ""
    _cache_at = now
    return _cache_value

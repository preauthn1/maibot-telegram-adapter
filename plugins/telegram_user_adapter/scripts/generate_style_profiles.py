"""从本地 transcript 为每个聊天流写入独立风格控制。

只读取该账号已经发送的文本，不请求网络、不上传聊天内容。生成结果合并进每个
``chats/<chat_id>/SKILL.md`` 的 YAML frontmatter；已有的风险控制字段与正文保留。

用法：
    .venv/bin/python plugins/telegram_user_adapter/scripts/generate_style_profiles.py \
      --data-dir data/plugins/preauthn1.telegram-user-adapter
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import sys

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT.parent))

from telegram_user_adapter.style_profiles import derive_style_controls, merge_style_frontmatter


def _load_owner_id(data_dir: Path) -> str:
    """从适配器账户画像读取账号 ID，避免在脚本中写死账号。"""

    profile_path = data_dir / "account_profile.json"
    raw = json.loads(profile_path.read_text(encoding="utf-8"))
    owner_id = str(raw.get("user_id") or "").strip()
    if not owner_id:
        raise ValueError(f"{profile_path} 缺少 user_id")
    return owner_id


def _collect_outbound_messages(data_dir: Path, owner_id: str) -> dict[str, list[str]]:
    """按聊天流收集并去重本账号的出站文本。"""

    grouped: dict[str, list[str]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    transcript_dir = data_dir / "transcripts"
    for path in sorted(transcript_dir.glob("chat_*.jsonl")):
        if path.name == "chat___usage__.jsonl":
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(row.get("sender_id") or "") != owner_id and row.get("direction") != "out":
                continue
            chat_id = str(row.get("chat_id") or "").strip()
            text = str(row.get("text") or "").strip()
            message_id = str(row.get("message_id") or "").strip()
            if not chat_id or not text:
                continue
            key = (chat_id, message_id or text)
            if key in seen:
                continue
            seen.add(key)
            grouped[chat_id].append(text)
    return grouped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--min-samples", type=int, default=20)
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    owner_id = _load_owner_id(data_dir)
    messages_by_chat = _collect_outbound_messages(data_dir, owner_id)
    changed = 0
    for chat_id, messages in sorted(messages_by_chat.items()):
        controls = derive_style_controls(messages, min_samples=args.min_samples)
        if not controls.style_enabled:
            print(f"跳过 {chat_id}: 样本 {controls.sample_count} < {args.min_samples}")
            continue
        skill_path = data_dir / "chats" / chat_id / "SKILL.md"
        existing = skill_path.read_text(encoding="utf-8") if skill_path.is_file() else ""
        updated = merge_style_frontmatter(existing, controls)
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text(updated, encoding="utf-8")
        changed += 1
        print(
            f"已写入 {chat_id}: 样本={controls.sample_count} "
            f"emoji_only={controls.allow_emoji_only} max_emoji={controls.max_emoji} "
            f"keep_period={controls.preserve_trailing_period}"
        )
    print(f"完成：更新 {changed} 个聊天流")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""输出一个部署自身的语言指纹指标快照，不上传也不展示聊天原文。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from generate_style_profiles import _collect_outbound_messages, _load_owner_id

import sys

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT.parent))

from telegram_user_adapter.style_metrics import compute_style_metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    messages = _collect_outbound_messages(data_dir, _load_owner_id(data_dir))
    report = compute_style_metrics(messages)
    payload = {
        "sample_count": report.sample_count,
        "chat_count": len(messages),
        "cross_chat_reuse_rate": round(report.cross_chat_reuse_rate, 6),
        "length_entropy": round(report.length_entropy, 6),
        "top_opening_words": report.top_opening_words,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

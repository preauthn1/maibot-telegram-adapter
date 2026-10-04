"""从来源合格的本账号入站记录刷新会话风格画像。

复用运行时同步入口，避免 CLI 与后台刷新在采样、撤回和人工禁用上分叉。
不请求网络，不上传聊天正文。
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT.parent))

# 保留旧指标脚本的导入接口，但统一到同一个来源过滤实现。
from telegram_user_adapter.style_profiles import (
    _collect_outbound_messages,
    _load_owner_id,
    sync_style_profiles,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--min-samples', type=int, default=20)
    args = parser.parse_args()
    if args.min_samples < 1:
        parser.error('--min-samples must be positive')
    updated = sync_style_profiles(args.data_dir.resolve(), min_samples=args.min_samples)
    print(f'完成：更新 {len(updated)} 个聊天流')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

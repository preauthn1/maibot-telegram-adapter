#!/usr/bin/env python3
"""从 transcript 汇总用量洞察，输出成本报告。

插件运行时每 50 次出站会把用量快照写进 transcript 的
``usage_insight`` 事件。这个脚本把落盘的快照读回来，
回答三个问题：

1. 总共消耗多少 token、估算多少钱
2. 哪个会话最烧 token
3. 平均单次消耗是否在上涨（上下文膨胀信号）

用法：
    .venv/bin/python scripts/usage_report.py
    .venv/bin/python scripts/usage_report.py --days 7
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import argparse
import glob
import json

CN = timezone(timedelta(hours=8))
TRANSCRIPT_GLOB = (
    "/root/MaiBot/data/plugins/preauthn1.telegram-user-adapter/transcripts/*.jsonl"
)


def load_snapshots(days: int) -> List[Dict[str, Any]]:
    """读取指定天数内的用量快照。

    Args:
        days: 回溯天数。

    Returns:
        List[Dict[str, Any]]: 快照列表，按时间升序。
    """

    cutoff = datetime.now(CN) - timedelta(days=days)
    snapshots: List[Dict[str, Any]] = []

    for path in glob.glob(TRANSCRIPT_GLOB):
        for line in Path(path).open(encoding="utf-8", errors="ignore"):
            line = line.strip()
            if not line.startswith("{") or "usage_insight" not in line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("event") != "usage_insight":
                continue
            stamp = item.get("ts", "")
            try:
                when = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            if when < cutoff:
                continue
            detail = item.get("detail", {})
            detail["_ts"] = when
            snapshots.append(detail)

    snapshots.sort(key=lambda d: d["_ts"])
    return snapshots


def main() -> int:
    """入口。

    Returns:
        int: 退出码。
    """

    parser = argparse.ArgumentParser(description="用量与成本洞察")
    parser.add_argument("--days", type=int, default=7, help="回溯天数（默认 7）")
    args = parser.parse_args()

    snapshots = load_snapshots(args.days)
    if not snapshots:
        print(f"最近 {args.days} 天没有用量快照。")
        print("插件每 50 次出站写一次；账号当前处于封禁停机状态，属正常。")
        return 0

    latest = snapshots[-1]
    print(f"════ 用量报告（最近 {args.days} 天，{len(snapshots)} 个快照）════\n")
    print(f"最新快照时间   {latest['_ts']:%m-%d %H:%M}")
    print(f"累计调用       {latest.get('calls', 0)} 次")
    print(
        f"累计 token     {latest.get('prompt_tokens', 0) + latest.get('completion_tokens', 0)}"
        f"（入 {latest.get('prompt_tokens', 0)} / 出 {latest.get('completion_tokens', 0)}）"
    )
    print(f"平均单次       {latest.get('avg_tokens_per_call', 0)} token")
    print(f"估算成本       ${latest.get('estimated_cost', 0):.4f}")

    top = latest.get("top_sessions", [])
    if top:
        print("\n消耗最高的会话:")
        for row in top:
            calls = row.get("calls", 0)
            tokens = row.get("tokens", 0)
            avg = tokens / calls if calls else 0
            print(f"  {row.get('session', '?')}: {tokens} token（{calls} 次，均 {avg:.0f}）")

    # 上下文膨胀检测：均值是否持续上涨
    if len(snapshots) >= 3:
        averages = [s.get("avg_tokens_per_call", 0) for s in snapshots]
        first, last = averages[0], averages[-1]
        if first > 0:
            change = (last - first) / first * 100
            print(f"\n平均单次消耗变化 {first:.0f} → {last:.0f}（{change:+.1f}%）")
            if change > 30:
                print("  ⚠️ 均值涨幅超 30%，可能是上下文膨胀，建议检查历史裁剪")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase 5 monitor CLI: record evidence, triage, and enqueue review jobs."""
from __future__ import annotations
import argparse, json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.self_evolution.monitor import EvolutionMonitor, MetricEvent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data/self-evolution/monitor"))
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record")
    record.add_argument("--target", required=True)
    record.add_argument("--outcome", required=True)
    record.add_argument("--score", type=float, required=True)
    record.add_argument("--usage-count", type=int, default=1)
    triage = sub.add_parser("triage")
    triage.add_argument("--min-usage", type=int, default=1)
    triage.add_argument("--failure-threshold", type=float, default=.5)
    args = parser.parse_args()
    monitor = EvolutionMonitor(args.root)
    if args.command == "record":
        added = monitor.record(MetricEvent(args.target, args.outcome, args.score, args.usage_count))
        print(json.dumps({"recorded": added}, ensure_ascii=False))
    else:
        items = monitor.triage(min_usage=args.min_usage, failure_threshold=args.failure_threshold)
        jobs = monitor.enqueue_jobs(items)
        print(json.dumps({"triage": [item.__dict__ for item in items], "jobs": jobs}, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

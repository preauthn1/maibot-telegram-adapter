"""Phase4 Darwinian CLI：只运行外部官方 worker，不导入 AGPL 包。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.self_evolution.code_evolution import run_darwinian


def main() -> int:
    parser = argparse.ArgumentParser(description="MaiBot Phase4 Darwinian external-worker runner")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--darwinian-python", type=Path, default=Path("/root/maibot-darwinian-venv/bin/python"))
    parser.add_argument("--output-root", type=Path, default=Path("data/self-evolution/code-candidates"))
    parser.add_argument("--num-iterations", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--mutator-command", nargs="+", required=True,
                        help="显式 argv 模板；必须含 {source} {candidate} {failure_cases} {learning_log} {sandbox}")
    args = parser.parse_args()
    result = run_darwinian(args.source, external_python=args.darwinian_python,
                            mutator_command=args.mutator_command, output_root=args.output_root,
                            num_iterations=args.num_iterations, timeout=args.timeout)
    print(json.dumps({"status": result.status, "reason": result.reason,
                      "sandbox": str(result.sandbox) if result.sandbox else None,
                      "candidate": str(result.candidate) if result.candidate else None,
                      "command": list(result.command),
                      "artifacts": [str(path) for path in result.artifact_paths]},
                     ensure_ascii=False, indent=2))
    return 0 if result.status in {"candidate", "retain_baseline"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

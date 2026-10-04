"""确定性 synthetic mutator；只在 Phase4 worker sandbox 中使用，不是 LLM 或生产修复器。"""
from __future__ import annotations

import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--candidate", type=Path, required=True)
parser.add_argument("--failure-cases", type=Path, required=True)
parser.add_argument("--learning-log", type=Path, required=True)
parser.add_argument("--sandbox", type=Path, required=True)
args = parser.parse_args()
args.candidate.write_text("def reproduce(value):\n    return value\n", encoding="utf-8")

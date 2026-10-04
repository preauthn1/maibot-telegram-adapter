"""显式运行一次自演化 worker；默认不启动、不部署。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.self_evolution.backend import ConfiguredModelBackend
from src.self_evolution.dataset import load_dataset, split_dataset
from src.self_evolution.gepa_adapter import reflective_fitness, run_gepa
from src.self_evolution.monitor import EvolutionMonitor
from src.self_evolution.registry import CandidateRegistry
from src.self_evolution.worker import EvolutionWorker


def _score(policy: str, examples: list[Any], backend: ConfiguredModelBackend, judge: ConfiguredModelBackend) -> list[float]:
    values: list[float] = []
    for example in examples:
        output = backend.complete([{"role": "system", "content": policy}, {"role": "user", "content": example.input}])
        result = reflective_fitness(
            example,
            output,
            lambda prompt: judge.complete([{"role": "system", "content": "只输出 JSON。"}, {"role": "user", "content": prompt}]),
        )
        values.append(float(result.value))
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded MaiBot evolution job; deployment is never automatic")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--monitor-root", type=Path, default=Path("data/self-evolution/monitor"))
    parser.add_argument("--registry-root", type=Path, default=Path("data/self-evolution"))
    parser.add_argument("--config", type=Path, default=Path("config/model_config.toml"))
    parser.add_argument("--steps", type=int, default=1)
    args = parser.parse_args()
    examples = load_dataset(args.dataset)
    splits = split_dataset(examples)
    baseline = args.policy.read_text(encoding="utf-8")
    baseline_digest = hashlib.sha256(baseline.encode("utf-8")).hexdigest()
    holdout_payload = [example.as_dict() for example in splits["holdout"]]
    dataset_digest = hashlib.sha256(json.dumps(holdout_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    backend = ConfiguredModelBackend(args.config, "planner")
    judge = ConfiguredModelBackend(args.config, "replyer")
    registry = CandidateRegistry(args.registry_root)
    registry.register(baseline, metadata={"source": str(args.policy), "kind": "baseline"})

    def optimize(target: str) -> dict[str, Any]:
        if target != "maisaka.planner":
            raise ValueError("unsupported evolution target")
        baseline_scores = _score(baseline, splits["holdout"], backend, judge)
        evolved = run_gepa(baseline, splits["train"], backend, steps=args.steps, val_examples=splits["val"])
        candidate_scores = _score(evolved, splits["holdout"], backend, judge)
        no_regression = len(baseline_scores) == len(candidate_scores) and all(
            candidate >= baseline_score for baseline_score, candidate in zip(baseline_scores, candidate_scores)
        )
        baseline_score = sum(baseline_scores) / max(1, len(baseline_scores))
        candidate_score = sum(candidate_scores) / max(1, len(candidate_scores))
        strict_gain = no_regression and candidate_score > baseline_score
        candidate_id = registry.register(evolved, metadata={"engine": "dspy.gepa", "target": target})
        artifact = registry.candidates / f"{candidate_id}.txt"
        return {
            "artifact": str(artifact), "deployment": "not_applied", "candidate_id": candidate_id,
            "baseline_score": baseline_score, "candidate_score": candidate_score,
            "no_regression": no_regression, "strict_gain": strict_gain,
            "baseline_digest": baseline_digest, "dataset_digest": dataset_digest,
        }

    result = EvolutionWorker(EvolutionMonitor(args.monitor_root), registry).run_once(optimize)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"review_required", "idle", "busy"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""MaiBot 自演化 CLI：验证数据、离线切分、评估与候选审批/部署。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# 允许从仓库根目录或直接以 `python3 scripts/...` 运行。
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.self_evolution.backend import ConfiguredModelBackend
from src.self_evolution.dataset import load_dataset, split_dataset, write_splits
from src.self_evolution.gepa_adapter import reflective_fitness, run_gepa
from src.self_evolution.registry import CandidateRegistry


def evaluate(policy: str, examples, backend: ConfiguredModelBackend, judge: ConfiguredModelBackend) -> list[dict]:
    results = []
    for example in examples:
        output = backend.complete([{"role": "system", "content": policy}, {"role": "user", "content": example.input}])
        score = reflective_fitness(example, output, lambda prompt: judge.complete([{"role": "system", "content": "只输出 JSON。"}, {"role": "user", "content": prompt}]))
        results.append({"input": example.input, "output": output, "score": score.value, "feedback": score.feedback})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="MaiBot self-evolution; no automatic deployment")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=Path("data/self-evolution"))
    parser.add_argument("--config", type=Path, default=Path("config/model_config.toml"))
    parser.add_argument("--split-dir", type=Path)
    parser.add_argument("--gepa", action="store_true")
    parser.add_argument("--steps", type=int, default=1)
    parser.add_argument("--dataset-digest", type=str)
    parser.add_argument("--approve", type=str)
    parser.add_argument("--deploy", type=str)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    examples = load_dataset(args.dataset)
    splits = split_dataset(examples)
    current_dataset_payload = [example.as_dict() for example in splits["holdout"]]
    current_dataset_digest = hashlib.sha256(json.dumps(current_dataset_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    if args.dataset_digest is not None and args.dataset_digest != current_dataset_digest:
        raise ValueError("provided dataset digest does not match the current dataset")
    if args.split_dir:
        write_splits(splits, args.split_dir)
    policy = args.policy.read_text(encoding="utf-8")
    CandidateRegistry.validate_policy(policy)
    registry = CandidateRegistry(args.registry)
    candidate_id = registry.register(policy, metadata={"source": str(args.policy), "synthetic_or_user_supplied": True})
    report = {"candidate_id": candidate_id, "splits": {key: len(value) for key, value in splits.items()}, "dataset_digest": current_dataset_digest, "deployment": "not_applied"}
    if args.gepa:
        backend = ConfiguredModelBackend(args.config, "planner")
        judge = ConfiguredModelBackend(args.config, "replyer")
        baseline_results = evaluate(policy, splits["holdout"], backend, judge)
        baseline_score = sum(item["score"] for item in baseline_results) / max(1, len(baseline_results))
        evolved = run_gepa(policy, splits["train"], backend, steps=args.steps, val_examples=splits["val"])
        evolved_results = evaluate(evolved, splits["holdout"], backend, judge)
        evolved_score = sum(item["score"] for item in evolved_results) / max(1, len(evolved_results))
        no_regression = all(
            new["score"] >= old["score"]
            for old, new in zip(baseline_results, evolved_results)
        ) and len(baseline_results) == len(evolved_results)
        strict_gain = no_regression and evolved_score > baseline_score
        evolved_id = registry.register(evolved, metadata={"engine": "dspy.gepa", "upstream_phase": "phase1"})
        baseline_digest = hashlib.sha256(policy.encode("utf-8")).hexdigest()
        registry.record_evaluation(evolved_id, baseline_score=baseline_score, candidate_score=evolved_score, no_regression=no_regression, strict_gain=strict_gain, baseline_digest=baseline_digest, dataset_digest=current_dataset_digest)
        report.update({"evolved_candidate_id": evolved_id, "changed": evolved != policy, "baseline_holdout_score": baseline_score, "evolved_holdout_score": evolved_score, "holdout_no_regression": no_regression, "holdout_strict_gain": strict_gain, "deployment": "not_applied"})
        if not strict_gain:
            report["selection"] = "retain_baseline"
        else:
            report["selection"] = "review_required"
    if args.approve:
        registry.approve(args.approve)
        report["approved"] = args.approve
    if args.deploy:
        registry.deploy(args.deploy, current_dataset_digest=current_dataset_digest)
        report["deployment"] = "applied"
    if args.rollback:
        registry.rollback()
        report["deployment"] = "rolled_back"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

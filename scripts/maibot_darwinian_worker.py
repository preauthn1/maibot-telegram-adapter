"""独立 Darwinian worker；仅此进程允许 import 官方 Darwinian 包。

这是 Phase4 的外部桥：注册 maibot_synthetic 后 runpy 官方 __main__，不复制官方算法。
变异器是确定性 synthetic canary，不是 LLM 优化器。
"""
from __future__ import annotations

import argparse
import ast
import json
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

from darwinian_evolver.learning_log import LearningLogEntry
from darwinian_evolver.problem import EvaluationFailureCase
from darwinian_evolver.problem import EvaluationResult
from darwinian_evolver.problem import Evaluator
from darwinian_evolver.problem import Mutator
from darwinian_evolver.problem import Organism
from darwinian_evolver.problem import Problem
from darwinian_evolver.problems import registry


ROOT = Path(__file__).resolve().parents[1]


class SyntheticOrganism(Organism):
    source_text: str


class SyntheticFailureCase(EvaluationFailureCase):
    input_value: object
    expected_output: object
    actual_output: object


def _safe_eval(source_text: str, values: list[object]) -> list[dict[str, object]]:
    """候选在无 builtins、CPU/地址空间受限的子进程中运行；不访问 MaiBot。"""
    harness = """import json, resource, sys
resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
resource.setrlimit(resource.RLIMIT_AS, (128*1024*1024, 128*1024*1024))
resource.setrlimit(resource.RLIMIT_FSIZE, (32768, 32768))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
namespace = {\"__builtins__\": {}}
exec(compile(open(sys.argv[1], encoding=\"utf-8\").read(), \"candidate\", \"exec\"), namespace)
outputs=[]
for value in json.load(open(sys.argv[2])):
    try: outputs.append({\"ok\": True, \"value\": namespace[\"reproduce\"](value)})
    except Exception as exc: outputs.append({\"ok\": False, \"error\": type(exc).__name__})
json.dump(outputs, open(sys.argv[3], \"w\"))
"""
    with __import__("tempfile").TemporaryDirectory(prefix="darwinian-canary-") as name:
        root = Path(name)
        source = root / "candidate.py"
        inputs = root / "inputs.json"
        outputs = root / "outputs.json"
        source.write_text(source_text, encoding="utf-8")
        inputs.write_text(json.dumps(values), encoding="utf-8")
        proc = subprocess.run([sys.executable, "-I", "-c", harness, str(source), str(inputs), str(outputs)],
                              cwd=root, capture_output=True, text=True, timeout=2, check=False)
        if proc.returncode or not outputs.is_file():
            return [{"ok": False, "error": "bounded process failed"} for _ in values]
        return json.loads(outputs.read_text(encoding="utf-8"))


class SyntheticEvaluator(Evaluator[SyntheticOrganism, EvaluationResult, SyntheticFailureCase]):
    TRAIN = (0, 1, -1, "mai", "", [1, 2])
    HOLDOUT = (3, 7, "holdout", [3, 5])

    def evaluate(self, organism: SyntheticOrganism) -> EvaluationResult:
        values = list(self.TRAIN + self.HOLDOUT)
        outputs = _safe_eval(organism.source_text, values)
        train: list[SyntheticFailureCase] = []
        holdout: list[SyntheticFailureCase] = []
        for index, (value, output) in enumerate(zip(values, outputs)):
            actual = output.get("value") if output.get("ok") else output.get("error")
            if not output.get("ok") or type(actual) is not type(value) or actual != value:
                failure = SyntheticFailureCase(data_point_id=f"case_{index}", input_value=value,
                    expected_output=value, actual_output=actual)
                (train if index < len(self.TRAIN) else holdout).append(failure)
        total = len(values)
        score = (total - len(train) - len(holdout)) / total
        return EvaluationResult(score=score, trainable_failure_cases=train,
                                holdout_failure_cases=holdout, is_viable=True)


class DeterministicCanaryMutator(Mutator[SyntheticOrganism, SyntheticFailureCase]):
    """确定性修复器：只替换 synthetic reproduction 文件，不调用模型或任意命令。"""
    def mutate(self, organism: SyntheticOrganism, failure_cases: list[SyntheticFailureCase],
               learning_log_entries: list[LearningLogEntry]) -> list[SyntheticOrganism]:
        candidate_text = "def reproduce(value):\n    return value\n"
        candidate = Path.cwd() / "candidates" / "deterministic-canary.py"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(candidate_text, encoding="utf-8")
        return [SyntheticOrganism(source_text=candidate_text, parent=organism,
                                  from_failure_cases=failure_cases,
                                  from_learning_log_entries=learning_log_entries,
                                  from_change_summary="deterministic synthetic canary: return value")]


def make_problem() -> Problem:
    baseline = "def reproduce(value):\n    return None if value in (1, 7) else value\n"
    return Problem(initial_organism=SyntheticOrganism(source_text=baseline),
                   evaluator=SyntheticEvaluator(), mutators=[DeterministicCanaryMutator()])


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("problem")
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.problem != "maibot_synthetic":
        raise SystemExit(f"unsupported worker problem: {args.problem}")
    registry.AVAILABLE_PROBLEMS[args.problem] = make_problem
    sys.argv = ["darwinian_evolver", args.problem, *args.rest]
    runpy.run_module("darwinian_evolver.__main__", run_name="__main__")


if __name__ == "__main__":
    main()

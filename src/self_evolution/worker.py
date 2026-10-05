"""Single-worker detection → optimization → review queue (never deployment)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import hashlib
import json
import time

from .monitor import EvolutionMonitor
from .registry import CandidateRegistry

_REQUIRED_RESULT_FIELDS = {
    "artifact",
    "deployment",
    "baseline_score",
    "candidate_score",
    "no_regression",
    "strict_gain",
    "candidate_id",
    "baseline_digest",
    "dataset_digest",
}


class EvolutionWorker:
    def __init__(self, monitor: EvolutionMonitor, registry: CandidateRegistry | None = None):
        self.monitor = monitor
        self.registry = registry or CandidateRegistry(monitor.root.parent)

    @staticmethod
    def _validate_result(result: Any, registry_root: Path) -> tuple[Path, str]:
        if not isinstance(result, dict) or not _REQUIRED_RESULT_FIELDS.issubset(result):
            raise ValueError("optimizer result is missing the unified evaluation contract")
        artifact = Path(result["artifact"]).resolve()
        candidate_id = result["candidate_id"]
        if not isinstance(candidate_id, str) or not candidate_id or not CandidateRegistry._valid_id(candidate_id):
            raise ValueError("optimizer candidate_id is invalid")
        if not artifact.is_file() or result["deployment"] != "not_applied":
            raise ValueError("optimizer artifact is missing or already deployed")
        expected_artifact = (registry_root / "candidates" / f"{candidate_id}.txt").resolve()
        if artifact != expected_artifact:
            raise ValueError("optimizer artifact does not match candidate_id")
        if not hashlib.sha256(artifact.read_bytes()).hexdigest().startswith(candidate_id):
            raise ValueError("optimizer artifact digest does not match candidate_id")
        scores = (result["baseline_score"], result["candidate_score"])
        if not all(type(value) in (int, float) and 0 <= value <= 1 for value in scores):
            raise ValueError("optimizer scores are invalid")
        if not all(type(result[name]) is bool for name in ("no_regression", "strict_gain")):
            raise ValueError("optimizer gate fields are invalid")
        return artifact, candidate_id

    def run_once(self, optimizer: Callable[[str], dict[str, Any]], *, now: float | None = None) -> dict[str, Any]:
        """Run at most one queued job; successful work always remains review-only."""
        clock = time.time() if now is None else now
        self.monitor.enqueue_jobs(self.monitor.triage())
        # 选择与领取在监测锁内一次完成，running 任务不会被其他 worker 抢走。
        job = self.monitor.claim_next_job(now=clock)
        if job is None:
            return {"status": "idle"}
        key = job["job_id"]
        claim_id = job["claim_id"]
        try:
            result = optimizer(job["target"])
            artifact, candidate_id = self._validate_result(result, self.registry.root)
            self.registry.record_evaluation(
                candidate_id,
                baseline_score=float(result["baseline_score"]),
                candidate_score=float(result["candidate_score"]),
                no_regression=result["no_regression"],
                strict_gain=result["strict_gain"],
                baseline_digest=result["baseline_digest"],
                dataset_digest=result["dataset_digest"],
            )
        except Exception:
            # Errors may carry auth/request details; never persist their text.
            failed_at = time.time() if now is None else now
            self.monitor.fail_job(key, claim_id, now=failed_at, error="optimization failed")
            return {"status": "failed", "job_id": key}
        # 收尾写入不在 except 覆盖范围内：领取权过期等错误必须直接暴露，不能改记为失败。
        completed_at = time.time() if now is None else now
        self.monitor.complete_job(key, claim_id, {**result, "artifact": str(artifact)}, completed_at=completed_at)
        return {"status": "review_required", "job_id": key, "artifact": str(artifact)}

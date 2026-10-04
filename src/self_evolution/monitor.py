"""Phase 5: durable metrics, triage, resumable jobs, and candidate work items.

The monitor never deploys a candidate. It only records evidence and creates a
reviewable job; approval/deployment remains an explicit registry operation.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MetricEvent:
    target: str
    outcome: str
    score: float | None
    usage_count: int = 1
    metadata: dict[str, str] | None = None
    event_id: str | None = None


@dataclass(frozen=True)
class TriageItem:
    target: str
    priority: float
    reason: str


def _event_key(event: MetricEvent) -> str:
    if event.event_id:
        return hashlib.sha256(event.event_id.encode("utf-8")).hexdigest()
    payload = json.dumps({"target": event.target, "outcome": event.outcome, "score": event.score, "metadata": event.metadata}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _monitor_locked(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.lock.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            return method(self, *args, **kwargs)
    return wrapped


class EvolutionMonitor:
    """Fail-closed monitor with durable state and deduplicated work items."""

    def __init__(self, root: Path):
        self.root = root
        self.events = root / "events.jsonl"
        self.state = root / "monitor-state.json"
        self.jobs = root / "jobs.json"
        self.lock = root / "monitor.lock"
        self.root.mkdir(parents=True, exist_ok=True)

    def _event_keys_from_log(self) -> set[str]:
        if not self.events.exists():
            return set()
        keys: set[str] = set()
        for line in self.events.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            key = item.get("key")
            if not isinstance(key, str) or not key:
                raise ValueError("invalid persisted evolution event key")
            keys.add(key)
        return keys

    def record(self, event: MetricEvent) -> bool:
        if not event.target.strip() or event.usage_count < 0:
            raise ValueError("invalid metric event")
        if event.score is not None and (not isinstance(event.score, (int, float)) or not math.isfinite(event.score) or not 0 <= event.score <= 1):
            raise ValueError("invalid scored metric event")
        if event.metadata is not None:
            if not isinstance(event.metadata, dict) or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in event.metadata.items()
            ):
                raise ValueError("metric metadata must be a string dictionary")
        with self.lock.open("a", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle, fcntl.LOCK_EX)
            return self._record_locked(event)

    def _record_locked(self, event: MetricEvent) -> bool:
        state = self._read_json(self.state, {})
        key = _event_key(event)
        keys = set(state.setdefault("event_keys", [])) | self._event_keys_from_log()
        if key in keys:
            return False
        record = {"key": key, **asdict(event), "recorded_at": datetime.now(timezone.utc).isoformat()}
        with self.events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        keys.add(key)
        state["event_keys"] = sorted(keys)[-5000:]
        self._atomic_json(self.state, state)
        return True

    @_monitor_locked
    def triage(self, *, min_usage: int = 1, failure_threshold: float = 0.5) -> list[TriageItem]:
        aggregates: dict[str, list[MetricEvent]] = {}
        if self.events.exists():
            for line in self.events.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                    raw_score = item.get("score")
                    if raw_score is not None and (
                        not isinstance(raw_score, (int, float))
                        or not math.isfinite(raw_score)
                        or not 0 <= raw_score <= 1
                    ):
                        raise ValueError("invalid persisted score")
                    raw_metadata = item.get("metadata")
                    if raw_metadata is not None and (
                        not isinstance(raw_metadata, dict)
                        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in raw_metadata.items())
                    ):
                        raise ValueError("invalid persisted metric metadata")
                    event = MetricEvent(
                        str(item["target"]), str(item["outcome"]),
                        None if raw_score is None else float(raw_score),
                        int(item.get("usage_count", 1)), item.get("metadata"), item.get("event_id"),
                    )
                    if event.score is None:
                        continue
                    aggregates.setdefault(event.target, []).append(event)
                except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                    raise ValueError("invalid persisted evolution metric event") from exc
        result: list[TriageItem] = []
        for target, events in aggregates.items():
            usage = sum(max(0, e.usage_count) for e in events)
            average = sum(e.score * max(0, e.usage_count) for e in events) / max(1, usage)
            if usage >= min_usage and average < failure_threshold:
                result.append(TriageItem(target, (1 - average) * usage, f"weighted score {average:.3f} below threshold"))
        return sorted(result, key=lambda item: item.priority, reverse=True)

    @_monitor_locked
    def enqueue_jobs(self, items: list[TriageItem]) -> list[str]:
        jobs = self._read_json(self.jobs, {})
        created: list[str] = []
        for item in items:
            job_id = hashlib.sha256(f"{item.target}\0{item.reason}".encode()).hexdigest()[:16]
            current = jobs.get(job_id)
            if current:
                status = current.get("status")
                # Do not reset retry state or duplicate active/completed work.
                if status in {"queued", "running", "paused", "succeeded"}:
                    continue
                if status == "failed":
                    # Retry is owned by the worker's retry_after clock.
                    continue
                raise ValueError("invalid persisted evolution job status")
            jobs[job_id] = {
                "job_id": job_id,
                "target": item.target,
                "priority": item.priority,
                "reason": item.reason,
                "status": "queued",
                "attempts": 0,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            created.append(job_id)
        self._atomic_json(self.jobs, jobs)
        return created

    @_monitor_locked
    def get_jobs(self) -> dict[str, Any]:
        return self._read_json(self.jobs, {})

    @_monitor_locked
    def claim_next_job(self, *, now: float) -> dict[str, Any] | None:
        """在同一把监测锁内完成选择与领取，返回带 claim_id 的任务快照。

        只有 queued 或已到 retry_after 的 failed 任务可被领取；running 任务不可被
        其他 worker 再次领取，claim_id 用于在收尾时拒绝过期写回。
        """
        jobs = self._read_json(self.jobs, {})
        eligible: list[tuple[str, dict[str, Any]]] = []
        for job_id, job in jobs.items():
            status = job.get("status")
            if status not in {"queued", "running", "paused", "succeeded", "failed"}:
                raise ValueError("invalid persisted evolution job status")
            if status in {"queued", "failed"} and float(job.get("retry_after", 0)) <= now:
                eligible.append((job_id, job))
        if not eligible:
            return None
        job_id, job = max(eligible, key=lambda pair: float(pair[1]["priority"]))
        if job.get("job_id") != job_id:
            raise ValueError("persisted evolution job id does not match its key")
        job["status"] = "running"
        job["claim_id"] = uuid.uuid4().hex
        job["claimed_at"] = now
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._atomic_json(self.jobs, jobs)
        return json.loads(json.dumps(job))

    def _claimed_job_locked(self, jobs: dict[str, Any], job_id: str, claim_id: str) -> dict[str, Any]:
        """校验调用方仍持有该任务的领取权；调用方必须已持有监测锁。"""
        if job_id not in jobs:
            raise KeyError(job_id)
        job = jobs[job_id]
        if job.get("status") != "running" or job.get("claim_id") != claim_id:
            raise PermissionError("evolution job claim is stale or not owned by this worker")
        return job

    @_monitor_locked
    def complete_job(self, job_id: str, claim_id: str, result: dict[str, Any], *, completed_at: float) -> None:
        """单次加锁事务写入成功结果；保留 attempts/retry_after 等既有字段。"""
        jobs = self._read_json(self.jobs, {})
        job = self._claimed_job_locked(jobs, job_id, claim_id)
        job.update(
            status="succeeded",
            review_required=True,
            result=result,
            completed_at=completed_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        self._atomic_json(self.jobs, jobs)

    @_monitor_locked
    def fail_job(self, job_id: str, claim_id: str, *, now: float, error: str) -> None:
        """单次加锁事务记录失败：递增 attempts 并按退避写入 retry_after。"""
        jobs = self._read_json(self.jobs, {})
        job = self._claimed_job_locked(jobs, job_id, claim_id)
        attempts = int(job.get("attempts", 0)) + 1
        job.update(
            status="failed",
            attempts=attempts,
            retry_after=now + min(3600, 30 * 2 ** min(attempts, 7)),
            last_error=error[:1000],
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        self._atomic_json(self.jobs, jobs)

    @_monitor_locked
    def set_job_result(self, job_id: str, result: dict[str, Any], *, completed_at: float) -> None:
        jobs = self._read_json(self.jobs, {})
        if job_id not in jobs:
            raise KeyError(job_id)
        jobs[job_id].update(status="succeeded", review_required=True, result=result, completed_at=completed_at)
        self._atomic_json(self.jobs, jobs)

    @_monitor_locked
    def set_job_retry(self, job_id: str, *, retry_after: float) -> None:
        jobs = self._read_json(self.jobs, {})
        if job_id not in jobs:
            raise KeyError(job_id)
        jobs[job_id]["retry_after"] = retry_after
        self._atomic_json(self.jobs, jobs)

    @_monitor_locked
    def set_job_status(self, job_id: str, status: str, *, error: str = "") -> None:
        if status not in {"queued", "running", "paused", "succeeded", "failed"}:
            raise ValueError("invalid job status")
        jobs = self._read_json(self.jobs, {})
        if job_id not in jobs:
            raise KeyError(job_id)
        jobs[job_id]["status"] = status
        jobs[job_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        if error:
            jobs[job_id]["last_error"] = error[:1000]
        if status == "failed":
            jobs[job_id]["attempts"] = int(jobs[job_id].get("attempts", 0)) + 1
        self._atomic_json(self.jobs, jobs)

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        # 仅不存在的文件可以初始化为空。损坏或读取失败必须暴露，
        # 否则后续原子写入会把已有任务/去重状态覆盖成空状态。
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, type(default)):
            raise ValueError("invalid persisted monitor state type")
        return value

    @staticmethod
    def _atomic_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

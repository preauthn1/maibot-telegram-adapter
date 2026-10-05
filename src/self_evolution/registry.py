"""策略候选的 fail-closed 注册、批准、原子部署与回滚。"""

from __future__ import annotations

from functools import wraps
import fcntl
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_POLICY_BYTES = 15_000
MAX_METADATA_BYTES = 8_000
SENSITIVE_METADATA_KEYS = {"api_key", "apikey", "secret", "token", "access_token", "authorization", "password"}


def _validate_metadata(value: Any, *, depth: int = 0) -> None:
    if depth > 4:
        raise ValueError("candidate metadata nesting is too deep")
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_METADATA_BYTES:
            raise ValueError("candidate metadata value is oversized")
        return
    if value is None or isinstance(value, bool) or type(value) in (int, float):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("candidate metadata contains a non-finite number")
        return
    if isinstance(value, list):
        if len(value) > 100:
            raise ValueError("candidate metadata list is oversized")
        for item in value:
            _validate_metadata(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 100:
            raise ValueError("candidate metadata object is oversized")
        for key, item in value.items():
            if not isinstance(key, str) or key.lower() in SENSITIVE_METADATA_KEYS:
                raise ValueError("candidate metadata contains a sensitive key")
            _validate_metadata(item, depth=depth + 1)
        return
    raise ValueError("candidate metadata contains an unsupported value")


def _registry_locked(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.lock.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            return method(self, *args, **kwargs)
    return wrapped


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CandidateRegistry:
    """文件注册表；缺失/损坏/未批准候选永远不参与运行时。"""

    def __init__(self, root: Path):
        self.root = root
        self.candidates = root / "candidates"
        self.active = root / "active_policy.txt"
        self.backups = root / "backups"
        self.manifest = root / "registry.json"
        self.lock = root / "registry.lock"
        for path in (self.candidates, self.backups):
            path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def validate_policy(policy: str) -> None:
        if not isinstance(policy, str) or not policy.strip() or len(policy.encode("utf-8")) > MAX_POLICY_BYTES:
            raise ValueError("invalid policy: empty or oversized")
        if "api_key" in policy.lower() or "bearer " in policy.lower() or "sk-" in policy.lower():
            raise ValueError("policy appears to contain a secret")

    @_registry_locked
    def register(self, policy: str, *, metadata: dict[str, Any] | None = None) -> str:
        self.validate_policy(policy)
        if metadata is not None:
            _validate_metadata(metadata)
            if len(json.dumps(metadata, ensure_ascii=False).encode("utf-8")) > MAX_METADATA_BYTES:
                raise ValueError("candidate metadata is oversized")
        candidate_id = _digest(policy)[:16]
        records = self._read_manifest()
        existing = records.get(candidate_id)
        if existing and existing.get("digest") == _digest(policy) and (self.candidates / f"{candidate_id}.txt").is_file():
            return candidate_id
        self._atomic_text(self.candidates / f"{candidate_id}.txt", policy)
        records[candidate_id] = {"candidate_id": candidate_id, "digest": _digest(policy), "approved": False, "evaluated": False, "metadata": metadata or {}, "created_at": datetime.now(timezone.utc).isoformat()}
        self._atomic_json(records)
        return candidate_id

    @staticmethod
    def _valid_id(candidate_id: str) -> bool:
        return isinstance(candidate_id, str) and len(candidate_id) == 16 and all(ch in "0123456789abcdef" for ch in candidate_id)

    @staticmethod
    def _valid_digest(value: Any) -> bool:
        return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)

    @classmethod
    def _evaluation_is_deployable(cls, evaluation: Any) -> bool:
        return (
            isinstance(evaluation, dict)
            and evaluation.get("no_regression") is True
            and evaluation.get("strict_gain") is True
            and cls._valid_digest(evaluation.get("baseline_digest"))
            and cls._valid_digest(evaluation.get("dataset_digest"))
        )

    @_registry_locked
    def record_evaluation(
        self,
        candidate_id: str,
        *,
        baseline_score: float,
        candidate_score: float,
        no_regression: bool,
        strict_gain: bool,
        baseline_digest: str | None = None,
        dataset_digest: str | None = None,
    ) -> None:
        records = self._read_manifest()
        if not self._valid_id(candidate_id) or candidate_id not in records:
            raise KeyError(candidate_id)
        if not all(type(x) in (int, float) and 0 <= x <= 1 for x in (baseline_score, candidate_score)):
            raise ValueError("invalid evaluation score")
        if baseline_digest is not None and (not isinstance(baseline_digest, str) or len(baseline_digest) != 64 or any(ch not in "0123456789abcdef" for ch in baseline_digest)):
            raise ValueError("invalid baseline digest")
        if dataset_digest is not None and (not isinstance(dataset_digest, str) or len(dataset_digest) != 64 or any(ch not in "0123456789abcdef" for ch in dataset_digest)):
            raise ValueError("invalid dataset digest")
        if type(no_regression) is not bool or type(strict_gain) is not bool:
            raise ValueError("evaluation gates must be booleans")
        # 逐样本非回归比平均分非回归更严格：均分上升仍可能有个例退化。
        if no_regression and candidate_score < baseline_score:
            raise ValueError("non-regression gate contradicts the measured scores")
        if strict_gain != (no_regression and candidate_score > baseline_score):
            raise ValueError("strict gain gate contradicts the measured scores")
        records[candidate_id]["evaluation"] = {"baseline_score": float(baseline_score), "candidate_score": float(candidate_score), "no_regression": bool(no_regression), "strict_gain": bool(strict_gain), "recorded_at": datetime.now(timezone.utc).isoformat()}
        records[candidate_id]["evaluated"] = True
        records[candidate_id]["evaluation"]["baseline_digest"] = baseline_digest
        records[candidate_id]["evaluation"]["dataset_digest"] = dataset_digest
        records[candidate_id]["approved"] = False
        records[candidate_id].pop("approved_at", None)
        self._atomic_json(records)

    @_registry_locked
    def approve(self, candidate_id: str) -> None:
        records = self._read_manifest()
        if not self._valid_id(candidate_id) or candidate_id not in records or not (self.candidates / f"{candidate_id}.txt").is_file():
            raise KeyError(candidate_id)
        evaluation = records[candidate_id].get("evaluation")
        if not self._evaluation_is_deployable(evaluation):
            raise PermissionError("candidate lacks a strict holdout gain, non-regression gate, and evaluation digests")
        records[candidate_id]["approved"] = True
        records[candidate_id]["approved_at"] = datetime.now(timezone.utc).isoformat()
        self._atomic_json(records)

    @_registry_locked
    def deploy(self, candidate_id: str, *, current_dataset_digest: str | None = None) -> None:
        records = self._read_manifest()
        if not self._valid_id(candidate_id):
            raise KeyError(candidate_id)
        record = records.get(candidate_id)
        evaluation = record.get("evaluation") if isinstance(record, dict) else None
        if not isinstance(record, dict) or record.get("approved") is not True or not self._evaluation_is_deployable(evaluation):
            raise PermissionError("candidate lacks current approval and evaluation gates")
        source = self.candidates / f"{candidate_id}.txt"
        if not source.is_file():
            raise PermissionError("candidate artifact is missing")
        policy = source.read_text(encoding="utf-8")
        self.validate_policy(policy)
        if record.get("digest") != _digest(policy):
            raise ValueError("candidate digest mismatch")
        if current_dataset_digest is not None:
            if not isinstance(evaluation, dict) or not self._valid_digest(current_dataset_digest) or evaluation.get("dataset_digest") != current_dataset_digest:
                raise PermissionError("candidate was evaluated against a different dataset")
        if self.active.exists():
            current_digest = _digest(self.active.read_text(encoding="utf-8"))
            if not isinstance(evaluation, dict) or evaluation.get("baseline_digest") != current_digest:
                raise PermissionError("candidate was evaluated against a different active baseline")
        previous_policy = self.active.read_text(encoding="utf-8") if self.active.exists() else None
        previous_records = json.loads(json.dumps(records))
        if previous_policy is not None:
            backup = self.backups / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.txt"
            self._atomic_text(backup, previous_policy)
        for other in records.values():
            other["active"] = False
        record["active"] = True
        record["deployed_at"] = datetime.now(timezone.utc).isoformat()
        try:
            self._atomic_text(self.active, policy)
            self._atomic_json(records)
        except Exception:
            if previous_policy is None:
                self.active.unlink(missing_ok=True)
            else:
                self._atomic_text(self.active, previous_policy)
            self._atomic_json(previous_records)
            raise

    @_registry_locked
    def rollback(self) -> None:
        current_digest = None
        if self.active.exists():
            current_digest = _digest(self.active.read_text(encoding="utf-8"))
        backups = sorted(self.backups.glob("*.txt"), reverse=True)
        policy = None
        for backup in backups:
            candidate = backup.read_text(encoding="utf-8")
            if _digest(candidate) != current_digest:
                policy = candidate
                break
        if policy is None:
            raise FileNotFoundError("no prior distinct policy backup")
        self.validate_policy(policy)
        records = self._read_manifest()
        digest = _digest(policy)
        for other in records.values():
            other["active"] = other.get("digest") == digest
        active_record = next((item for item in records.values() if item.get("digest") == digest), None)
        if active_record is None or active_record.get("approved") is not True:
            raise PermissionError("backup does not correspond to an approved candidate")
        evaluation = active_record.get("evaluation")
        if not isinstance(evaluation, dict) or evaluation.get("no_regression") is not True or evaluation.get("strict_gain") is not True:
            raise PermissionError("backup lacks current evaluation gates")
        previous_policy = self.active.read_text(encoding="utf-8") if self.active.exists() else None
        previous_records = json.loads(json.dumps(records))
        try:
            self._atomic_text(self.active, policy)
            self._atomic_json(records)
        except Exception:
            if previous_policy is None:
                self.active.unlink(missing_ok=True)
            else:
                self._atomic_text(self.active, previous_policy)
            self._atomic_json(previous_records)
            raise

    @_registry_locked
    def read_active(self) -> str | None:
        if not self.active.is_file():
            return None
        policy = self.active.read_text(encoding="utf-8")
        self.validate_policy(policy)
        candidate_id = _digest(policy)[:16]
        records = self._read_manifest()
        record = records.get(candidate_id)
        evaluation = record.get("evaluation") if isinstance(record, dict) else None
        if (
            not isinstance(record, dict)
            or record.get("digest") != _digest(policy)
            or record.get("active") is not True
            or record.get("approved") is not True
            or not isinstance(evaluation, dict)
            or evaluation.get("no_regression") is not True
            or evaluation.get("strict_gain") is not True
            or not evaluation.get("baseline_digest")
            or not evaluation.get("dataset_digest")
        ):
            raise ValueError("active policy is not backed by an approved evaluated candidate")
        return policy

    def _read_manifest(self) -> dict[str, Any]:
        if not self.manifest.exists():
            return {}
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("invalid persisted candidate manifest type")
        return data

    def _atomic_json(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
        self._atomic_text(self.manifest, payload)

    @staticmethod
    def _atomic_text(target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

"""数据集校验与确定性 train/val/holdout 切分。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

REQUIRED = ("input", "expected_behavior")


@dataclass(frozen=True)
class Example:
    input: str
    expected_behavior: str
    reference: str = ""
    metadata: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"input": self.input, "expected_behavior": self.expected_behavior, "reference": self.reference, "metadata": self.metadata or {}}


def load_dataset(path: Path) -> list[Example]:
    """读取 JSON 数组或 JSONL；拒绝不完整、重复和疑似真实标识字段。"""
    raw = path.read_text(encoding="utf-8")
    payload: Any
    if path.suffix.lower() == ".jsonl":
        payload = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            payload = payload.get("examples", payload.get("all_examples", []))
    if not isinstance(payload, list) or not payload:
        raise ValueError("dataset must be a non-empty JSON array/JSONL")
    result: list[Example] = []
    seen: set[str] = set()
    for index, item in enumerate(payload):
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key].strip() for key in REQUIRED):
            raise ValueError(f"invalid example at index {index}")
        if any(key in item for key in ("telegram_id", "user_id", "phone", "access_token", "api_key")):
            raise ValueError(f"possible identifier/secret field at index {index}")
        example = Example(item["input"].strip(), item["expected_behavior"].strip(), str(item.get("reference", "")), item.get("metadata") if isinstance(item.get("metadata", {}), dict) else {})
        # 输入相同即视为重复，标签、参考答案或 metadata 不能绕过跨集泄漏检查。
        fingerprint = hashlib.sha256(example.input.encode("utf-8")).hexdigest()
        if fingerprint in seen:
            raise ValueError(f"duplicate example at index {index}")
        seen.add(fingerprint)
        result.append(example)
    return result


def split_dataset(examples: Iterable[Example], *, seed: int = 0, train_ratio: float = .6, val_ratio: float = .2) -> dict[str, list[Example]]:
    items = list(examples)
    if not 0 < train_ratio < 1 or not 0 < val_ratio < 1 or train_ratio + val_ratio >= 1:
        raise ValueError("train_ratio + val_ratio must be below 1")
    items.sort(key=lambda item: hashlib.sha256(f"{seed}\0{item.input}".encode()).hexdigest())
    n = len(items)
    if n < 3:
        raise ValueError("at least 3 examples are required for train/val/holdout")
    if len({item.input.strip() for item in items}) != n:
        raise ValueError("duplicate inputs would leak across train/val/holdout")
    # 每一分区至少一条，不能让极端比例挤掉验证集或留出集。
    train_end = min(n - 2, max(1, int(n * train_ratio)))
    val_end = min(n - 1, train_end + max(1, int(n * val_ratio)))
    return {"train": items[:train_end], "val": items[train_end:val_end], "holdout": items[val_end:]}


def write_splits(splits: dict[str, list[Example]], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, examples in splits.items():
        (directory / f"{name}.jsonl").write_text("\n".join(json.dumps(item.as_dict(), ensure_ascii=False) for item in examples) + "\n", encoding="utf-8")

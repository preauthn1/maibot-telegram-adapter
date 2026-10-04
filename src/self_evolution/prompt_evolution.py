"""Phase 3: safe system-prompt section candidates with frozen boundaries."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Iterable

@dataclass(frozen=True)
class PromptSection:
    name: str
    text: str
    max_growth: float = .20
    required_terms: tuple[str, ...] = ()

@dataclass(frozen=True)
class PromptCandidate:
    sections: dict[str, str]
    baseline_digest: str
    metadata: dict[str, str]

def digest_sections(sections: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(sections, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

def validate_prompt_candidate(baseline: Iterable[PromptSection], candidate: dict[str, str]) -> list[str]:
    if not isinstance(candidate, dict):
        raise ValueError("prompt candidate must be an object")
    if any(not isinstance(name, str) or not isinstance(value, str) for name, value in candidate.items()):
        raise ValueError("prompt candidate keys and values must be strings")
    baseline_sections = list(baseline)
    errors: list[str] = []
    names = {section.name for section in baseline_sections}
    if len(names) != len(baseline_sections):
        raise ValueError("duplicate baseline prompt section")
    for section in baseline_sections:
        if not isinstance(section.name, str) or not section.name.strip() or not isinstance(section.text, str) or not section.text.strip():
            raise ValueError("invalid baseline prompt section")
        if not isinstance(section.max_growth, (int, float)) or not math.isfinite(section.max_growth) or section.max_growth < 0:
            raise ValueError("invalid prompt growth limit")
        if any(not isinstance(term, str) or not term for term in section.required_terms):
            raise ValueError("invalid prompt semantic anchor")
        value = candidate.get(section.name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"missing section: {section.name}")
            continue
        if len(value) > max(len(section.text) + 1, int(len(section.text) * (1 + section.max_growth))):
            errors.append(f"growth exceeded: {section.name}")
        for term in section.required_terms:
            if term not in value:
                errors.append(f"semantic anchor missing: {section.name}:{term}")
    for name in candidate:
        if name not in names:
            errors.append(f"unknown section: {name}")
    return errors

def build_candidate(baseline: Iterable[PromptSection], candidate: dict[str, str], metadata: dict[str, str] | None = None) -> PromptCandidate:
    base = list(baseline)
    errors = validate_prompt_candidate(base, candidate)
    if errors:
        raise ValueError("; ".join(errors))
    if not isinstance(metadata, (dict, type(None))):
        raise ValueError("prompt candidate metadata must be an object")
    if metadata is not None and any(not isinstance(key, str) or not isinstance(value, str) for key, value in metadata.items()):
        raise ValueError("prompt candidate metadata must contain only string keys and values")
    return PromptCandidate(dict(candidate), digest_sections({x.name: x.text for x in base}), dict(metadata or {}))


def serialize_prompt_candidate(candidate: PromptCandidate) -> str:
    """把提示词分区候选序列化为确定性文本，进入统一 CandidateRegistry 审批链。"""
    payload = {
        "kind": "prompt_sections",
        "baseline_digest": candidate.baseline_digest,
        "sections": {name: candidate.sections[name] for name in sorted(candidate.sections)},
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)

"""Phase 2：工具描述的真实候选优化与全局回归门。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Callable

MAX_DESCRIPTION_CHARS = 500
MAX_PARAMETER_DESCRIPTION_CHARS = 200

@dataclass(frozen=True)
class ToolDescription:
    name: str
    description: str
    parameters: dict[str, str]
    source: str = ""

@dataclass(frozen=True)
class ToolSelectionExample:
    task: str
    correct_tool: str
    expected_parameters: dict[str, Any] | None = None

@dataclass(frozen=True)
class ToolSelectionScore:
    accuracy: float
    parameter_accuracy: float
    per_tool: dict[str, float]
    regressions: tuple[str, ...] = ()


def extract_tool_descriptions(schema: list[dict[str, Any]]) -> dict[str, ToolDescription]:
    result: dict[str, ToolDescription] = {}
    for item in schema:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        params = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        props = params.get("properties") if isinstance(params.get("properties"), dict) else {}
        result[name] = ToolDescription(name, str(item.get("description", "")), {str(k): str(v.get("description", "")) for k, v in props.items() if isinstance(v, dict)})
    return result


def validate_descriptions(descriptions: dict[str, ToolDescription]) -> list[str]:
    errors: list[str] = []
    for name, item in descriptions.items():
        if len(item.description) > MAX_DESCRIPTION_CHARS:
            errors.append(f"{name}: description exceeds {MAX_DESCRIPTION_CHARS}")
        for param, text in item.parameters.items():
            if len(text) > MAX_PARAMETER_DESCRIPTION_CHARS:
                errors.append(f"{name}.{param}: parameter description exceeds {MAX_PARAMETER_DESCRIPTION_CHARS}")
    return errors


def deterministic_tool_fingerprint(descriptions: dict[str, ToolDescription]) -> str:
    payload = {k: {"description": v.description, "parameters": v.parameters} for k, v in sorted(descriptions.items())}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def serialize_tool_candidate(descriptions: dict[str, ToolDescription]) -> str:
    """把工具描述候选序列化为确定性文本，以便进入统一 CandidateRegistry 审批链。"""
    errors = validate_descriptions(descriptions)
    if errors:
        raise ValueError("; ".join(errors))
    payload = {
        "kind": "tool_descriptions",
        "tools": {k: {"description": v.description, "parameters": v.parameters} for k, v in sorted(descriptions.items())},
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def tool_dataset_digest(examples: list[ToolSelectionExample]) -> str:
    """holdout 工具样本的 digest，用于部署时检测评估集漂移。"""
    payload = [
        {"task": item.task, "correct_tool": item.correct_tool, "expected_parameters": item.expected_parameters}
        for item in examples
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _params_match(expected: dict[str, Any] | None, actual: dict[str, Any] | None) -> bool:
    if expected is None:
        return True
    return isinstance(actual, dict) and all(key in actual and actual[key] == value for key, value in expected.items())


def score_tool_selection(predictions: list[tuple[str, str, dict[str, Any] | None]], baseline: ToolSelectionScore | None = None, examples: list[ToolSelectionExample] | None = None) -> ToolSelectionScore:
    if not predictions:
        return ToolSelectionScore(0.0, 0.0, {})
    good = [left == right for left, right, _ in predictions]
    parameter_hits = [_params_match(examples[i].expected_parameters if examples and i < len(examples) else None, item[2]) for i, item in enumerate(predictions) if item[0] == item[1]]
    per_tool: dict[str, list[bool]] = {}
    for chosen, correct, _ in predictions:
        per_tool.setdefault(correct, []).append(chosen == correct)
    rates = {tool: sum(values) / len(values) for tool, values in per_tool.items()}
    regressions = []
    accuracy = sum(good) / len(good)
    parameter_accuracy = sum(parameter_hits) / max(1, len(parameter_hits))
    if baseline:
        if accuracy < baseline.accuracy:
            regressions.append("cross-tool selection accuracy regressed")
        # 参数准确率同样是工具调用质量的一部分，不能只看工具名是否选对。
        if parameter_accuracy < baseline.parameter_accuracy:
            regressions.append("tool parameter accuracy regressed")
        for tool, old in baseline.per_tool.items():
            if tool not in rates:
                regressions.append(f"tool missing from evaluation set: {tool}")
            elif rates[tool] < old:
                regressions.append(f"tool selection regressed: {tool}")
    return ToolSelectionScore(accuracy, parameter_accuracy, rates, tuple(regressions))


def tool_holdout_gate(baseline: ToolSelectionScore, candidate: ToolSelectionScore) -> dict[str, bool]:
    """工具描述候选的 holdout 门：无任何回归，且总准确率或参数准确率严格提升。

    门本身重新比较各项指标，不依赖调用方是否在评估时传入 baseline。
    """
    no_regression = (
        not candidate.regressions
        and candidate.accuracy >= baseline.accuracy
        and candidate.parameter_accuracy >= baseline.parameter_accuracy
        and all(tool in candidate.per_tool and candidate.per_tool[tool] >= old for tool, old in baseline.per_tool.items())
    )
    strict_gain = no_regression and (
        candidate.accuracy > baseline.accuracy or candidate.parameter_accuracy > baseline.parameter_accuracy
    )
    return {"no_regression": no_regression, "strict_gain": strict_gain}


def split_tool_examples(examples: list[ToolSelectionExample], *, seed: int = 0) -> dict[str, list[ToolSelectionExample]]:
    """确定性切分工具选择样本，禁止候选只在训练集上通过。"""
    if len(examples) < 3:
        raise ValueError("at least 3 tool examples are required")
    seen: set[str] = set()
    for item in examples:
        key = hashlib.sha256(item.task.strip().encode("utf-8")).hexdigest()
        if key in seen:
            raise ValueError("duplicate tool-selection task")
        seen.add(key)
    ordered = sorted(examples, key=lambda item: hashlib.sha256(f"{seed}\0{item.task}".encode()).hexdigest())
    train_end = min(len(ordered) - 2, max(1, len(ordered) * 3 // 5))
    val_end = min(len(ordered) - 1, train_end + max(1, len(ordered) // 5))
    return {"train": ordered[:train_end], "val": ordered[train_end:val_end], "holdout": ordered[val_end:]}


def apply_description_mutation(baseline: dict[str, ToolDescription], mutations: dict[str, str]) -> dict[str, ToolDescription]:
    """只改变文字，不改变工具名、参数名及参数结构。"""
    result = dict(baseline)
    for name, text in mutations.items():
        if name not in baseline:
            raise ValueError(f"unknown tool: {name}")
        result[name] = replace(baseline[name], description=text)
    errors = validate_descriptions(result)
    if errors:
        raise ValueError("; ".join(errors))
    return result


def evaluate_candidate(candidate: dict[str, ToolDescription], examples: list[ToolSelectionExample], selector: Callable[[dict[str, ToolDescription], str], tuple[str, dict[str, Any] | None]], baseline: ToolSelectionScore | None = None) -> ToolSelectionScore:
    predictions = []
    for example in examples:
        chosen, params = selector(candidate, example.task)
        predictions.append((chosen, example.correct_tool, params))
    return score_tool_selection(predictions, baseline, examples)

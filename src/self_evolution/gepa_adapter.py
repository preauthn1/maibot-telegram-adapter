"""DSPy/GEPA 适配：真实编译、真实候选突变，不提供伪优化回退。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Callable

from .backend import ConfiguredModelBackend
from .dataset import Example


@dataclass(frozen=True)
class Score:
    value: float
    feedback: str


def reflective_fitness(example: Example, output: str, judge: Callable[[str], str] | None = None) -> Score:
    if judge is None:
        raise RuntimeError("reflective judge unavailable; evaluation aborted")
    prompt = json.dumps({"task": example.input, "rubric": example.expected_behavior, "answer": output, "format": "JSON {score:0..1, feedback:string}"}, ensure_ascii=False)
    raw = judge(prompt)
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 20_000:
        raise RuntimeError("reflective judge returned an invalid response")
    try:
        parsed = json.loads(raw)
        score = float(parsed["score"])
        feedback = parsed["feedback"]
        if not math.isfinite(score) or not 0 <= score <= 1 or not isinstance(feedback, str) or not feedback.strip():
            raise ValueError
        return Score(score, feedback)
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError("reflective judge returned invalid JSON or score") from exc


def extract_instruction(module: object) -> str:
    candidates: list[object] = [module]
    predictor = getattr(module, "predictor", None)
    if predictor is not None:
        candidates.append(predictor)
        signature = getattr(predictor, "signature", None)
        if signature is not None:
            candidates.append(signature)
    for item in candidates:
        for attr in ("instructions", "instruction"):
            value = getattr(item, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
    raise RuntimeError("optimized module has no extractable mutated instruction")


def run_gepa(seed_instruction: str, examples: list[Example], backend: ConfiguredModelBackend, *, steps: int = 1, val_examples: list[Example] | None = None) -> str:
    """用已安装的真实 DSPy GEPA 运行有限预算优化；缺依赖或配置错误直接失败。"""
    if type(steps) is not int or steps < 1 or steps > 50:
        raise ValueError("steps must be within [1, 50]")
    try:
        import dspy
    except ImportError as exc:
        raise RuntimeError("isolated environment must provide dspy with gepa") from exc
    if not hasattr(dspy, "GEPA"):
        raise RuntimeError("installed dspy has no GEPA")

    instruction = seed_instruction.strip()
    if not instruction or len(instruction.encode("utf-8")) > 15_000:
        raise ValueError("seed instruction must be non-empty and <= 15000 bytes")
    if not examples:
        raise ValueError("GEPA requires at least one training example")
    if val_examples is not None and not val_examples:
        raise ValueError("GEPA validation set must not be empty")

    class TaskSignature(dspy.Signature):
        """根据任务和优化后的指导生成行为正确的回答。"""
        task_input: str = dspy.InputField()
        output: str = dspy.OutputField()

    class Module(dspy.Module):
        def __init__(self, text: str):
            super().__init__()
            self.predictor = dspy.Predict(TaskSignature)
            self.predictor.signature.instructions = text

        def forward(self, task_input: str):
            return self.predictor(task_input=task_input)

    lm_kwargs: dict[str, Any] = {"temperature": backend.temperature, "max_tokens": backend.max_tokens}
    if str(backend.model).startswith(("gpt-5", "o1", "o3")):
        lm_kwargs["temperature"] = 1.0
        lm_kwargs["max_tokens"] = max(int(lm_kwargs.get("max_tokens") or 0), 16000)
    lm_kwargs.update(backend.extra_params)
    forbidden_params = {"model", "messages", "stream", "tools", "response_format"}
    if forbidden_params.intersection(lm_kwargs):
        raise ValueError("extra_params attempts to override protected completion fields")
    lm = dspy.LM(f"openai/{backend.model}", api_base=backend.base_url, api_key=backend.api_key, **lm_kwargs)
    dspy.configure(lm=lm)

    def metric(example: Any, prediction: Any, trace: Any = None, pred_name: Any = None, pred_trace: Any = None) -> Any:
        del trace, pred_name, pred_trace
        task_input = getattr(example, "task_input", None)
        expected_behavior = getattr(example, "expected_behavior", None)
        if not isinstance(task_input, str) or not isinstance(expected_behavior, str) or not task_input.strip() or not expected_behavior.strip():
            raise TypeError("GEPA examples must expose non-empty task_input and expected_behavior strings")
        item = Example(task_input.strip(), expected_behavior.strip())
        answer_value = getattr(prediction, "output", None)
        if not isinstance(answer_value, str):
            raise TypeError("GEPA prediction must expose a string output")
        answer = answer_value
        judged = reflective_fitness(item, answer, lambda p: backend.complete([{"role": "system", "content": "只输出 JSON。"}, {"role": "user", "content": p}]))
        return dspy.Prediction(score=judged.value, feedback=judged.feedback)

    trainset = [dspy.Example(task_input=x.input, expected_behavior=x.expected_behavior).with_inputs("task_input") for x in examples]
    valset = [dspy.Example(task_input=x.input, expected_behavior=x.expected_behavior).with_inputs("task_input") for x in (val_examples or examples)]
    optimizer = dspy.GEPA(
        metric=metric,
        max_metric_calls=max(steps * max(3, len(trainset)), 3),
        reflection_lm=lm,
        reflection_minibatch_size=min(3, max(1, len(trainset))),
        num_threads=1,
        seed=0,
    )
    optimized = optimizer.compile(Module(instruction), trainset=trainset, valset=valset)
    evolved = extract_instruction(optimized)
    # GEPA may legitimately keep the baseline when all evaluated examples are
    # already perfect. This is a valid no-change result, not an optimization
    # failure; the caller must compare holdout scores before approval.
    return evolved

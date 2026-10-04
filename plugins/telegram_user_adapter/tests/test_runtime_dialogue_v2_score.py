from pathlib import Path

import importlib.util

import pytest

SPEC = importlib.util.spec_from_file_location("runtime_v2_score", Path(__file__).resolve().parents[3] / "scripts/score_runtime_dialogue_v2.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("评分模块不存在")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def fixture():
    return {"scenarios": [{"id": "case", "turns": [{"user": "只回好", "expected_exact": "好"}]}]}


def test_exact():
    result = module.score_cases(fixture(), {"case": [{"user": "只回好", "output": "好", "finish_reason": "stop"}]})
    assert result["fully_accepted"] is True


@pytest.mark.parametrize("output,reason,state", [("好。", "stop", "fail"), ("好", "length", "invalid"), ("", "stop", "invalid")])
def test_no_normalization_or_incomplete_success(output, reason, state):
    result = module.score_cases(fixture(), {"case": [{"user": "只回好", "output": output, "finish_reason": reason}]})
    assert result["counts"][state] == 1
    assert result["fully_accepted"] is False


@pytest.mark.parametrize("observations", [{}, {"other": []}, {"case": []}, {"case": [{"user": "不同输入"}]}])
def test_reject_wrong_coverage(observations):
    with pytest.raises(ValueError):
        module.score_cases(fixture(), observations)


def test_manual_rubric_is_not_automatic_pass():
    data = {"scenarios": [{"id": "case", "turns": [{"user": "难受", "rubric": "共情但不补写经历"}]}]}
    result = module.score_cases(data, {"case": [{"user": "难受", "output": "唉。", "finish_reason": "stop"}]})
    assert result["counts"]["review_required"] == 1
    assert result["fully_accepted"] is False

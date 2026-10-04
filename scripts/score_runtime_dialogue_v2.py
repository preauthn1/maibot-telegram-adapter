"""固定场景覆盖与逐字要求的保守评分；不把主观自然度伪装成自动通过。"""
from typing import Any, Dict

import argparse
import json
from pathlib import Path


def score_cases(fixture: Dict[str, Any], observations: Dict[str, Any]) -> Dict[str, Any]:
    """observations: {scenario_id: [{user, output, finish_reason}, ...]}。"""
    scenarios = fixture.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("评测场景必须非空")
    expected = {}
    for case in scenarios:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"]:
            raise ValueError("场景编号无效")
        if case["id"] in expected or not isinstance(case.get("turns"), list) or not case["turns"]:
            raise ValueError("场景重复或轮次无效")
        for turn in case["turns"]:
            if not isinstance(turn, dict) or not isinstance(turn.get("user"), str) or not turn["user"]:
                raise ValueError("输入正文无效")
            if ("expected_exact" in turn) == ("rubric" in turn):
                raise ValueError("每轮必须且只能有一个验收标准")
            criterion = turn.get("expected_exact", turn.get("rubric"))
            if not isinstance(criterion, str) or not criterion:
                raise ValueError("验收标准为空")
        expected[case["id"]] = case["turns"]
    if not isinstance(observations, dict) or set(observations) != set(expected):
        raise ValueError("实际场景与固定场景不一致")
    rows = []
    for name, turns in expected.items():
        actual = observations[name]
        if not isinstance(actual, list) or len(actual) != len(turns):
            raise ValueError("场景轮次不完整")
        for index, (want, got) in enumerate(zip(turns, actual, strict=True)):
            if not isinstance(got, dict) or got.get("user") != want["user"]:
                raise ValueError("实际输入与固定输入不一致")
            output = got.get("output")
            if not isinstance(output, str) or not output.strip() or got.get("finish_reason") != "stop":
                state = "invalid"
            elif "expected_exact" in want:
                state = "pass" if output == want["expected_exact"] else "fail"
            else:
                state = "review_required"
            rows.append({"scenario": name, "turn": index, "status": state})
    counts = {state: sum(row["status"] == state for row in rows)
              for state in ("pass", "fail", "invalid", "review_required")}
    return {"coverage": "complete", "counts": counts, "rows": rows,
            "all_exact_passed": counts["fail"] == counts["invalid"] == 0,
            "fully_accepted": counts["fail"] == counts["invalid"] == counts["review_required"] == 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("observations", type=Path)
    args = parser.parse_args()
    result = score_cases(json.loads(args.fixture.read_text()), json.loads(args.observations.read_text()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["fully_accepted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

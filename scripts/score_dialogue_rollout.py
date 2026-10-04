"""仅对明确可判定的多轮要求评分；主观质量保持待复核。"""
import argparse
import json
from pathlib import Path

SUITE_SHAPES = {
    'paraphrase_v1': {'duration_attachment': 1, 'owner_attachment': 1, 'correction_attachment': 1, 'uncertain_cause': 1},
    'relations_v1': {'preparation_window': 2, 'ownership_duration': 2, 'temporal_correction': 2},
    'open_dialogue_v1': {'casual': 2, 'emotion': 2, 'revision_history': 3},
    'transfer_v1': {'sharing_to_help': 2, 'feeling_boundary': 2, 'ownership_correction': 2},
    'rollout_v1': {'correction': 3, 'intent': 3},
    'heldout_grounding_v1': {
        'emotion_unspecified': 1, 'emotion_explicit': 1,
        'evidence_missing': 1, 'attribution': 2,
    },
}

EXPECTED = {
    ('relations_v1', 'preparation_window', 1): '未说明',
    ('relations_v1', 'ownership_duration', 1): '未知',
    ('relations_v1', 'temporal_correction', 1): '三月报名；七月训练',
    ('rollout_v1', 'correction', 1): 'Alpine',
    ('rollout_v1', 'correction', 2): 'Ubuntu→Alpine',
    ('rollout_v1', 'intent', 2): '好',
    ('heldout_grounding_v1', 'attribution', 1): '狗',
}


def score(report):
    # 老报告没有版本，不能根据文件名或场景名称猜测版本。
    suite = report.get('suite')
    rows = []
    scenarios = report.get('scenarios', {})
    for name, turns in scenarios.items():
        for index, turn in enumerate(turns):
            expected = EXPECTED.get((suite, name, index))
            output = turn.get('output')
            if turn.get('completion_status') != 'complete' or not isinstance(output, str) or not output.strip():
                status = 'invalid'
            elif expected is None:
                status = 'review_required'
            else:
                # 用户要求只回答时，仅忽略两端空白；额外标点也应如实报出。
                status = 'pass' if output.strip() == expected else 'fail'
            rows.append({'scenario': name, 'turn': index + 1, 'status': status, 'expected': expected})
    expected_turns = report.get('expected_turns')
    shape = SUITE_SHAPES.get(suite)
    issues = []
    if shape is None:
        coverage = 'unverified'
    else:
        for name, required in shape.items():
            actual = len(scenarios.get(name, []))
            if actual != required:
                issues.append({'scenario': name, 'expected': required, 'observed': actual})
        for name in scenarios.keys() - shape.keys():
            issues.append({'scenario': name, 'expected': 0, 'observed': len(scenarios[name])})
        if type(expected_turns) is not int or expected_turns != sum(shape.values()):
            issues.append({'field': 'expected_turns', 'reason': 'missing_or_inconsistent'})
        coverage = 'incomplete' if issues else 'complete'
    counts = {status: sum(row['status'] == status for row in rows)
              for status in ('pass', 'fail', 'invalid', 'review_required')}
    return {'scope': 'exact constraints only; not overall dialogue quality',
            'suite': suite, 'coverage': coverage, 'observed_turns': len(rows),
            'expected_turns': expected_turns, 'coverage_issues': issues, 'counts': counts, 'checks': rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('report', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = score(json.loads(args.report.read_text(encoding='utf-8')))
    result['source_report'] = str(args.report)
    # 不覆盖既有审核证据。
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

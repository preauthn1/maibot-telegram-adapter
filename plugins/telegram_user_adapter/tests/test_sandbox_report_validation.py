"""沙箱回放不能用等量重复轮次掩盖缺失场景。"""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from verify_history_sandbox import report_bodies


def sample():
    return {'suite': 'transfer_v1', 'expected_turns': 6, 'scenarios': {
        k: [{'output': '合成回答', 'completion_status': 'complete'} for _ in range(2)]
        for k in ('sharing_to_help', 'feeling_boundary', 'ownership_correction')}}


def test_complete_report():
    assert len(report_bodies(sample())) == 6


@pytest.mark.parametrize('fault', ['same_total', 'unknown', 'empty', 'truncated'])
def test_rejects_invalid_report(fault):
    report = sample()
    if fault == 'same_total':
        report['scenarios']['sharing_to_help'].extend(report['scenarios'].pop('feeling_boundary'))
    elif fault == 'unknown':
        report['suite'] = 'unknown'
    elif fault == 'empty':
        report['scenarios']['sharing_to_help'][0]['output'] = ''
    else:
        report['scenarios']['sharing_to_help'][0]['completion_status'] = 'truncated'
    with pytest.raises(ValueError):
        report_bodies(report)

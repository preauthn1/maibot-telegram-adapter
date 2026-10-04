"""评测不把缺失、未审查或关键词覆盖误报为通过。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from score_dialogue_constraints import assess


def row(case, output, ok=True):
    return dict(case=case+'__r1', variant='baseline', output=output, ok=ok)


def test_missing_output_is_invalid():
    assert assess(row('memory_provided', '', False))['status'] == 'invalid'


def test_exact_name_and_extra_claim():
    assert assess(row('memory_provided', '豆豆'))['status'] == 'pass'
    assert assess(row('memory_provided', '豆豆，我见过它'))['status'] == 'flag'


def test_advice_signal_and_unreviewed_empathy():
    assert assess(row('no_advice', '先歇会儿吧'))['status'] == 'flag'
    assert assess(row('no_advice', '今天真够累的'))['status'] == 'review'


def test_headings_do_not_prove_correctness():
    result = assess(row('detail_requested', '备份 验证 回滚'))
    assert result['status'] == 'review'
    assert 'technical_correctness_not_checked' in result['signals']

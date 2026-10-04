"""截断回答即使包含期望答案也不能算完整生成。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from dialogue_eval_metadata import completion_status
from score_dialogue_constraints import assess


def test_generation_states():
    assert completion_status('豆豆', 'stop') == 'complete'
    assert completion_status('豆豆', 'length') == 'truncated'
    assert completion_status(' ', 'stop') == 'empty'
    assert completion_status('豆豆', None) == 'unverified_finish'
    assert completion_status('豆豆', 'content_filter') == 'unverified_finish'


def test_truncated_expected_answer_is_invalid():
    result = assess(dict(case='memory_provided__r1', variant='baseline',
                         output='豆豆', ok=True, finish_reason='length'))
    assert result['status'] == 'invalid'

"""审核完整性不等于语义判定正确；这里只验证证据不被改写。"""
import copy
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from validate_blind_review import validate


def fixture():
    original = {'tasks': [{'id': 'a', 'context': [{'role': 'user', 'content': '你好'}], 'response': '你好'}]}
    reviewed = copy.deepcopy(original)
    reviewed['tasks'][0].update(review={'grounding': 'pass', 'intent_fit': 'pass', 'continuity': 'pass', 'naturalness': 3}, evidence_quotes=['你好'], rationale='回应问候')
    return original, reviewed


def test_valid_review():
    original, reviewed = fixture()
    assert validate(original, reviewed) == 1


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'id', 'context', 'response', 'quote', 'score', 'bool_score', 'reason', 'empty_quotes'])
def test_rejects_corrupt_review(fault):
    original, reviewed = fixture()
    row = reviewed['tasks'][0]
    if fault == 'missing': reviewed['tasks'].clear()
    elif fault == 'duplicate': reviewed['tasks'].append(copy.deepcopy(row))
    elif fault == 'id': row['id'] = 'unknown'
    elif fault == 'context': row['context'][0]['content'] = 'changed'
    elif fault == 'response': row['response'] = 'changed'
    elif fault == 'quote': row['evidence_quotes'] = ['不存在的引文']
    elif fault == 'score': row['review']['naturalness'] = 6
    elif fault == 'bool_score': row['review']['naturalness'] = True
    elif fault == 'reason': row['rationale'] = ' '
    elif fault == 'empty_quotes': row['evidence_quotes'] = []
    with pytest.raises(AssertionError):
        validate(original, reviewed)

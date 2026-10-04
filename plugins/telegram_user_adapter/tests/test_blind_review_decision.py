"""候选决策不得用自然度抵消事实失败。"""
import copy
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from summarize_blind_review import summarize


def fixture():
    tasks = [{'id': name, 'context': [{'role': 'user', 'content': '你好'}], 'response': '你好'}
             for name in ('a', 'b')]
    original = {'tasks': tasks}
    reviewed = copy.deepcopy(original)
    for row in reviewed['tasks']:
        row.update(review={'grounding': 'pass', 'intent_fit': 'pass', 'continuity': 'pass',
                           'naturalness': 3}, evidence_quotes=['你好'], rationale='合成测试理由')
    mapping = {name: {'variant': variant, 'scenario': 'greeting', 'turn': 1}
               for name, variant in [('a', 'current'), ('b', 'intent_fit')]}
    return original, reviewed, mapping


def test_explicit_candidate_variant():
    original, reviewed, mapping = fixture()
    mapping['b']['variant'] = 'grounded_intent'
    result = summarize(original, reviewed, mapping, candidate_variant='grounded_intent')
    assert result['paired_turns'] == 1
    assert set(result['counts']) == {'current', 'grounded_intent'}
    assert result['deployment'] == 'not_applied'


def test_candidate_cannot_be_baseline():
    with pytest.raises(ValueError, match='distinct'):
        summarize(*fixture(), candidate_variant='current')


def test_factual_regression_blocks_high_naturalness():
    original, reviewed, mapping = fixture()
    reviewed['tasks'][1]['review'].update(grounding='fail', naturalness=5)
    result = summarize(original, reviewed, mapping)
    assert result['selection'] == 'retain_baseline'
    assert result['new_failures'][0]['dimension'] == 'grounding'
    assert result['deployment'] == 'not_applied'


def test_same_label_different_user_history_rejected():
    original, reviewed, mapping = fixture()
    for document in (original, reviewed):
        document['tasks'][1]['context'][0]['content'] = '不同问题'
    with pytest.raises(ValueError, match='user histories'):
        summarize(original, reviewed, mapping)


def test_different_generated_history_allowed():
    original, reviewed, mapping = fixture()
    for document in (original, reviewed):
        document['tasks'][0]['context'].insert(0, {'role': 'assistant', 'content': '旧回复甲'})
        document['tasks'][1]['context'].insert(0, {'role': 'assistant', 'content': '旧回复乙'})
    assert summarize(original, reviewed, mapping)['paired_turns'] == 1


def test_equal_scores_never_auto_approve():
    result = summarize(*fixture())
    assert result['selection'] == 'further_review_required'
    assert result['deployment'] == 'not_applied'


def test_unpaired_scenario_rejected():
    original, reviewed, mapping = fixture()
    mapping['b']['scenario'] = 'different'
    with pytest.raises(ValueError, match='Unpaired'):
        summarize(original, reviewed, mapping)


def test_missing_mapping_rejected():
    original, reviewed, mapping = fixture()
    del mapping['b']
    with pytest.raises(ValueError, match='Mapping'):
        summarize(original, reviewed, mapping)


def test_improvement_is_recorded_not_deployed():
    original, reviewed, mapping = fixture()
    reviewed['tasks'][0]['review']['intent_fit'] = 'fail'
    result = summarize(original, reviewed, mapping)
    assert len(result['resolved_failures']) == 1
    assert result['selection'] == 'further_review_required'
    assert result['deployment'] == 'not_applied'

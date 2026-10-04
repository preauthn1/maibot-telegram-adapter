"""明确格式要求与主观质量分开验收。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from score_dialogue_rollout import score


def sample(output='狗', status='complete'):
    return {'suite': 'heldout_grounding_v1', 'expected_turns': 5,
            'scenarios': {
                'emotion_unspecified': [{'output': '难受', 'completion_status': 'complete'}],
                'emotion_explicit': [{'output': '收到', 'completion_status': 'complete'}],
                'evidence_missing': [{'output': '证据不足', 'completion_status': 'complete'}],
                'attribution': [
                {'output': '收到', 'completion_status': 'complete'},
                {'output': output, 'completion_status': status}]}}


def test_exact_and_subjective_are_separate():
    result = score(sample())
    assert result['coverage'] == 'complete'
    assert result['counts'] == {'pass': 1, 'fail': 0, 'invalid': 0, 'review_required': 4}


def test_extra_text_is_not_exact_answer():
    assert score(sample('狗。'))['counts']['fail'] == 1


def test_truncated_correct_text_is_invalid():
    assert score(sample('狗', 'truncated'))['counts']['invalid'] == 1


def test_missing_turn_is_not_complete():
    report = sample()
    report['scenarios']['attribution'].pop()
    assert score(report)['coverage'] == 'incomplete'


def test_legacy_suite_is_not_guessed():
    report = sample()
    del report['suite']
    del report['expected_turns']
    result = score(report)
    assert result['coverage'] == 'unverified'
    assert result['counts']['pass'] == 0


def test_equal_total_does_not_hide_missing_scenario():
    report = sample()
    removed = report['scenarios'].pop('emotion_unspecified')
    report['scenarios']['attribution'].extend(removed)
    result = score(report)
    assert result['observed_turns'] == result['expected_turns']
    assert result['coverage'] == 'incomplete'
    assert len(result['coverage_issues']) == 2


def test_unknown_suite_never_reports_complete():
    report = sample()
    report['suite'] = 'unknown'
    assert score(report)['coverage'] == 'unverified'


def test_new_suites_coverage_without_invented_exact_rules():
    for suite, shape in [
        ('open_dialogue_v1', {'casual': 2, 'emotion': 2, 'revision_history': 3}),
        ('transfer_v1', {'sharing_to_help': 2, 'feeling_boundary': 2, 'ownership_correction': 2}),
    ]:
        report = {'suite': suite, 'expected_turns': sum(shape.values()), 'scenarios': {
            key: [{'output': '待语义复核', 'completion_status': 'complete'} for _ in range(n)]
            for key, n in shape.items()}}
        result = score(report)
        assert result['coverage'] == 'complete'
        assert result['counts']['pass'] == 0
        assert result['counts']['review_required'] == report['expected_turns']
        report['scenarios'][next(iter(shape))].pop()
        assert score(report)['coverage'] == 'incomplete'


def test_relation_answers_do_not_certify_spontaneous_paraphrase():
    shape = {'preparation_window': '未说明', 'ownership_duration': '未知',
             'temporal_correction': '三月报名；七月训练'}
    report = {'suite': 'relations_v1', 'expected_turns': 6, 'scenarios': {
        key: [{'output': '三个月里三次失败', 'completion_status': 'complete'},
              {'output': answer, 'completion_status': 'complete'}]
        for key, answer in shape.items()}}
    result = score(report)
    assert result['counts'] == {'pass': 3, 'fail': 0, 'invalid': 0, 'review_required': 3}
    report['scenarios']['preparation_window'][1]['output'] = '已说明'
    assert score(report)['counts']['fail'] == 1


def test_paraphrase_requires_semantic_review_even_with_all_numbers():
    names = ['duration_attachment', 'owner_attachment', 'correction_attachment', 'uncertain_cause']
    report = {'suite': 'paraphrase_v1', 'expected_turns': 4, 'scenarios': {
        name: [{'output': '八个月两次六年二月六月周三周五', 'completion_status': 'complete'}]
        for name in names}}
    result = score(report)
    assert result['coverage'] == 'complete'
    assert result['counts']['pass'] == 0
    assert result['counts']['review_required'] == 4
    report['scenarios']['owner_attachment'] = []
    assert score(report)['coverage'] == 'incomplete'


def test_empty_success_is_invalid():
    assert score(sample(''))['counts']['invalid'] == 1

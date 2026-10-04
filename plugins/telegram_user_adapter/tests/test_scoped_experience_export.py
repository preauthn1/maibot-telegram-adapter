"""真实导出到真实读取，不使用生产数据。"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
from src.chat.utils.chat_experience import build_scoped_experience_prompt_block

spec = importlib.util.spec_from_file_location('scoped_export_test', Path(__file__).parents[1] / 'scoped_experience_export.py')
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_export_read_and_revoke(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base = tmp_path / 'data/plugins/adapter'
    state = {'avoid_phrases': ['GLOBAL'], 'suspicion_samples': [{'chat_id': '-1', 'our_text': 'IDENTITY'}],
             'violation_samples': [{'chat_id': '-1', 'kind': 'aggressive', 'our_text': 'ONE'},
                                   {'chat_id': '-2', 'kind': 'aggressive', 'our_text': 'TWO'}]}
    target = module.export_scoped_experience(base, state, '-1')
    session = SimpleNamespace(platform='telegram', group_id='-1', user_id=None)
    text = build_scoped_experience_prompt_block(session)
    assert 'ONE' in text and '待核实' in text
    assert all(word not in text for word in ['TWO', 'GLOBAL', 'IDENTITY'])
    module.export_scoped_experience(base, {}, '-1')
    assert target.read_text() == ''
    assert build_scoped_experience_prompt_block(session) == ''
    assert not list(target.parent.glob('.experience-*'))


@pytest.mark.parametrize('operation', ['replace', 'fsync'])
def test_failed_write_preserves_previous_file(tmp_path, monkeypatch, operation):
    base = tmp_path / 'adapter'
    state = {'violation_samples': [{'chat_id': '-1', 'kind': 'aggressive', 'our_text': 'OLD'}]}
    target = module.export_scoped_experience(base, state, '-1')
    previous = target.read_bytes()
    def fail(*args):
        raise OSError('simulated storage failure')
    monkeypatch.setattr(module.os, operation, fail)
    state['violation_samples'][0]['our_text'] = 'NEW'
    with pytest.raises(OSError):
        module.export_scoped_experience(base, state, '-1')
    assert target.read_bytes() == previous
    assert not list(target.parent.glob('.experience-*'))


@pytest.mark.parametrize('bad', [None, 'broken', {}, [None]])
def test_corrupt_samples_preserve_previous_file(tmp_path, bad):
    target = module.export_scoped_experience(tmp_path, {'violation_samples': [
        {'chat_id': '-1', 'kind': 'aggressive', 'our_text': 'OLD'}]}, '-1')
    previous = target.read_bytes()
    with pytest.raises(ValueError):
        module.export_scoped_experience(tmp_path, {'violation_samples': bad}, '-1')
    assert target.read_bytes() == previous


def test_export_preserves_long_text_tail(tmp_path):
    text = '前文' * 110 + '但这个结论不成立。'
    target = module.export_scoped_experience(tmp_path, {'violation_samples': [
        {'chat_id': '-1', 'kind': 'aggressive', 'our_text': text}]}, '-1')
    import json
    records = json.loads(target.read_text(encoding='utf-8').split('\n', 1)[1])
    assert records[0]['text'] == text


@pytest.mark.parametrize('field', ['kind', 'our_text'])
@pytest.mark.parametrize('value', [None, 12, [], {}])
def test_invalid_sample_fields_preserve_export(tmp_path, field, value):
    item = {'chat_id': '-1', 'kind': 'aggressive', 'our_text': 'OLD'}
    target = module.export_scoped_experience(tmp_path, {'violation_samples': [item]}, '-1')
    previous = target.read_bytes()
    item[field] = value
    with pytest.raises(ValueError):
        module.export_scoped_experience(tmp_path, {'violation_samples': [item]}, '-1')
    assert target.read_bytes() == previous


def test_invalid_id(tmp_path):
    with pytest.raises(ValueError):
        module.export_scoped_experience(tmp_path, {}, '../other')

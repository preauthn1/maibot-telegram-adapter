"""模拟引擎吞掉反思异常后的结束检查。"""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from dialogue_evolution_errors import TrackedCompletion


def test_swallowed_error_remains_failure(tmp_path):
    def fail(_):
        raise ValueError('PRIVATE_TOKEN must not appear')
    path = tmp_path / 'errors.jsonl'
    client = TrackedCompletion(fail, path)
    try:
        client('reflection prompt')
    except ValueError:
        pass
    with pytest.raises(RuntimeError):
        client.require_clean()
    assert client.failures == [{'phase': 'reflection', 'error_type': 'ValueError'}]
    assert 'PRIVATE_TOKEN' not in path.read_text()


def test_clean_calls_preserve_result(tmp_path):
    client = TrackedCompletion(lambda _: '真实测试返回值', tmp_path / 'errors.jsonl')
    assert client([]) == '真实测试返回值'
    client.require_clean()
    assert not client.failures

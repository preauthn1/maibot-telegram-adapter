"""退出码为零也不能掩盖跳过或空测试。"""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from run_isolated_dialogue_tests import regression_passed

@pytest.mark.parametrize('code,tests,failures,errors,skipped,expected', [
    (0, 3, 0, 0, 0, True),
    (0, 3, 0, 0, 1, False),
    (0, 0, 0, 0, 0, False),
    (1, 3, 0, 0, 0, False),
    (0, 3, 1, 0, 0, False),
    (0, 3, 0, 1, 0, False),
])
def test_regression_gate(code, tests, failures, errors, skipped, expected):
    assert regression_passed(code, dict(tests=tests, failures=failures, errors=errors, skipped=skipped)) is expected

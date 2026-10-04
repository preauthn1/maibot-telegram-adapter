"""实验参数冲突应在读取凭据或创建运行目录前失败。"""
from pathlib import Path
import subprocess
import sys
import pytest

SCRIPT = Path(__file__).resolve().parents[3] / 'scripts' / 'evaluate_dialogue_rollout.py'


@pytest.mark.parametrize('flags', [
    ['--open-dialogue', '--heldout-grounding'],
    ['--transfer', '--open-dialogue'],
    ['--transfer', '--heldout-grounding'],
    ['--grounded-intent', '--intent-fit'],
    ['--relations', '--paraphrase'],
    ['--relations', '--transfer'],
    ['--paraphrase', '--open-dialogue'],
    ['--evidence-examples', '--grounding'],
    ['--evidence-examples', '--grounded-intent'],
    ['--evidence-examples', '--intent-fit'],
])
def test_conflicting_rollout_flags_fail_before_config(tmp_path, flags):
    result = subprocess.run([sys.executable, str(SCRIPT), *flags], cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert 'error:' in result.stderr
    assert 'FileNotFoundError' not in result.stderr
    assert not (tmp_path / 'data').exists()

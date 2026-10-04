import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from junit_evidence import verified_counts

@pytest.mark.parametrize('declared,body,valid', [
    (1, '<testcase name="a"/>', True),
    (2, '<testcase name="a"/>', False),
    (0, '', False),
    (1, '<testcase name="a"><failure/></testcase>', False),
])
def test_junit_counts(tmp_path, declared, body, valid):
    path = tmp_path/'result.xml'
    path.write_text(f'<testsuites><testsuite tests="{declared}" failures="0" errors="0" skipped="0">{body}</testsuite></testsuites>')
    if valid:
        assert verified_counts(path) == {'tests':1, 'failures':0, 'errors':0, 'skipped':0}
    else:
        with pytest.raises(ValueError):
            verified_counts(path)

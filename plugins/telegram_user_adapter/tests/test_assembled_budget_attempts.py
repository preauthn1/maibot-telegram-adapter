"""回退成本必须计入首轮，不把未知用量当零。"""
import hashlib
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from audit_assembled_prompt_budget import audit

@pytest.mark.parametrize('first_usage', [None, {'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}])
def test_budget_accounts_for_stream_attempt(tmp_path, first_usage):
    source = tmp_path/'assembled-one.json'
    source.write_text(json.dumps({'sample_id':'one','messages':[{'role':'user','content':'test'}]}))
    results = tmp_path/'results.json'
    results.write_text(json.dumps({'results':[{'sample_id':'one',
        'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'passed':True,'elapsed_seconds':1,'fallback_attempted':True,
        'stream_attempt':{'usage':first_usage},
        'usage':{'prompt_tokens':10,'completion_tokens':3,'total_tokens':13}}]}))
    if first_usage is None:
        with pytest.raises(ValueError, match='usage'):
            audit(tmp_path, results)
    else:
        report = audit(tmp_path, results)
        assert report['reported_token_totals'] == {'prompt_tokens':20,'completion_tokens':5,'total_tokens':25}
        assert report['samples'][0]['attempt_count'] == 2

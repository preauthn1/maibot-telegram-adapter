"""Real SQLite evidence timestamps, including replay."""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('replay', [False, True])
@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), -float('inf'), 'invalid'])
def test_evidence_invalid_time(tmp_path, replay, value):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        p = s.add_paragraph('合成证据')
        claim = s.upsert_fact_claim(scope_type='person', scope_id='synthetic', fact_key='key', value_text='事实')
        args = dict(evidence_type='paragraph', evidence_id=p)
        if replay: s.add_fact_evidence(claim['claim_id'], **args, observed_at=0)
        def snapshot():
            return [tuple(r) for r in s._conn.execute('SELECT * FROM fact_evidence ORDER BY rowid')]
        before = snapshot(); changes = s._conn.total_changes
        with pytest.raises(ValueError, match='^invalid_fact_time$'):
            s.add_fact_evidence(claim['claim_id'], **args, observed_at=value)
        assert s._conn.total_changes == changes
        s.close(); s.connect()
        assert snapshot() == before
        result = s.add_fact_evidence(claim['claim_id'], **args, observed_at='0')
        assert result['observed_at'] == 0
    finally: s.close()

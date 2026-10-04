"""Invalid weights on idempotent replays must be rejected before any writes."""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


@pytest.mark.parametrize('api', ['claim', 'evidence'])
@pytest.mark.parametrize('weight', [True, float('nan'), 1.1])
def test_invalid_replay_weight(tmp_path, api, weight):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        p = s.add_paragraph('合成证据')
        args = dict(scope_type='person', scope_id='synthetic', fact_key='key', value_text='合成事实',
                    evidence_type='paragraph', evidence_id=p)
        old = s.upsert_fact_claim(**args, evidence_weight=0.25)
        def snapshot():
            return {t: [tuple(r) for r in s._conn.execute(f'SELECT * FROM {t} ORDER BY rowid')]
                    for t in ('fact_claims', 'fact_evidence', 'fact_transitions')}
        before = snapshot()
        changes = s._conn.total_changes
        with pytest.raises(ValueError, match='^invalid_fact_evidence_weight$'):
            if api == 'claim':
                s.upsert_fact_claim(**args, evidence_weight=weight)
            else:
                s.add_fact_evidence(old['claim_id'], evidence_type='paragraph', evidence_id=p, weight=weight)
        assert s._conn.total_changes == changes
        s.close(); s.connect()
        assert snapshot() == before
        replay = s.upsert_fact_claim(**args, evidence_weight=0.25)
        assert replay['idempotent'] is True
        assert snapshot() == before
    finally:
        s.close()

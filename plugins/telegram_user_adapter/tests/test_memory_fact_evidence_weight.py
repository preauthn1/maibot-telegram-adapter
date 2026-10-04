"""Real SQLite evidence weight validation and transactional rollback."""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


@pytest.mark.parametrize('weight', [True, False, float('nan'), float('inf'), -0.1, 1.1, 'invalid'])
@pytest.mark.parametrize('create', [False, True])
def test_invalid_evidence_weight(tmp_path, weight, create):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        p = s.add_paragraph('合成证据')
        args = dict(scope_type='person', scope_id='synthetic', fact_key='test', value_text='合成事实')
        old = None if create else s.upsert_fact_claim(**args)
        def snapshot():
            return {t: [tuple(r) for r in s._conn.execute(f'SELECT * FROM {t} ORDER BY rowid')]
                    for t in ('fact_claims', 'fact_evidence', 'fact_transitions')}
        before = snapshot()
        with pytest.raises(ValueError, match='^invalid_fact_evidence_weight$'):
            if create:
                s.upsert_fact_claim(**args, evidence_type='paragraph', evidence_id=p, evidence_weight=weight)
            else:
                s.add_fact_evidence(old['claim_id'], evidence_type='paragraph', evidence_id=p, weight=weight)
        assert not s._conn.in_transaction
        assert snapshot() == before
        s.close(); s.connect()
        assert snapshot() == before
    finally:
        s.close()


def test_zero_evidence_weight_persists(tmp_path):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        p = s.add_paragraph('合成零权重证据')
        s.upsert_fact_claim(scope_type='person', scope_id='synthetic', fact_key='test',
            value_text='合成事实', evidence_type='paragraph', evidence_id=p, evidence_weight=0)
        s.close(); s.connect()
        assert s._conn.execute('SELECT weight FROM fact_evidence').fetchone()[0] == 0
    finally:
        s.close()

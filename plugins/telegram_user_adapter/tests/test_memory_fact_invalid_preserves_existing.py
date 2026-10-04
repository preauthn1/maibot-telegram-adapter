"""Invalid confidence must not reinforce or supersede existing real SQLite facts."""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


@pytest.mark.parametrize('replace', [False, True])
@pytest.mark.parametrize('score', [True, float('nan'), 1.1])
def test_invalid_preserves_existing(tmp_path, replace, score):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        args = dict(scope_type='person', scope_id='synthetic', fact_key='favorite',
                    cardinality='single', value_text='合成旧值', confidence=0.25)
        original = store.upsert_fact_claim(**args)
        def snapshot():
            return {table: [tuple(r) for r in store._conn.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                    for table in ('fact_claims', 'fact_evidence', 'fact_transitions')}
        before = snapshot()
        changes = store._conn.total_changes
        bad = dict(args, confidence=score)
        if replace:
            bad.update(value_text='合成新值', supersedes_claim_ids=[original['claim_id']])
        with pytest.raises(ValueError, match='^invalid_fact_confidence$'):
            store.upsert_fact_claim(**bad)
        assert store._conn.total_changes == changes
        assert snapshot() == before
        store.close(); store.connect()
        assert snapshot() == before
        old = store.get_fact_claim(original['claim_id'])
        assert old['status'] == 'active' and old['confidence'] == 0.25
    finally:
        store.close()

"""Real SQLite fact storage validates confidence independently of ingest."""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


@pytest.mark.parametrize('score', [True, False, float('nan'), float('inf'), -float('inf'), -0.1, 1.1, 'synthetic-invalid'])
def test_fact_storage_invalid_score(tmp_path, score):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        before = store._conn.total_changes
        with pytest.raises(ValueError, match='^invalid_fact_confidence$'):
            store.upsert_fact_claim(scope_type='person', scope_id='synthetic-person',
                fact_key='synthetic-key', value_text='合成事实', confidence=score)
        assert store._conn.total_changes == before
        store.close(); store.connect()
        assert store.list_fact_claims(scope_type='person', scope_id='synthetic-person') == []
    finally:
        store.close()

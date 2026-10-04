"""Actual ingest + SQLite: invalid person score fails before paragraph/vector effects."""
import asyncio
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService


@pytest.mark.parametrize('score', [True, float('nan'), -0.1, 'synthetic-invalid'])
def test_person_score_preflight(tmp_path, score):
    store = MetadataStore(data_dir=tmp_path); store.connect()
    try:
        vector = AsyncMock(return_value={})
        svc = SimpleNamespace(metadata_store=store, relation_write_service=Mock(),
            initialize=AsyncMock(), _is_chat_filtered=lambda **kw: False,
            _write_paragraph_vector_or_enqueue=vector)
        svc._write_person_fact_claims = MethodType(MemoryIngestService._write_person_fact_claims, svc)
        before = store._conn.total_changes
        with pytest.raises(ValueError, match='^invalid_person_fact_confidence$'):
            asyncio.run(MemoryIngestService.ingest_text(svc, external_id='synthetic-preflight',
                source_type='person_fact', text='合成事实', person_ids=['synthetic-person'],
                metadata={'fact_claim': {'confidence': score}}))
        assert store._conn.total_changes == before
        vector.assert_not_awaited()
        store.close(); store.connect()
        assert store._conn.execute('SELECT count(*) FROM paragraphs').fetchone()[0] == 0
        assert store.get_external_memory_ref('synthetic-preflight') is None
    finally:
        store.close()

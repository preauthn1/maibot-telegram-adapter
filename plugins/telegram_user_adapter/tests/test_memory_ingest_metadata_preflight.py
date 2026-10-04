"""Actual ingest and SQLite; graph/vector dependencies are synthetic."""
import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService
from src.A_memorix.core.utils.relation_write_service import RelationWriteService


@pytest.mark.parametrize('conflict', ['set', 'cycle', 'mixed_keys'])
def test_ingest_metadata_preflight(tmp_path, conflict):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        writer = SimpleNamespace(metadata_store=store,
            graph_store=SimpleNamespace(batch_update=nullcontext, add_edges=Mock()))
        async def write(**kwargs):
            return await RelationWriteService.upsert_relation_with_vector(writer, **kwargs)
        writer.upsert_relation_with_vector = AsyncMock(side_effect=write)
        vector = AsyncMock(return_value={})
        svc = SimpleNamespace(metadata_store=store, relation_write_service=writer,
            relation_vectors_enabled=False, _is_chat_filtered=lambda **kw: False,
            initialize=AsyncMock(), _write_paragraph_vector_or_enqueue=vector, _persist=Mock())
        a = dict(subject='合成甲', predicate='喜欢', object='合成乙', confidence=0.5, metadata={'origin':'synthetic'})
        b = dict(a, object='合成丙')
        bad = {'value': {'synthetic'}}
        if conflict == 'cycle':
            bad = {}; bad['self'] = bad
        if conflict == 'mixed_keys': bad = {1: 'one', 'two': 2}
        b['metadata'] = bad
        before = store._conn.total_changes
        call = MemoryIngestService.ingest_text(svc, external_id='synthetic-duplicates',
            source_type='chat_summary', text='合成重复关系', relations=[a,b])
        if conflict:
            with pytest.raises(ValueError, match='invalid_relation_metadata'):
                asyncio.run(call)
            assert store._conn.total_changes == before
            vector.assert_not_awaited()
            writer.upsert_relation_with_vector.assert_not_awaited()
        else:
            result = asyncio.run(call)
            assert len(result['stored_ids']) == len(set(result['stored_ids'])) == 2
            assert writer.upsert_relation_with_vector.await_count == 1
        store.close(); store.connect()
        assert store._conn.execute('SELECT count(*) FROM relations').fetchone()[0] == (0 if conflict else 1)
        if conflict:
            assert store._conn.execute('SELECT count(*) FROM paragraphs').fetchone()[0] == 0
            assert store.get_external_memory_ref('synthetic-duplicates') is None
    finally:
        store.close()

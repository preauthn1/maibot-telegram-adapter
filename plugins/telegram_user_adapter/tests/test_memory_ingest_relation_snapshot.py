"""SQLite persistence uses preflight relation metadata despite mutation across await."""
import asyncio
import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService
from src.A_memorix.core.utils.relation_write_service import RelationWriteService


def test_relation_metadata_snapshot(tmp_path):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        metadata = {'evidence': {'ids': ['synthetic-original']}}
        row = dict(subject='甲', predicate='喜欢', object='乙', confidence=0.5, metadata=metadata)
        writer = SimpleNamespace(metadata_store=store,
            graph_store=SimpleNamespace(batch_update=nullcontext, add_edges=Mock()))
        async def write(**kwargs):
            return await RelationWriteService.upsert_relation_with_vector(writer, **kwargs)
        writer.upsert_relation_with_vector = AsyncMock(side_effect=write)
        async def change_input(**kwargs):
            await asyncio.sleep(0)
            metadata['evidence']['ids'].append('synthetic-late')
            return {}
        svc = SimpleNamespace(metadata_store=store, relation_write_service=writer,
            relation_vectors_enabled=False, _is_chat_filtered=lambda **kw: False,
            initialize=AsyncMock(), _write_paragraph_vector_or_enqueue=change_input, _persist=Mock())
        asyncio.run(MemoryIngestService.ingest_text(svc, external_id='synthetic-snapshot',
            source_type='chat_summary', text='合成快照', relations=[row]))
        assert metadata['evidence']['ids'] == ['synthetic-original', 'synthetic-late']
        assert writer.upsert_relation_with_vector.call_args.kwargs['metadata'] == {
            'evidence': {'ids': ['synthetic-original']}}
        h = store.compute_relation_hash('甲', '喜欢', '乙')
        store.close(); store.connect()
        actual = store.get_relation(h)['metadata']
        if isinstance(actual, str): actual = json.loads(actual)
        assert actual['evidence']['ids'] == ['synthetic-original']
    finally:
        store.close()

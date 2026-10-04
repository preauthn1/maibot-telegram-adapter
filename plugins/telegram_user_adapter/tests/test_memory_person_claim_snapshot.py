"""Actual ingest/SQLite paragraph; claim persistence is a spy, vector await mutates caller input."""
import asyncio
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService


def test_person_metadata_snapshot(tmp_path, monkeypatch):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        metadata = {'fact_claim': {'confidence': 0.25}, 'evidence_message_ids': ['original']}
        claim = Mock(return_value={'claim_id': 'synthetic-claim'})
        monkeypatch.setattr(store, 'upsert_fact_claim', claim)
        async def vector(**kw):
            await asyncio.sleep(0)
            metadata['fact_claim']['confidence'] = 0.9
            metadata['evidence_message_ids'].append('late')
            return {}
        svc = SimpleNamespace(metadata_store=store, relation_write_service=Mock(),
            initialize=AsyncMock(), _is_chat_filtered=lambda **kw: False,
            _write_paragraph_vector_or_enqueue=vector, _persist=Mock(),
            _mark_person_active=Mock(), _enqueue_person_profile_refresh=Mock())
        svc._write_person_fact_claims = MethodType(MemoryIngestService._write_person_fact_claims, svc)
        result = asyncio.run(MemoryIngestService.ingest_text(svc,
            external_id='synthetic-person-snapshot', source_type='person_fact',
            text='合成事实', person_ids=['synthetic-person'], metadata=metadata))
        claim.assert_called_once()
        assert claim.call_args.kwargs['confidence'] == 0.25
        assert claim.call_args.kwargs['evidence_metadata']['evidence_message_ids'] == ['original']
        assert metadata['fact_claim']['confidence'] == 0.9
        assert metadata['evidence_message_ids'] == ['original', 'late']
        store.close(); store.connect()
        assert store.get_external_memory_ref('synthetic-person-snapshot')['paragraph_hash'] == result['stored_ids'][0]
    finally:
        store.close()

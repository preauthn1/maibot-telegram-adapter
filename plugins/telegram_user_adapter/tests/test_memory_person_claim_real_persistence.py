"""Actual ingest and fact persistence; vector processing and profile scheduling mocked."""
import asyncio
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService


@pytest.mark.parametrize('trust', ['manual_confirmed', ''])
@pytest.mark.parametrize('score', [0, 0.25, 0.9, None])
def test_person_claim_real_persistence(tmp_path, trust, score):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        svc = SimpleNamespace(metadata_store=store, relation_write_service=Mock(),
            initialize=AsyncMock(), _is_chat_filtered=lambda **kw: False,
            _write_paragraph_vector_or_enqueue=AsyncMock(return_value={}), _persist=Mock(),
            _mark_person_active=Mock(), _enqueue_person_profile_refresh=Mock())
        svc._write_person_fact_claims = MethodType(MemoryIngestService._write_person_fact_claims, svc)
        result = asyncio.run(MemoryIngestService.ingest_text(svc,
            external_id='synthetic-person-persist', source_type='person_fact',
            text='合成人物事实', person_ids=['synthetic-person'],
            metadata={'fact_claim': {'trust': trust, 'confidence': score}}))
        assert len(result['fact_claim_ids']) == 1
        store.close(); store.connect()
        claim = store.get_fact_claim(result['fact_claim_ids'][0])
        assert claim is not None
        expected = (1.0 if trust else 0.5) if score is None else score
        if not trust:
            expected = min(0.5, expected)
        assert claim['confidence'] == expected
        assert claim['authority'] == ('manual' if trust else 'summary_derived')
        assert claim['stability'] == ('stable' if trust else 'uncertain')
        assert claim['scope_id'] == 'synthetic-person'
        ref = store.get_external_memory_ref('synthetic-person-persist')
        assert ref is not None and ref['paragraph_hash'] == result['stored_ids'][0]
        svc._mark_person_active.assert_called_once_with('synthetic-person')
        svc._enqueue_person_profile_refresh.assert_called_once()
    finally:
        store.close()

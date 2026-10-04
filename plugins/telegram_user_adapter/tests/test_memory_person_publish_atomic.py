"""Actual ingest and SQLite: person publication rolls back if external mapping fails."""
import asyncio
import json
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService


@pytest.mark.parametrize('cancelled', [False, True])
@pytest.mark.parametrize('stage', ['mapping', 'paragraph'])
def test_person_mapping_failure_rolls_back(tmp_path, monkeypatch, cancelled, stage):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        svc = SimpleNamespace(metadata_store=s, relation_write_service=Mock(),
            initialize=AsyncMock(), _is_chat_filtered=lambda **kw: False,
            _write_paragraph_vector_or_enqueue=AsyncMock(return_value={}), _persist=Mock(),
            _mark_person_active=Mock(), _enqueue_person_profile_refresh=Mock())
        svc._write_person_fact_claims = MethodType(MemoryIngestService._write_person_fact_claims, svc)
        method = 'upsert_external_memory_ref' if stage == 'mapping' else 'update_paragraph_metadata'
        original = getattr(s, method)
        error = asyncio.CancelledError() if cancelled else OSError('synthetic mapping failure')
        def fail(*args, **kw):
            original(*args, **kw)
            raise error
        monkeypatch.setattr(s, method, fail)
        args = dict(external_id='synthetic-publish', source_type='person_fact',
                    text='synthetic fact', person_ids=['synthetic-person'])
        with pytest.raises(type(error)) as caught:
            asyncio.run(MemoryIngestService.ingest_text(svc, **args))
        assert caught.value is error
        svc._persist.assert_not_called()
        svc._enqueue_person_profile_refresh.assert_not_called()
        s.close(); s.connect()
        assert s.get_external_memory_ref('synthetic-publish') is None
        for table in ('fact_claims', 'fact_evidence', 'fact_transitions'):
            assert s._conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0
        # Earlier paragraph remains: this is deliberately not full ingest atomicity.
        assert s._conn.execute('SELECT count(*) FROM paragraphs').fetchone()[0] == 1
        paragraph_id = s._conn.execute('SELECT hash FROM paragraphs').fetchone()[0]
        metadata = s.get_paragraph(paragraph_id)['metadata']
        if isinstance(metadata, str): metadata = json.loads(metadata)
        assert 'fact_claim_ids' not in metadata
        monkeypatch.setattr(s, method, original)
        result = asyncio.run(MemoryIngestService.ingest_text(svc, **args))
        s.close(); s.connect()
        assert len(result['fact_claim_ids']) == 1
        assert s.get_fact_claim(result['fact_claim_ids'][0]) is not None
        assert s.get_external_memory_ref('synthetic-publish') is not None
        metadata = s.get_paragraph(paragraph_id)['metadata']
        if isinstance(metadata, str): metadata = json.loads(metadata)
        assert metadata['fact_claim_ids'] == result['fact_claim_ids']
    finally:
        s.close()

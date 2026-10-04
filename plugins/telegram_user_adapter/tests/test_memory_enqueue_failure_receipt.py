"""Actual enqueue helper must not turn storage failure into queued success."""
import asyncio
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest
from src.A_memorix.core.runtime.services.embedding_state_service import MemoryEmbeddingStateService
from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService


@pytest.mark.parametrize('missing', [False, True])
def test_enqueue_failure_cannot_report_success(missing, monkeypatch):
    error = OSError('SYNTHETIC_PRIVATE_QUEUE_ERROR')
    storage = None if missing else SimpleNamespace(enqueue_paragraph_vector_backfill=Mock(side_effect=error))
    logger = Mock()
    monkeypatch.setattr('src.A_memorix.core.runtime.services.embedding_state_service.logger', logger)
    svc = SimpleNamespace(metadata_store=storage, _allow_metadata_only_write=lambda: True,
                          _paragraph_store=lambda: None)
    svc._enqueue_paragraph_vector_backfill = MethodType(
        MemoryEmbeddingStateService._enqueue_paragraph_vector_backfill, svc)
    with pytest.raises(RuntimeError if missing else OSError) as caught:
        asyncio.run(MemoryIngestService._write_paragraph_vector_or_enqueue(
            svc, paragraph_hash='synthetic', content='synthetic paragraph'))
    if not missing:
        assert caught.value is error
        storage.enqueue_paragraph_vector_backfill.assert_called_once()
    assert 'SYNTHETIC_PRIVATE_QUEUE_ERROR' not in repr(logger.mock_calls)

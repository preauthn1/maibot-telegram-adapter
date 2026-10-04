"""Actual direct ingest helper -> SQLite queue -> real vector save/load; synthetic embeddings."""
import asyncio
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np

from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.storage.vector_store import VectorStore
from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService
from src.A_memorix.core.runtime.services.embedding_state_service import MemoryEmbeddingStateService
from src.A_memorix.core.runtime.services.vector_runtime_service import MemoryVectorRuntimeService


def test_direct_invalid_vector_recovers_via_backfill(tmp_path):
    store = MetadataStore(data_dir=tmp_path / 'metadata')
    store.connect()
    try:
        text = '\n    synthetic evidence\n'
        p = store.add_paragraph(text)
        vectors = VectorStore(dimension=4, data_dir=tmp_path / 'vectors', use_mmap=False)
        direct = AsyncMock(return_value=np.array([float('nan'), 0, 0, 0]))
        batch = AsyncMock(return_value=np.array([[1, 0, 0, 0]], dtype=np.float32))
        svc = SimpleNamespace(metadata_store=store, vector_store=vectors,
            embedding_manager=SimpleNamespace(encode=direct, encode_batch=batch),
            _paragraph_store=lambda: vectors, _allow_metadata_only_write=lambda: True,
            _is_embedding_degraded=lambda: False, _embedding_fallback_enabled=lambda: False,
            _persist=vectors.save)
        svc._enqueue_paragraph_vector_backfill = MethodType(
            MemoryEmbeddingStateService._enqueue_paragraph_vector_backfill, svc)
        svc._encode_and_add_rebuild_vectors = MethodType(
            MemoryVectorRuntimeService._encode_and_add_rebuild_vectors, svc)
        receipt = asyncio.run(MemoryIngestService._write_paragraph_vector_or_enqueue(
            svc, paragraph_hash=p, content=text))
        assert receipt['queued'] is True and receipt['vector_written'] is False
        assert p not in vectors
        store.close(); store.connect()
        pending = store.fetch_paragraph_vector_backfill_batch()
        assert len(pending) == 1 and pending[0]['paragraph_hash'] == p
        assert pending[0]['last_error'] == 'paragraph_vector_write_failed:ValueError'
        result = asyncio.run(MemoryVectorRuntimeService._run_paragraph_backfill_once(svc, limit=2, max_retry=3))
        assert result['done'] == 1 and result['failed'] == 0
        restored = VectorStore(dimension=4, data_dir=tmp_path / 'vectors', use_mmap=False)
        restored.load()
        assert p in restored
        store.close(); store.connect()
        assert store.get_paragraph_vector_backfill_status_counts()['done'] == 1
        assert store.get_paragraph(p)['content'] == text
        direct.assert_awaited_once_with(text)
        batch.assert_awaited_once_with([text], batch_size=2)
    finally:
        store.close()

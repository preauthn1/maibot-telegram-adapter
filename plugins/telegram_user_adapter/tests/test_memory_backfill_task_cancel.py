"""Real task cancellation at encoder await; SQLite and vector store are real."""
import asyncio
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock
import numpy as np
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.storage.vector_store import VectorStore
from src.A_memorix.core.runtime.services.vector_runtime_service import MemoryVectorRuntimeService as Service


def test_backfill_task_cancel_reclaim(tmp_path):
    store = MetadataStore(data_dir=tmp_path / 'metadata')
    store.connect()
    try:
        p = store.add_paragraph('合成任务取消恢复')
        store.enqueue_paragraph_vector_backfill(p)
        vectors = VectorStore(dimension=4, data_dir=tmp_path / 'vectors', use_mmap=False)
        async def scenario():
            entered = asyncio.Event()
            release = asyncio.Event()
            async def encode(texts, **kw):
                entered.set()
                await release.wait()
                return np.array([[1., 0, 0, 0]], dtype=np.float32)
            encoder = AsyncMock(side_effect=encode)
            svc = SimpleNamespace(metadata_store=store, vector_store=vectors,
                embedding_manager=SimpleNamespace(encode_batch=encoder),
                _paragraph_store=lambda: vectors, _is_embedding_degraded=lambda: False,
                _persist=vectors.save)
            svc._encode_and_add_rebuild_vectors = MethodType(Service._encode_and_add_rebuild_vectors, svc)
            task = asyncio.create_task(Service._run_paragraph_backfill_once(svc, limit=1, max_retry=3))
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                assert store.get_paragraph_vector_backfill_status_counts()['running'] == 1
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert task.cancelled() and p not in vectors
                store.close(); store.connect()
                assert store.get_paragraph_vector_backfill_status_counts()['running'] == 0
                pending = store.fetch_paragraph_vector_backfill_batch(max_retry=3)
                assert len(pending) == 1 and pending[0]['status'] == 'failed'
                assert pending[0]['retry_count'] == 1
                release.set()
                result = await Service._run_paragraph_backfill_once(svc, limit=1, max_retry=3)
                assert result['done'] == 1 and result['failed'] == 0
                assert encoder.await_count == 2
            finally:
                release.set()
                if not task.done(): task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        asyncio.run(scenario())
        store.close(); store.connect()
        assert store.get_paragraph_vector_backfill_status_counts()['done'] == 1
        loaded = VectorStore(dimension=4, data_dir=tmp_path / 'vectors', use_mmap=False)
        loaded.load()
        assert p in loaded
    finally:
        store.close()

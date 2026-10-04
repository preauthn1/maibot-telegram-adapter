"""Real SQLite and VectorStore recovery; synthetic embedding, explicit caller save."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.storage.vector_store import VectorStore
from src.A_memorix.core.utils.relation_write_service import RelationWriteService, _RelationVectorRecord


@pytest.mark.parametrize('typed', [False, True])
@pytest.mark.parametrize('batch', [False, True])
def test_relation_real_vector_recovery(tmp_path, typed, batch):
    store = MetadataStore(data_dir=tmp_path / 'metadata')
    store.connect()
    try:
        h = store.add_relation('合成甲', '喜欢', '合成乙')
        vectors = VectorStore(dimension=4, data_dir=tmp_path / 'vectors', use_mmap=False)
        wrong_pool = VectorStore(dimension=4, data_dir=tmp_path / 'other', use_mmap=False)
        encode = AsyncMock(side_effect=[np.array([np.nan, 0, 0, 0]), np.array([1., 0, 0, 0])])
        encode_batch = AsyncMock(side_effect=[np.array([[np.nan, 0, 0, 0]]), np.array([[1., 0, 0, 0]])])
        manager = SimpleNamespace(encode=encode, encode_batch=encode_batch, batch_size=2, max_concurrent=1)
        writer = RelationWriteService(store, None, wrong_pool if typed else vectors, manager,
                                      graph_vector_store=vectors if typed else wrong_pool)
        async def run():
            if batch:
                return (await writer._ensure_relation_vectors([
                    _RelationVectorRecord(h, '合成甲', '喜欢', '合成乙')], typed_id=typed))[0]
            return await writer.ensure_relation_vector(h, '合成甲', '喜欢', '合成乙', typed_id=typed)
        vector_id = writer.relation_vector_id(h) if typed else h
        first = asyncio.run(run())
        assert first.vector_state == 'failed' and vector_id not in vectors
        store.close(); store.connect()
        assert store.get_relation(h)['vector_state'] == 'failed'
        second = asyncio.run(run())
        assert second.vector_state == 'ready' and second.vector_written
        # ready is not a persistence receipt: caller explicitly saves here.
        vectors.save()
        restored = VectorStore(dimension=4, data_dir=tmp_path / 'vectors', use_mmap=False)
        restored.load()
        assert vector_id in restored
        assert h not in wrong_pool and writer.relation_vector_id(h) not in wrong_pool
        store.close(); store.connect()
        assert store.get_relation(h)['vector_state'] == 'ready'
        if typed:
            writer.graph_vector_store = restored
        else:
            writer.vector_store = restored
        third = asyncio.run(run())
        assert third.vector_already_exists and not third.vector_written
        assert (encode_batch if batch else encode).await_count == 2
        (encode if batch else encode_batch).assert_not_awaited()
    finally:
        store.close()

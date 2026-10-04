"""Mixed batch failure and retry with real SQLite/vector store, synthetic encoder."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import numpy as np
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.storage.vector_store import VectorStore
from src.A_memorix.core.utils.relation_write_service import RelationWriteService, _RelationVectorRecord


def test_mixed_batches_retry_only_failed(tmp_path):
    store = MetadataStore(data_dir=tmp_path / 'metadata')
    store.connect()
    try:
        records = []
        for obj in ('合成乙', '合成丙'):
            h = store.add_relation('合成甲', '喜欢', obj)
            records.append(_RelationVectorRecord(h, '合成甲', '喜欢', obj))
        vectors = VectorStore(dimension=4, data_dir=tmp_path / 'vectors', use_mmap=False)
        encode = AsyncMock(side_effect=[OSError('synthetic'),
            np.array([[1., 0, 0, 0]]), np.array([[0., 1, 0, 0]])])
        writer = RelationWriteService(store, None, vectors,
            SimpleNamespace(encode_batch=encode, batch_size=1, max_concurrent=1))
        result = asyncio.run(writer._ensure_relation_vectors(records))
        assert [r.vector_state for r in result] == ['failed', 'ready']
        assert records[0].hash_value not in vectors
        assert records[1].hash_value in vectors
        vectors.save()
        store.close(); store.connect()
        assert [store.get_relation(r.hash_value)['vector_state'] for r in records] == ['failed', 'ready']
        restored = VectorStore(dimension=4, data_dir=tmp_path / 'vectors', use_mmap=False)
        restored.load()
        writer.vector_store = restored
        retry = asyncio.run(writer._ensure_relation_vectors(records))
        assert [r.vector_state for r in retry] == ['ready', 'ready']
        assert retry[1].vector_already_exists and not retry[1].vector_written
        assert encode.await_count == 3
        first_text = writer.build_relation_vector_text('合成甲', '喜欢', '合成乙')
        second_text = writer.build_relation_vector_text('合成甲', '喜欢', '合成丙')
        assert [c.args[0] for c in encode.await_args_list] == [[first_text], [second_text], [first_text]]
        restored.save()
        final = VectorStore(dimension=4, data_dir=tmp_path / 'vectors', use_mmap=False)
        final.load()
        assert all(r.hash_value in final for r in records)
        store.close(); store.connect()
        assert all(store.get_relation(r.hash_value)['vector_state'] == 'ready' for r in records)
    finally:
        store.close()

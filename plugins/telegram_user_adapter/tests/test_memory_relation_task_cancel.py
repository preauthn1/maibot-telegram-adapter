"""Real Task.cancel at embedding await; real SQLite and vector persistence."""
import asyncio
from types import SimpleNamespace
import numpy as np
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.storage.vector_store import VectorStore
from src.A_memorix.core.utils.relation_write_service import RelationWriteService, _RelationVectorRecord


@pytest.mark.parametrize('batch', [False, True])
def test_real_task_cancel_then_retry(tmp_path, batch):
    store = MetadataStore(data_dir=tmp_path / 'db'); store.connect()
    try:
        h = store.add_relation('甲', '喜欢', '乙')
        vectors = VectorStore(dimension=4, data_dir=tmp_path / 'vectors', use_mmap=False)
        async def scenario():
            entered = asyncio.Event()
            never = asyncio.Event()
            calls = []
            async def blocked(*args, **kwargs):
                calls.append(args)
                entered.set()
                await never.wait()
            manager = SimpleNamespace(encode=blocked, encode_batch=blocked, batch_size=1, max_concurrent=1)
            writer = RelationWriteService(store, None, vectors, manager)
            async def run():
                if batch:
                    return (await writer._ensure_relation_vectors([_RelationVectorRecord(h, '甲', '喜欢', '乙')]))[0]
                return await writer.ensure_relation_vector(h, '甲', '喜欢', '乙')
            task = asyncio.create_task(run())
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert task.cancelled() and h not in vectors
                store.close(); store.connect()
                row = store.get_relation(h)
                assert row is not None and row['vector_state'] == 'pending'
                async def valid(*args, **kwargs):
                    calls.append(args)
                    return np.array([[1., 0, 0, 0]]) if batch else np.array([1., 0, 0, 0])
                manager.encode = manager.encode_batch = valid
                result = await run()
                assert result.vector_state == 'ready'
                assert len(calls) == 2
                vectors.save()
                reloaded = VectorStore(dimension=4, data_dir=tmp_path / 'vectors', use_mmap=False)
                reloaded.load()
                assert h in reloaded
                store.close(); store.connect()
                assert store.get_relation(h)['vector_state'] == 'ready'
            finally:
                if not task.done(): task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        asyncio.run(scenario())
    finally:
        store.close()

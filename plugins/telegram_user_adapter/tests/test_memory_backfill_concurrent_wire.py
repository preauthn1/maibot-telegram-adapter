"""真实领取/回填/索引，事件控制合成编码暂停；不是多进程压力测试。"""
import asyncio
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock
import numpy as np
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.storage.vector_store import VectorStore
from src.A_memorix.core.runtime.services.vector_runtime_service import MemoryVectorRuntimeService as Service


def test_second_consumer_cannot_encode_claimed_paragraph(tmp_path):
    store=MetadataStore(data_dir=tmp_path/'metadata');store.connect()
    try:
        p=store.add_paragraph('合成并发回填');store.enqueue_paragraph_vector_backfill(p)
        vectors=VectorStore(dimension=4,data_dir=tmp_path/'vectors',use_mmap=False)
        async def run():
            entered=asyncio.Event();release=asyncio.Event()
            async def encode(texts,**kw):
                entered.set()
                await release.wait()
                return np.array([[1,0,0,0]],dtype=np.float32)
            encoder=AsyncMock(side_effect=encode)
            svc=SimpleNamespace(metadata_store=store,embedding_manager=SimpleNamespace(encode_batch=encoder),
                vector_store=vectors,_paragraph_store=lambda:vectors,_is_embedding_degraded=lambda:False,_persist=vectors.save)
            svc._encode_and_add_rebuild_vectors=MethodType(Service._encode_and_add_rebuild_vectors,svc)
            first=asyncio.create_task(Service._run_paragraph_backfill_once(svc,limit=1,max_retry=3))
            try:
                await asyncio.wait_for(entered.wait(),timeout=3)
                # 重复生产者入队也不应撤销正在执行的领取。
                store.enqueue_paragraph_vector_backfill(p)
                second=await Service._run_paragraph_backfill_once(svc,limit=1,max_retry=3)
                assert second['processed']==0
                assert store.get_paragraph_vector_backfill_status_counts()['running']==1
                release.set()
                result=await asyncio.wait_for(first,timeout=3)
                assert result['done']==1
                encoder.assert_awaited_once_with(['合成并发回填'],batch_size=1)
            finally:
                release.set()
                if not first.done():first.cancel()
                await asyncio.gather(first,return_exceptions=True)
        asyncio.run(run())
        store.close();store.connect()
        assert store.get_paragraph_vector_backfill_status_counts()['done']==1
        loaded=VectorStore(dimension=4,data_dir=tmp_path/'vectors',use_mmap=False);loaded.load()
        assert p in loaded
    finally:store.close()

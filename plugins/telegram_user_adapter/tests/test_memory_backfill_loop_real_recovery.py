"""真实循环/批次/SQLite/向量保存重载；合成embedding与一次保存故障。"""
import asyncio
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock
import numpy as np
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.storage.vector_store import VectorStore
from src.A_memorix.core.runtime.services.vector_runtime_service import MemoryVectorRuntimeService
from src.A_memorix.core.runtime.services.background_task_service import MemoryBackgroundTaskService


def test_loop_recovers_persist_failure(tmp_path):
    store=MetadataStore(data_dir=tmp_path/'metadata');store.connect()
    try:
        receipt=store.ingest_relation_metadata_atomic(external_id='synthetic-loop',content='合成自动恢复',
            source='chat:synthetic',source_type='chat_summary',queue_paragraph_vector=True,
            relations=[dict(subject='甲',predicate='喜欢',object='乙')])
        p=receipt['stored_ids'][0]
        vectors=VectorStore(dimension=4,data_dir=tmp_path/'vectors',use_mmap=False)
        encoder=AsyncMock(return_value=np.array([[1,0,0,0]],dtype=np.float32))
        svc=SimpleNamespace(metadata_store=store,embedding_manager=SimpleNamespace(encode_batch=encoder),
            vector_store=vectors,_paragraph_store=lambda:vectors,_is_embedding_degraded=lambda:False,
            _background_stopping=False,_paragraph_vector_backfill_enabled=lambda:True,
            _paragraph_vector_backfill_batch_size=lambda:2,_paragraph_vector_backfill_max_retry=lambda:3)
        turns=[];saved=[]
        def interval():
            turns.append(store.get_paragraph_vector_backfill_status_counts())
            if turns[-1].get('done')==1:svc._background_stopping=True
            if len(turns)>4:raise AssertionError('loop failed to recover')
            return 0
        def persist():
            saved.append(True)
            if len(saved)==1:raise OSError('synthetic save fault')
            vectors.save()
        svc._paragraph_vector_backfill_interval_seconds=interval
        svc._persist=persist
        svc._encode_and_add_rebuild_vectors=MethodType(MemoryVectorRuntimeService._encode_and_add_rebuild_vectors,svc)
        svc._run_paragraph_backfill_once=MethodType(MemoryVectorRuntimeService._run_paragraph_backfill_once,svc)
        async def run():
            await asyncio.wait_for(MemoryBackgroundTaskService._paragraph_vector_backfill_loop(svc),timeout=5)
        asyncio.run(run())
        assert len(saved)==2
        assert [r.get('failed',0) for r in turns]==[0,1,0]
        encoder.assert_awaited_once_with(['合成自动恢复'],batch_size=2)
        store.close();store.connect()
        assert store.get_paragraph_vector_backfill_status_counts()['done']==1
        reopened=VectorStore(dimension=4,data_dir=tmp_path/'vectors',use_mmap=False);reopened.load()
        assert p in reopened
    finally:store.close()

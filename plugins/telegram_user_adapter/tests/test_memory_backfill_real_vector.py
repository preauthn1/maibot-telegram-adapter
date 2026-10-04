"""真实SQLite与VectorStore保存/重载；编码为固定合成向量。"""
import asyncio
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock
import numpy as np
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.storage.vector_store import VectorStore
from src.A_memorix.core.runtime.services.vector_runtime_service import MemoryVectorRuntimeService


def test_atomic_backfill_real_vector_reload(tmp_path):
    store=MetadataStore(data_dir=tmp_path/'metadata');store.connect()
    try:
        result=store.ingest_relation_metadata_atomic(external_id='synthetic-real-vector',content='合成索引持久化',
            source='chat:synthetic',source_type='chat_summary',queue_paragraph_vector=True,
            relations=[dict(subject='甲',predicate='喜欢',object='乙')])
        p=result['stored_ids'][0]
        vectors=VectorStore(dimension=4,data_dir=tmp_path/'vectors',use_mmap=False)
        encoder=AsyncMock(return_value=np.array([[1,0,0,0]],dtype=np.float32))
        svc=SimpleNamespace(metadata_store=store,embedding_manager=SimpleNamespace(encode_batch=encoder),
            vector_store=vectors,_paragraph_store=lambda:vectors,_is_embedding_degraded=lambda:False,
            _persist=vectors.save)
        svc._encode_and_add_rebuild_vectors=MethodType(MemoryVectorRuntimeService._encode_and_add_rebuild_vectors,svc)
        done=asyncio.run(MemoryVectorRuntimeService._run_paragraph_backfill_once(svc,limit=2,max_retry=3))
        assert done['done']==1
        reopened=VectorStore(dimension=4,data_dir=tmp_path/'vectors',use_mmap=False)
        reopened.load()
        assert p in reopened
        store.close();store.connect()
        assert store.get_paragraph_vector_backfill_status_counts()['done']==1
        svc._paragraph_store=lambda:reopened
        repeat=asyncio.run(MemoryVectorRuntimeService._run_paragraph_backfill_once(svc,limit=2,max_retry=3))
        assert repeat['processed']==0
        encoder.assert_awaited_once_with(['合成索引持久化'],batch_size=2)
    finally:store.close()

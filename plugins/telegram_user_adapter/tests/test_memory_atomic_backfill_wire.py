"""原子待办→真实回填编排→SQLite；编码/向量/持久化调用为替身。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.vector_runtime_service import MemoryVectorRuntimeService


def test_atomic_pending_consumed_by_existing_worker(tmp_path):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        receipt=store.ingest_relation_metadata_atomic(external_id='synthetic-wire',content='合成回填正文',
            source='chat:synthetic',source_type='chat_summary',queue_paragraph_vector=True,
            relations=[dict(subject='甲',predicate='喜欢',object='乙')])
        p=receipt['stored_ids'][0]
        store.close();store.connect()
        vectors=set()
        async def encode(*,items,batch_size,vector_store):
            assert items==[(p,'合成回填正文')]
            assert store.get_paragraph_vector_backfill_status_counts()['running']==1
            vector_store.add(p)
            return (1,0,'',[p],[])
        service=SimpleNamespace(metadata_store=store,embedding_manager=object(),
            _paragraph_store=lambda:vectors,_is_embedding_degraded=lambda:False,
            _encode_and_add_rebuild_vectors=AsyncMock(side_effect=encode),_persist=Mock())
        result=asyncio.run(MemoryVectorRuntimeService._run_paragraph_backfill_once(service,limit=2,max_retry=2))
        assert result['success'] is True and result['done']==1 and result['failed']==0
        service._persist.assert_called_once()
        store.close();store.connect()
        assert store.get_paragraph_vector_backfill_status_counts()['done']==1
        assert store.fetch_paragraph_vector_backfill_batch()==[]
        repeat=asyncio.run(MemoryVectorRuntimeService._run_paragraph_backfill_once(service,limit=2,max_retry=2))
        assert repeat['processed']==0
        service._encode_and_add_rebuild_vectors.assert_awaited_once()
    finally:store.close()

"""真实SQLite软删除段落不得进入编码；不涉及用户真实删除操作。"""
import asyncio
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.vector_runtime_service import MemoryVectorRuntimeService as Service


def test_deleted_paragraph_not_encoded(tmp_path):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        p=store.add_paragraph('合成已删除正文');store.enqueue_paragraph_vector_backfill(p)
        store._conn.execute('UPDATE paragraphs SET is_deleted=1 WHERE hash=?',(p,));store._conn.commit()
        encoder=AsyncMock(side_effect=AssertionError('deleted content reached encoder'))
        svc=SimpleNamespace(metadata_store=store,embedding_manager=SimpleNamespace(encode_batch=encoder),
            vector_store=set(),_paragraph_store=lambda:set(),_is_embedding_degraded=lambda:False,
            _embedding_fallback_enabled=lambda:False,_persist=Mock())
        svc._encode_and_add_rebuild_vectors=MethodType(Service._encode_and_add_rebuild_vectors,svc)
        result=asyncio.run(Service._run_paragraph_backfill_once(svc,limit=1,max_retry=3))
        encoder.assert_not_awaited()
        assert result['failed']==0 and result['done']==1
        store.close();store.connect()
        assert store.get_paragraph(p)['is_deleted']==1
        assert store.get_paragraph(p)['content']=='合成已删除正文'
        assert store.fetch_paragraph_vector_backfill_batch()==[]
    finally:store.close()

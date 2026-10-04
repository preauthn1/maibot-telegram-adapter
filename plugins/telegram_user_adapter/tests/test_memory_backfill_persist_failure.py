"""真实SQLite状态；向量/编码/保存故障为替身，不代表真实索引验收。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.vector_runtime_service import MemoryVectorRuntimeService

@pytest.mark.parametrize('error_type',[OSError,asyncio.CancelledError])
def test_persist_before_done(tmp_path,error_type):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        p=store.add_paragraph('合成保存故障');store.enqueue_paragraph_vector_backfill(p)
        error=error_type('synthetic-private')
        observed=[]
        def persist():
            observed.append(store.get_paragraph_vector_backfill_status_counts().get('done',0))
            raise error
        svc=SimpleNamespace(metadata_store=store,embedding_manager=object(),
            _paragraph_store=lambda:set(),_is_embedding_degraded=lambda:False,
            _encode_and_add_rebuild_vectors=AsyncMock(return_value=(1,0,'',[p],[])),_persist=Mock(side_effect=persist))
        with pytest.raises(error_type) as caught:
            asyncio.run(MemoryVectorRuntimeService._run_paragraph_backfill_once(svc,limit=2,max_retry=3))
        assert caught.value is error
        assert observed==[0]
        store.close();store.connect()
        rows=store.fetch_paragraph_vector_backfill_batch(max_retry=3)
        assert len(rows)==1 and rows[0]['status']=='failed'
        assert rows[0]['last_error']=='backfill_persist_interrupted:'+error_type.__name__
        svc._persist=Mock()
        result=asyncio.run(MemoryVectorRuntimeService._run_paragraph_backfill_once(svc,limit=2,max_retry=3))
        assert result['done']==1
        store.close();store.connect()
        assert store.get_paragraph_vector_backfill_status_counts()['done']==1
    finally:store.close()

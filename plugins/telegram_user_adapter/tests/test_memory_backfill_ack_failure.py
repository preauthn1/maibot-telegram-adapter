"""真实SQLite及向量落盘；完成确认首次故障，embedding为合成向量。"""
import asyncio
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock
import numpy as np
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.storage.vector_store import VectorStore
from src.A_memorix.core.runtime.services.vector_runtime_service import MemoryVectorRuntimeService as Service

@pytest.mark.parametrize('error_type',[OSError,asyncio.CancelledError])
def test_saved_vector_ack_retry(tmp_path,monkeypatch,error_type):
    store=MetadataStore(data_dir=tmp_path/'db');store.connect()
    try:
        p=store.add_paragraph('合成确认故障');store.enqueue_paragraph_vector_backfill(p)
        vectors=VectorStore(dimension=4,data_dir=tmp_path/'vectors',use_mmap=False)
        encoder=AsyncMock(return_value=np.array([[1,0,0,0]],dtype=np.float32))
        svc=SimpleNamespace(metadata_store=store,embedding_manager=SimpleNamespace(encode_batch=encoder),
            vector_store=vectors,_paragraph_store=lambda:vectors,_is_embedding_degraded=lambda:False,_persist=vectors.save)
        svc._encode_and_add_rebuild_vectors=MethodType(Service._encode_and_add_rebuild_vectors,svc)
        mark=store.mark_paragraph_vector_backfill_done
        error=error_type('synthetic-private')
        def fail(hashes):raise error
        monkeypatch.setattr(store,'mark_paragraph_vector_backfill_done',fail)
        with pytest.raises(error_type) as caught:
            asyncio.run(Service._run_paragraph_backfill_once(svc,limit=1,max_retry=3))
        assert caught.value is error
        loaded=VectorStore(dimension=4,data_dir=tmp_path/'vectors',use_mmap=False);loaded.load()
        assert p in loaded
        store.close();store.connect()
        rows=store.fetch_paragraph_vector_backfill_batch(max_retry=3)
        assert len(rows)==1 and rows[0]['status']=='failed'
        assert rows[0]['last_error']=='backfill_ack_interrupted:'+error_type.__name__
        monkeypatch.setattr(store,'mark_paragraph_vector_backfill_done',mark)
        svc._paragraph_store=lambda:loaded
        svc._persist=loaded.save
        result=asyncio.run(Service._run_paragraph_backfill_once(svc,limit=1,max_retry=3))
        assert result['done']==1
        encoder.assert_awaited_once()
        store.close();store.connect()
        assert store.get_paragraph_vector_backfill_status_counts()['done']==1
    finally:store.close()

"""真实SQLite任务状态；编码替身抛错，不访问外部模型。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.vector_runtime_service import MemoryVectorRuntimeService

@pytest.mark.parametrize('error_type',[OSError,asyncio.CancelledError])
@pytest.mark.parametrize('stage',['encode','read','contains'])
def test_interrupted_encode_remains_retryable(tmp_path,error_type,stage,monkeypatch):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        p=store.add_paragraph('合成待回填正文')
        store.enqueue_paragraph_vector_backfill(p)
        error=error_type('synthetic-private-detail')
        encoder=AsyncMock(side_effect=error if stage=='encode' else None)
        original_read=store.get_paragraphs_by_hashes
        if stage=='read':
            monkeypatch.setattr(store,'get_paragraphs_by_hashes',Mock(side_effect=error))
        class BrokenIndex:
            def __contains__(self,key):raise error
        vectors=BrokenIndex() if stage=='contains' else set()
        service=SimpleNamespace(metadata_store=store,embedding_manager=object(),
            _paragraph_store=lambda:vectors,_is_embedding_degraded=lambda:False,
            _encode_and_add_rebuild_vectors=encoder,_persist=Mock())
        with pytest.raises(error_type) as caught:
            asyncio.run(MemoryVectorRuntimeService._run_paragraph_backfill_once(service,limit=2,max_retry=3))
        assert caught.value is error
        store.close();store.connect()
        rows=store.fetch_paragraph_vector_backfill_batch(max_retry=3)
        assert len(rows)==1 and rows[0]['paragraph_hash']==p
        assert rows[0]['status']=='failed'
        assert rows[0]['last_error']=='backfill_interrupted:'+error_type.__name__
        if stage!='encode':encoder.assert_not_awaited()
        monkeypatch.setattr(store,'get_paragraphs_by_hashes',original_read)
        vectors=set()
        encoder.side_effect=None
        encoder.return_value=(1,0,'',[p],[])
        result=asyncio.run(MemoryVectorRuntimeService._run_paragraph_backfill_once(service,limit=2,max_retry=3))
        assert result['done']==1
        store.close();store.connect()
        assert store.get_paragraph_vector_backfill_status_counts()['done']==1
    finally:store.close()

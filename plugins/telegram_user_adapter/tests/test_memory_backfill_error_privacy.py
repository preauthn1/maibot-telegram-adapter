"""真实编码编排及SQLite错误回读；外部编码异常为合成替身。"""
import asyncio
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services import vector_runtime_service as module


def test_encoder_error_body_not_persisted(tmp_path,monkeypatch):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        p=store.add_paragraph('合成隐私测试');store.enqueue_paragraph_vector_backfill(p)
        marker='SYNTHETIC_PRIVATE_EXCEPTION_BODY'
        logs=Mock();monkeypatch.setattr(module,'logger',logs)
        svc=SimpleNamespace(metadata_store=store,embedding_manager=SimpleNamespace(encode_batch=AsyncMock(side_effect=OSError(marker))),
            vector_store=set(),_paragraph_store=lambda:set(),_is_embedding_degraded=lambda:False,
            _embedding_fallback_enabled=lambda:False,_persist=Mock())
        svc._encode_and_add_rebuild_vectors=MethodType(module.MemoryVectorRuntimeService._encode_and_add_rebuild_vectors,svc)
        result=asyncio.run(module.MemoryVectorRuntimeService._run_paragraph_backfill_once(svc,limit=2,max_retry=3))
        assert result['success'] is False and result['failed']==1
        store.close();store.connect()
        rows=store.fetch_paragraph_vector_backfill_batch(max_retry=3)
        assert len(rows)==1 and rows[0]['status']=='failed'
        assert rows[0]['last_error']=='vector_rebuild_failed:OSError'
        assert marker not in str(logs.mock_calls)
    finally:store.close()

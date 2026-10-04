"""显式零重试：真实SQLite队列，编码不应调用。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.vector_runtime_service import MemoryVectorRuntimeService


def test_zero_retry_does_not_use_default(tmp_path):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        p=store.add_paragraph('合成零重试')
        store.enqueue_paragraph_vector_backfill(p)
        store.mark_paragraph_vector_backfill_failed(p,'synthetic')
        before=dict(store._conn.execute('SELECT * FROM paragraph_vector_backfill').fetchone())
        default=Mock(return_value=5)
        encoder=AsyncMock(return_value=(1,0,'',[p],[]))
        svc=SimpleNamespace(metadata_store=store,embedding_manager=object(),
            _paragraph_store=lambda:set(),_is_embedding_degraded=lambda:False,
            _paragraph_vector_backfill_max_retry=default,
            _encode_and_add_rebuild_vectors=encoder,_persist=Mock())
        result=asyncio.run(MemoryVectorRuntimeService._run_paragraph_backfill_once(svc,limit=2,max_retry=0))
        assert result['processed']==0
        default.assert_not_called();encoder.assert_not_awaited()
        store.close();store.connect()
        assert dict(store._conn.execute('SELECT * FROM paragraph_vector_backfill').fetchone())==before
    finally:store.close()

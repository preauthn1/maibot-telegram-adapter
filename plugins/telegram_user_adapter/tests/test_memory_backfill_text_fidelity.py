"""真实SQLite到编码边界的正文保真；编码为替身。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.vector_runtime_service import MemoryVectorRuntimeService


def test_backfill_preserves_stored_whitespace(tmp_path):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        text='\n    合成代码示例\n        return False\n\n'
        p=store.add_paragraph(text);store.enqueue_paragraph_vector_backfill(p)
        assert store.get_paragraph(p)['content']==text
        encode=AsyncMock(return_value=(1,0,'',[p],[]))
        svc=SimpleNamespace(metadata_store=store,embedding_manager=object(),
            _paragraph_store=lambda:set(),_is_embedding_degraded=lambda:False,
            _encode_and_add_rebuild_vectors=encode,_persist=Mock())
        result=asyncio.run(MemoryVectorRuntimeService._run_paragraph_backfill_once(svc,limit=1,max_retry=1))
        assert result['done']==1
        assert encode.await_args.kwargs['items']==[(p,text)]
        store.close();store.connect()
        assert store.get_paragraph(p)['content']==text
    finally:store.close()

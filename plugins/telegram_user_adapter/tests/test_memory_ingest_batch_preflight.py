"""真实反馈适配→ingest→关系写入→SQLite；图/向量/初始化为替身。"""
import asyncio
from contextlib import nullcontext
from types import SimpleNamespace, MethodType
from unittest.mock import Mock, AsyncMock
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService
from src.A_memorix.core.runtime.services.feedback_correction_service import MemoryFeedbackCorrectionService as Feedback
from src.A_memorix.core.utils.relation_write_service import RelationWriteService

@pytest.mark.parametrize('score',['bad',float('nan'),float('inf'),-0.1,1.1,True])
def test_invalid_later_score_has_no_write(tmp_path,score):
    store=MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        writer=SimpleNamespace(metadata_store=store,graph_store=SimpleNamespace(batch_update=nullcontext,add_edges=Mock()))
        writer.upsert_relation_with_vector=MethodType(RelationWriteService.upsert_relation_with_vector,writer)
        service=SimpleNamespace(metadata_store=store,relation_write_service=writer,relation_vectors_enabled=False,
            _is_chat_filtered=Mock(return_value=False),initialize=AsyncMock(),
            _write_paragraph_vector_or_enqueue=AsyncMock(return_value={}),_persist=Mock(),
            _chat_source=lambda s:'chat:'+s)
        service.ingest_text=MethodType(MemoryIngestService.ingest_text,service)
        before=store._conn.total_changes
        rows=[{'subject':'合成甲','predicate':'喜欢','object':'合成乙','confidence':0.5},
              {'subject':'合成甲','predicate':'喜欢','object':'合成丙','confidence':score}]
        with pytest.raises(ValueError, match='invalid_relation_confidence'):
            asyncio.run(service.ingest_text(external_id='synthetic-invalid-batch',source_type='chat_summary',
                text='合成批量记忆',chat_id='synthetic',relations=rows))
        assert store._conn.total_changes==before
        writer.graph_store.add_edges.assert_not_called()
        service._write_paragraph_vector_or_enqueue.assert_not_called()
        service._persist.assert_not_called()
        store.close()
        store.connect()
        assert store.get_external_memory_ref('synthetic-invalid-batch') is None
        assert store.get_relation(store.compute_relation_hash('合成甲','喜欢','合成乙')) is None
    finally:
        store.close()

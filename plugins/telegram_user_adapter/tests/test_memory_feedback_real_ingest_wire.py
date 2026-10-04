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

@pytest.mark.parametrize('score',[0,0.5,1])
def test_feedback_receipt_matches_sqlite(tmp_path,score):
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
        normalized=Feedback._normalize_feedback_decision({'decision':'correct','confidence':1,
            'corrected_relations':[{'subject':'合成甲','predicate':'喜欢','object':'合成乙','confidence':score}]},hit_hashes=[])
        result=asyncio.run(Feedback._ingest_feedback_relations(service,query_tool_id='synthetic-query',
            session_id='synthetic-session',relation_hashes=['synthetic-old'],corrected_relations=normalized['corrected_relations']))
        assert result['success'] is True
        expected=store.compute_relation_hash('合成甲','喜欢','合成乙')
        assert result['corrected_relation_hashes']==[expected]
        assert result['stored_ids']==result['paragraph_hashes']+[expected]
        paragraph_id=result['paragraph_hashes'][0]
        assert store.get_external_memory_ref(result['external_id'])['paragraph_hash']==paragraph_id
        paragraph=store.get_paragraph(paragraph_id)
        assert paragraph['content']=='合成甲 喜欢 合成乙'
        row=store.get_relation(expected)
        assert row['confidence']==float(score)
        assert {r['hash'] for r in store.get_paragraph_relations(paragraph_id)}=={expected}
        store.close()
        store.connect()
        assert store.get_relation(expected)['confidence']==float(score)
        assert store.get_paragraph(paragraph_id)['content']==paragraph['content']
    finally:
        store.close()

"""真实ingest/关系写入/SQLite；图与向量替身，合成数据。"""
import asyncio
from contextlib import nullcontext
from types import SimpleNamespace, MethodType
from unittest.mock import Mock, AsyncMock
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService
from src.A_memorix.core.runtime.services.feedback_correction_service import MemoryFeedbackCorrectionService
from src.A_memorix.core.utils.relation_write_service import RelationWriteService

@pytest.mark.parametrize('score',[0,0.5,1])
def test_ingest_confidence_persisted(tmp_path,score):
    store=MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        writer=SimpleNamespace(metadata_store=store,graph_store=SimpleNamespace(batch_update=nullcontext,add_edges=Mock()))
        writer.upsert_relation_with_vector=MethodType(RelationWriteService.upsert_relation_with_vector,writer)
        service=SimpleNamespace(metadata_store=store,relation_write_service=writer,relation_vectors_enabled=False,
            _is_chat_filtered=Mock(return_value=False),initialize=AsyncMock(),
            _write_paragraph_vector_or_enqueue=AsyncMock(return_value={}),_persist=Mock())
        normalized=MemoryFeedbackCorrectionService._normalize_feedback_decision({'decision':'correct','confidence':1,
            'corrected_relations':[{'subject':'合成甲','predicate':'喜欢','object':'合成乙','confidence':score}]},hit_hashes=[])
        result=asyncio.run(MemoryIngestService.ingest_text(service,external_id='synthetic-score',source_type='feedback',
            text='合成甲喜欢合成乙',chat_id='synthetic-session',relations=normalized['corrected_relations']))
        assert len(result['stored_ids'])==2
        row=store.get_relation(result['stored_ids'][1])
        assert row is not None and row['confidence']==float(score)
    finally:
        store.close()

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

@pytest.mark.parametrize('fault',['inactive','unlinked','deleted_paragraph','valid'])
def test_real_sqlite_replay_revalidates(tmp_path,fault):
    store=MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        writer=SimpleNamespace(metadata_store=store,graph_store=SimpleNamespace(batch_update=nullcontext,add_edges=Mock()))
        writer.upsert_relation_with_vector=MethodType(RelationWriteService.upsert_relation_with_vector,writer)
        service=SimpleNamespace(metadata_store=store,relation_write_service=writer,relation_vectors_enabled=False,
            _is_chat_filtered=Mock(return_value=False),initialize=AsyncMock(),
            _write_paragraph_vector_or_enqueue=AsyncMock(return_value={}),_persist=Mock(),_chat_source=lambda s:'chat:'+s)
        service.ingest_text=MethodType(MemoryIngestService.ingest_text,service)
        kwargs=dict(query_tool_id='synthetic-replay',session_id='synthetic-session',relation_hashes=['synthetic-old'],
            corrected_relations=[{'subject':'合成甲','predicate':'喜欢','object':'合成乙','confidence':0.5}])
        first=asyncio.run(Feedback._ingest_feedback_relations(service,**kwargs))
        assert first['success'] is True
        paragraph=first['paragraph_hashes'][0]
        relation=first['corrected_relation_hashes'][0]
        if fault=='inactive':
            store.mark_relations_inactive([relation])
        elif fault=='unlinked':
            # 仅对tmp_path测试库注入损坏，不访问生产数据库。
            store._conn.execute('DELETE FROM paragraph_relations WHERE paragraph_hash=? AND relation_hash=?',(paragraph,relation))
            store._conn.commit()
        elif fault=='deleted_paragraph':
            store._conn.execute('UPDATE paragraphs SET is_deleted=1 WHERE hash=?',(paragraph,))
            store._conn.commit()
        store.close()
        store.connect()
        assert store.get_external_memory_ref(first['external_id'])['paragraph_hash']==paragraph
        before=store.get_relation(relation)
        writer.upsert_relation_with_vector=AsyncMock(side_effect=AssertionError('replay must not write'))
        replay=asyncio.run(Feedback._ingest_feedback_relations(service,**kwargs))
        assert replay['success'] is (fault=='valid')
        assert replay['stored_ids']==[] and replay['reason']=='exists'
        if fault!='valid':
            assert replay['error']=='missing_corrected_relations'
            assert replay['corrected_relation_hashes']==[]
        else:
            assert replay['idempotent_replay'] is True
            assert replay['corrected_relation_hashes']==[relation]
        writer.upsert_relation_with_vector.assert_not_called()
        store.close()
        store.connect()
        assert store.get_relation(relation)==before
        assert bool(store.get_paragraph(paragraph)['is_deleted']) is (fault=='deleted_paragraph')
        assert bool(store.get_paragraph_relations(paragraph)) is (fault!='unlinked')
    finally:
        store.close()

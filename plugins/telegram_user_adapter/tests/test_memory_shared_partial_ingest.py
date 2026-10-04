"""共享关系部分写入刻画；真实SQLite，图/向量替身，非修复验收。"""
from contextlib import nullcontext
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock
import asyncio
import json
import os
from pathlib import Path
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService
from src.A_memorix.core.runtime.services.feedback_correction_service import MemoryFeedbackCorrectionService as Feedback
from src.A_memorix.core.utils.relation_write_service import RelationWriteService

@pytest.mark.parametrize('cancelled',[False,True])
def test_characterize_shared_partial_write(tmp_path,cancelled):
    store=MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        original_paragraph=store.add_paragraph('其他来源的合成事实')
        shared=store.add_relation(subject='合成甲',predicate='喜欢',obj='合成乙',confidence=0.9,source_paragraph=original_paragraph,metadata={'origin':'synthetic-other'})
        original_row=store.get_relation(shared)
        writer=SimpleNamespace(metadata_store=store,graph_store=SimpleNamespace(batch_update=nullcontext,add_edges=Mock()))
        calls=[]
        error=asyncio.CancelledError() if cancelled else OSError('synthetic second relation failure')
        async def write(**kwargs):
            calls.append(kwargs)
            if len(calls)==2:
                raise error
            return await RelationWriteService.upsert_relation_with_vector(writer,**kwargs)
        writer.upsert_relation_with_vector=write
        service=SimpleNamespace(metadata_store=store,relation_write_service=writer,relation_vectors_enabled=False,
            _is_chat_filtered=Mock(return_value=False),initialize=AsyncMock(),
            _write_paragraph_vector_or_enqueue=AsyncMock(return_value={}),_persist=Mock(),_chat_source=lambda s:'chat:'+s)
        service.ingest_text=MethodType(MemoryIngestService.ingest_text,service)
        captured={}
        real_ingest=service.ingest_text
        async def capture(**kwargs):
            captured.update(kwargs)
            return await real_ingest(**kwargs)
        service.ingest_text=capture
        rows=[{'subject':'合成甲','predicate':'喜欢','object':obj,'confidence':0.5} for obj in ('合成乙','合成丙')]
        with pytest.raises(type(error)) as caught:
            asyncio.run(Feedback._ingest_feedback_relations(service,query_tool_id='synthetic-partial',session_id='synthetic',relation_hashes=['synthetic-old'],corrected_relations=rows))
        assert caught.value is error
        first=store.compute_relation_hash('合成甲','喜欢','合成乙')
        second=store.compute_relation_hash('合成甲','喜欢','合成丙')
        paragraph=calls[0]['source_paragraph']
        store.close()
        store.connect()
        current=store.get_relation(shared)
        for key in ('confidence','source_paragraph','metadata','subject','predicate','object'):
            assert current[key]==original_row[key]
        assert current['reinforcement_count']>original_row['reinforcement_count']
        assert current['lifecycle_revision']>original_row['lifecycle_revision']
        assert {x['hash'] for x in store.get_paragraph_relations(original_paragraph)}=={shared}
        assert paragraph!=original_paragraph
        evidence={'shared_fact_fields_unchanged':True,'shared_lifecycle_modified_by_failed_ingest':True,'original_source_link_preserved':True,'scope':'Known-defect characterization, not successful recovery; actual ingest and SQLite, mocked graph/vector; no full correction orchestration',
            'cancelled':cancelled,'first_relation_persisted':store.get_relation(first) is not None,
            'second_relation_absent':store.get_relation(second) is None,
            'paragraph_persisted':store.get_paragraph(paragraph) is not None,
            'linked_relation_count':len(store.get_paragraph_relations(paragraph)),
            'external_ref_absent':store.get_external_memory_ref(captured['external_id']) is None}
        assert evidence['first_relation_persisted'] and evidence['second_relation_absent']
        assert evidence['paragraph_persisted'] and evidence['linked_relation_count']==1 and evidence['external_ref_absent']
        # 故障仅在第二次关系调用触发；以完全相同请求重试，观察实际恢复边界。
        request=dict(captured)
        retry=asyncio.run(Feedback._ingest_feedback_relations(service,query_tool_id='synthetic-partial',session_id='synthetic',relation_hashes=['synthetic-old'],corrected_relations=rows))
        assert captured==request
        assert retry['success'] is True
        assert retry['paragraph_hashes']==[paragraph]
        assert retry['corrected_relation_hashes']==[first,second]
        assert {r['hash'] for r in store.get_paragraph_relations(paragraph)}=={first,second}
        assert store.get_external_memory_ref(request['external_id'])['paragraph_hash']==paragraph
        calls_after_retry=len(calls)
        repeated=asyncio.run(Feedback._ingest_feedback_relations(service,query_tool_id='synthetic-partial',session_id='synthetic',relation_hashes=['synthetic-old'],corrected_relations=rows))
        assert len(calls)==calls_after_retry
        # 已成功的相同请求须回读完整关系后返回幂等成功。
        assert repeated['success'] is True and repeated['reason']=='exists'
        assert repeated['corrected_relation_hashes']==[first,second]
        assert repeated['idempotent_replay'] is True
        store.close()
        store.connect()
        assert {r['hash'] for r in store.get_paragraph_relations(paragraph)}=={first,second}
        assert store.get_external_memory_ref(request['external_id'])['paragraph_hash']==paragraph
        current=store.get_relation(shared)
        for key in ('confidence','source_paragraph','metadata','subject','predicate','object'):
            assert current[key]==original_row[key]
        assert current['reinforcement_count']>original_row['reinforcement_count']
        assert current['lifecycle_revision']>original_row['lifecycle_revision']
        assert {x['hash'] for x in store.get_paragraph_relations(original_paragraph)}=={shared}
        evidence.update(retry_completed_relations=True,retry_reused_paragraph=True,
            successful_repeat_writes_no_relations=True,successful_repeat_verified=True)
        export=os.environ.get('MAIBOT_ASSEMBLED_PROMPT_OUTPUT')
        if export:
            p=Path(export)/('assembled-shared-partial-ingest-cancel.json' if cancelled else 'assembled-shared-partial-ingest-error.json')
            p.write_text(json.dumps(evidence));p.chmod(0o600)
    finally:
        store.close()

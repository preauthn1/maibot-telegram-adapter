"""真实反馈任务入队/运行/终态持久化；无纠正证据时不得修改记忆。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services.feedback_correction_service import MemoryFeedbackCorrectionService

@pytest.mark.parametrize('with_hits', [True, False])
def test_no_evidence_task_is_skipped(tmp_path, with_hits):
    store=MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        h=store.add_paragraph('合成人物周三游泳',time_meta={'event_time':100.0})
        original=store.get_paragraph(h)
        task=store.enqueue_feedback_task(query_tool_id='synthetic-no-evidence',session_id='synthetic-session',
            query_timestamp=100.0,due_at=200.0,query_snapshot={'hits':[{'hash':h,'type':'paragraph','content':'合成人物周三游泳'}] if with_hits else []})
        classify=AsyncMock(side_effect=AssertionError('must not classify without evidence'))
        apply=AsyncMock(side_effect=AssertionError('must not apply without evidence'))
        extract=Mock(return_value=[])
        service=SimpleNamespace(metadata_store=store,_extract_feedback_messages=extract,
            _classify_feedback=classify,_apply_feedback_decision=apply)
        asyncio.run(MemoryFeedbackCorrectionService._process_feedback_task(service,task))
        saved=store.get_feedback_task('synthetic-no-evidence')
        assert saved['status']=='skipped'
        assert saved['decision_payload']['reason']==('no_feedback_messages' if with_hits else 'no_hits')
        assert store.get_paragraph(h)==original
        classify.assert_not_awaited()
        apply.assert_not_awaited()
        assert extract.call_count==int(with_hits)
    finally:
        store.close()

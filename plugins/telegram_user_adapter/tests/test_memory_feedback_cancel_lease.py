"""真实SQLite取消/租约恢复；合成时间，不启动后台循环。"""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.storage import metadata_feedback
from src.A_memorix.core.runtime.services.feedback_correction_service import MemoryFeedbackCorrectionService


def test_cancelled_feedback_can_be_reclaimed_after_lease(tmp_path,monkeypatch):
    store=MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        h=store.add_paragraph('合成原记忆',time_meta={'event_time':100.0})
        original=store.get_paragraph(h)
        task=store.enqueue_feedback_task(query_tool_id='synthetic-cancel',session_id='synthetic-session',query_timestamp=100.0,due_at=200.0,query_snapshot={'hits':[{'type':'paragraph','hash':h}]})
        clock=[1000.0]
        class Clock:
            @staticmethod
            def now():
                return datetime.fromtimestamp(clock[0])
        monkeypatch.setattr(metadata_feedback,'datetime',Clock)
        classify=AsyncMock()
        apply=AsyncMock()
        service=SimpleNamespace(metadata_store=store,_extract_feedback_messages=Mock(side_effect=asyncio.CancelledError()),_classify_feedback=classify,_apply_feedback_decision=apply)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(MemoryFeedbackCorrectionService._process_feedback_task(service,task))
        saved=store.get_feedback_task('synthetic-cancel')
        assert saved['status']=='running' and saved['attempt_count']==1
        assert store.fetch_due_feedback_tasks(now=1299.0)==[]
        assert store.mark_feedback_task_running(task['id']) is None
        clock[0]=1301.0
        due=store.fetch_due_feedback_tasks(now=clock[0])
        assert [row['id'] for row in due]==[task['id']]
        service._extract_feedback_messages=Mock(return_value=[])
        asyncio.run(MemoryFeedbackCorrectionService._process_feedback_task(service,due[0]))
        saved=store.get_feedback_task('synthetic-cancel')
        assert saved['status']=='skipped' and saved['attempt_count']==2
        assert saved['decision_payload']['reason']=='no_feedback_messages'
        assert store.get_paragraph(h)==original
        classify.assert_not_awaited()
        apply.assert_not_awaited()
    finally:
        store.close()

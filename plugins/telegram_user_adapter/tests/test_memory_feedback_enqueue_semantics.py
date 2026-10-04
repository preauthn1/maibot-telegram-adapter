"""真实临时SQLite反馈入队不等于记忆已修改；不运行后台纠错模型。"""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services import feedback_correction_service as module


def test_feedback_queued_is_not_memory_updated(tmp_path, monkeypatch):
    store=MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        paragraph=store.add_paragraph('合成人物每周三游泳',time_meta={'event_time':100.0})
        before=store.get_paragraph(paragraph)
        monkeypatch.setattr(module,'feedback_cfg_enabled',lambda:True)
        monkeypatch.setattr(module,'feedback_cfg_window_hours',lambda:1.0)
        service=SimpleNamespace(metadata_store=store)
        result=asyncio.run(module.MemoryFeedbackCorrectionService.enqueue_feedback_task(
            service,query_tool_id='synthetic-query',session_id='synthetic-session',
            query_timestamp=datetime(2026,1,1,12),structured_content={'hits':[{'type':'paragraph','hash':paragraph,'content':'合成人物每周三游泳'}]}))
        assert result['success'] is True and result['queued'] is True
        assert result['due_at']=='2026-01-01T13:00:00'
        assert isinstance(result['task'],dict)
        assert store.get_paragraph(paragraph)==before
    finally:
        store.close()

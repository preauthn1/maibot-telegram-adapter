"""真实SQLite任务错误回读；消息提取故障为合成替身。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services import feedback_correction_service as module


def test_feedback_error_is_private_and_terminal(tmp_path,monkeypatch):
    store=MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        h=store.add_paragraph('合成记忆不应变更',time_meta={'event_time':100.0})
        before=store.get_paragraph(h)
        task=store.enqueue_feedback_task(query_tool_id='synthetic-error',session_id='synthetic',query_timestamp=100.0,due_at=200.0,query_snapshot={'hits':[{'hash':h,'type':'paragraph'}]})
        logger=Mock()
        monkeypatch.setattr(module,'logger',logger)
        classify=AsyncMock()
        apply=AsyncMock()
        service=SimpleNamespace(metadata_store=store,_extract_feedback_messages=Mock(side_effect=OSError('SYNTHETIC_SECRET_CONNECTION')), _classify_feedback=classify,_apply_feedback_decision=apply)
        asyncio.run(module.MemoryFeedbackCorrectionService._process_feedback_task(service,task))
        saved=store.get_feedback_task('synthetic-error')
        assert saved['status']=='error'
        assert 'OSError' in saved['last_error']
        assert 'SYNTHETIC_SECRET_CONNECTION' not in str(saved)
        assert 'SYNTHETIC_SECRET_CONNECTION' not in str(logger.mock_calls)
        assert not logger.warning.call_args.kwargs.get('exc_info')
        assert 'SYNTHETIC_SECRET_CONNECTION' not in '\n'.join(store._conn.iterdump())
        assert store.get_paragraph(h)==before
        classify.assert_not_awaited()
        apply.assert_not_awaited()
    finally:
        store.close()

"""近期历史恢复失败不将数据库异常原文写入日志。"""
import asyncio
from unittest.mock import Mock
from src.maisaka import runtime as module


def test_restore_error_does_not_log_private_exception(monkeypatch):
    runtime=object.__new__(module.MaisakaHeartFlowChatting)
    runtime.session_id='synthetic'
    runtime.log_prefix='synthetic'
    runtime._chat_history=[]
    runtime.message_cache=[]
    monkeypatch.setattr(runtime,'_get_context_restore_limit',lambda:20)
    monkeypatch.setattr(module,'find_messages',Mock(side_effect=OSError('PRIVATE_SQL_ARGUMENT')))
    logger=Mock()
    monkeypatch.setattr(module,'logger',logger)
    asyncio.run(runtime._restore_recent_context_from_db())
    logger.warning.assert_called_once()
    assert 'PRIVATE_SQL_ARGUMENT' not in str(logger.mock_calls)
    assert 'OSError' in str(logger.mock_calls)
    assert not logger.warning.call_args.kwargs.get('exc_info')
    assert runtime._chat_history == [] and runtime.message_cache == []

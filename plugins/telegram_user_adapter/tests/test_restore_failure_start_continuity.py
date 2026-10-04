"""恢复失败时 start 保持原有降级语义，并进入运行状态。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from src.maisaka import runtime as module


def test_start_continues_after_restore_failure_without_logging_secret(monkeypatch):
    runtime=object.__new__(module.MaisakaHeartFlowChatting)
    runtime._running=False
    runtime.session_id='synthetic'
    runtime.session_name='合成会话'
    runtime.log_prefix='synthetic'
    runtime._reply_effect_tracker=SimpleNamespace(start=AsyncMock())
    runtime._agent_state=SimpleNamespace()
    runtime._ensure_background_tasks_running=Mock()
    runtime._schedule_message_turn=Mock()
    runtime._update_stage_status=Mock()
    monkeypatch.setattr(module,'global_config',SimpleNamespace(
        mcp=SimpleNamespace(enable=False),
        debug=SimpleNamespace(enable_reply_effect_tracking=False)))
    runtime._chat_history=[]
    runtime.message_cache=[]
    monkeypatch.setattr(runtime,'_get_context_restore_limit',lambda:20)
    # 在数据库端注入失败，保留真实恢复方法的降级处理。
    monkeypatch.setattr(module,'find_messages',Mock(side_effect=OSError('PRIVATE_DB_DETAIL')))
    log=Mock();monkeypatch.setattr(module,'logger',log)
    asyncio.run(runtime.start())
    assert runtime._running is True
    runtime._ensure_background_tasks_running.assert_called_once()
    runtime._schedule_message_turn.assert_called_once()
    assert 'PRIVATE_DB_DETAIL' not in str(log.mock_calls)
    assert runtime._context_restore_failed is True
    runtime._update_stage_status.assert_called_once_with('降级', '近期历史恢复失败；当前上下文不完整')
    monkeypatch.setattr(module, 'find_messages', Mock(return_value=[]))
    asyncio.run(runtime._restore_recent_context_from_db())
    assert runtime._context_restore_failed is False

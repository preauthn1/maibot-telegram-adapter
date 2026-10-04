"""实际恢复入口的清空边界测试；不连接数据库或平台。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from src.maisaka import runtime as module
from src.maisaka.context.clear_context import CLEAR_CONTEXT_MARKER_KEY


def test_restore_only_builds_messages_after_last_executed_clear(monkeypatch):
    def message(label, command=False, cleared=False, notify=False):
        return SimpleNamespace(label=label, is_command=command, is_notify=notify,
            message_info=SimpleNamespace(additional_config={CLEAR_CONTEXT_MARKER_KEY: cleared}))
    rows=[message('old'), message('clear1',True,True), message('middle'),
          message('clear2',True,True), message('command',True),
          message('notification',notify=True), message('kept')]
    runtime=object.__new__(module.MaisakaHeartFlowChatting)
    runtime.session_id='synthetic-clear'
    runtime.log_prefix='synthetic'
    runtime._chat_history=[]
    runtime.message_cache=[]
    runtime.chat_stream=SimpleNamespace(session_id='synthetic-clear',is_group_session=True)
    monkeypatch.setattr(runtime,'_get_context_restore_limit',lambda: 30)
    monkeypatch.setattr(runtime,'_resolve_restored_message_source_kind',lambda m: 'user')
    monkeypatch.setattr(runtime,'_build_context_restore_reference_message',lambda *a,**kw: None)
    monkeypatch.setattr(module,'find_messages',lambda **kw: rows)
    monkeypatch.setattr(module,'logger',SimpleNamespace(info=lambda *a,**k:None))
    builder=AsyncMock(return_value='restored-kept')
    runtime._reasoning_engine=SimpleNamespace(_build_history_message=builder)
    asyncio.run(runtime._restore_recent_context_from_db())
    builder.assert_awaited_once_with(rows[-1],source_kind='user')
    assert runtime._chat_history==['restored-kept']
    assert runtime.message_cache==[rows[-1]]
    assert runtime._last_processed_index==1

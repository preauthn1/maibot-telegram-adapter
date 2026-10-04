"""首次检索抛出异常时，不向日志或工具结果泄漏后端正文。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from src.maisaka.builtin_tool import query_memory as module
from src.maisaka.builtin_tool.context import BuiltinToolRuntimeContext


def test_primary_exception_privacy(monkeypatch):
    search=AsyncMock(side_effect=OSError('SYNTHETIC_PRIVATE_BACKEND_DETAIL'))
    logger=Mock()
    monkeypatch.setattr(module.memory_service,'search',search)
    monkeypatch.setattr(module,'logger',logger)
    monkeypatch.setattr(module,'_resolve_person_id',lambda **kw:('',''))
    runtime=SimpleNamespace(session_id='synthetic',log_prefix='synthetic',chat_stream=SimpleNamespace(platform='telegram',user_id='17',group_id='group'))
    ctx=BuiltinToolRuntimeContext(SimpleNamespace(),runtime)
    invocation=SimpleNamespace(tool_name='query_memory',arguments={'query':'合成查询'})
    result=asyncio.run(module.handle_tool(ctx,invocation))
    assert search.await_count==1
    assert result.success is False and '失败' in result.error_message
    assert 'SYNTHETIC_PRIVATE_BACKEND_DETAIL' not in str(result)
    assert 'SYNTHETIC_PRIVATE_BACKEND_DETAIL' not in str(logger.mock_calls)
    logger.exception.assert_not_called()
    logger.warning.assert_called_once()
    assert 'OSError' in str(logger.warning.call_args)
    assert not result.metadata.get('replyer_memory_reference')

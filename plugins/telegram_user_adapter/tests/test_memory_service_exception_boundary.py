"""真实服务search→工具入口异常传播；仅host调用为合成替身。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
import src.services.memory_service as service_module
from src.maisaka.builtin_tool import query_memory as tool
from src.maisaka.builtin_tool.context import BuiltinToolRuntimeContext

@pytest.mark.parametrize('cancel', [False, True])
def test_service_exception_boundary(monkeypatch,cancel):
    error=asyncio.CancelledError() if cancel else OSError('SYNTHETIC_PRIVATE_SERVICE_DETAIL')
    invoke=AsyncMock(side_effect=error)
    log=Mock()
    monkeypatch.setattr(tool.memory_service,'_invoke',invoke)
    monkeypatch.setattr(service_module,'logger',log)
    monkeypatch.setattr(tool,'_resolve_person_id',lambda **kw:('',''))
    runtime=SimpleNamespace(session_id='synthetic',log_prefix='synthetic',chat_stream=SimpleNamespace(platform='telegram',user_id='17',group_id='group'))
    ctx=BuiltinToolRuntimeContext(SimpleNamespace(),runtime)
    invocation=SimpleNamespace(tool_name='query_memory',arguments={'query':'合成查询'})
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(tool.handle_tool(ctx,invocation))
        log.warning.assert_not_called()
    else:
        result=asyncio.run(tool.handle_tool(ctx,invocation))
        assert result.success is False
        assert '失败' in result.error_message
        assert 'SYNTHETIC_PRIVATE_SERVICE_DETAIL' not in str(result)
        assert 'SYNTHETIC_PRIVATE_SERVICE_DETAIL' not in str(log.mock_calls)
        log.warning.assert_called_once()
        assert 'OSError' in str(log.warning.call_args)
        assert not result.metadata.get('replyer_memory_reference')
    assert invoke.await_count==1

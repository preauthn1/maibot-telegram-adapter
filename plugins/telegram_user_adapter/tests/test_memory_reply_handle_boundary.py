"""真实reply工具入口的记忆参数路由，生成边界终止，绝不发送。"""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.maisaka.builtin_tool import reply as module
from src.maisaka.context.messages import ToolResultMessage

class ReachedGenerator(BaseException):
    pass

@pytest.mark.parametrize('turn', ['current', 'other', ''])
def test_handle_routes_only_current_memory(monkeypatch, turn):
    reference='【长期记忆检索结果-内部参考】\n  合成正文\n'
    def memory(t, success=True, name='query_memory'):
        return ToolResultMessage(content='工具正文', timestamp=datetime(2026,1,1),tool_call_id='call',
            logical_turn_id=t,tool_name=name,success=success,metadata={'replyer_memory_reference':reference})
    history=[memory('current'),memory('old'),memory('current',False),memory('current',name='other_tool')]
    target=SimpleNamespace(platform='telegram',message_info=SimpleNamespace(user_info=SimpleNamespace(user_id='17')))
    runtime=SimpleNamespace(_chat_history=history,session_id='synthetic',chat_stream=SimpleNamespace(),
        find_source_message_by_id=lambda _:target,_update_stage_status=Mock(),log_prefix='synthetic')
    ctx=SimpleNamespace(runtime=runtime,engine=SimpleNamespace(_active_logical_turn_id=turn))
    captured={}
    async def generate(**kwargs):
        captured.update(kwargs)
        raise ReachedGenerator()
    monkeypatch.setattr(module.replyer_manager,'get_replyer',lambda **kw:SimpleNamespace(generate_reply_with_context=generate))
    monkeypatch.setattr(module,'is_bot_self',lambda *a:False)
    monkeypatch.setattr(module,'_find_recent_reply_to_target',lambda *a:'')
    invocation=SimpleNamespace(arguments={'msg_id':'target'},reasoning='合成理由',tool_name='reply')
    with pytest.raises(ReachedGenerator):
        asyncio.run(module.handle_tool(ctx,invocation))
    assert captured['memory_references']==((reference,) if turn=='current' else ())
    assert captured['stream_id']=='synthetic'
    assert captured['reply_message'] is target
    assert captured['chat_history']==history and captured['chat_history'] is not history
    assert runtime._chat_history==history

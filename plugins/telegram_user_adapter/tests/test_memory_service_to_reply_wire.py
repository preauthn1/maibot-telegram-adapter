"""跨组件组合：底层响应/核心提示替身；其余记忆传递路径真实执行。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.services.memory_service import memory_service
from src.maisaka.builtin_tool import query_memory
from src.maisaka.builtin_tool.context import BuiltinToolRuntimeContext
from src.maisaka.reasoning_engine import MaisakaReasoningEngine
from src.core.tooling import ToolInvocation
from src.llm_models.payload_content.tool_option import ToolCall
from src.maisaka.context.reply_memory import collect_reply_memory_references
from src.maisaka.context.memory_reference_policy import MEMORY_REFERENCE_POLICY
from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator
from src.llm_models.model_client.openai_client import _convert_messages

@pytest.mark.parametrize('state', ['success','failed','filtered'])
def test_service_to_reply_wire(monkeypatch,state):
    body='  合成人物喜欢栀子花\n\t不是玫瑰\n'
    payload={'success':state!='failed','filtered':state=='filtered','hits':[{'content':body}]}
    if state=='failed':
        payload['error']='SYNTHETIC_PRIVATE_ERROR'
    invoke=AsyncMock(return_value=payload)
    monkeypatch.setattr(memory_service,'_invoke',invoke)
    monkeypatch.setattr(query_memory,'_resolve_person_id',lambda **kw:('',''))
    runtime=SimpleNamespace(_chat_history=[],session_id='synthetic-session',log_prefix='synthetic',
        chat_stream=SimpleNamespace(platform='telegram',user_id='17',group_id='synthetic-group'))
    engine=object.__new__(MaisakaReasoningEngine)
    engine._runtime=runtime
    engine._active_logical_turn_id='synthetic-turn'
    result=asyncio.run(query_memory.handle_tool(BuiltinToolRuntimeContext(engine,runtime),
        ToolInvocation(tool_name='query_memory',arguments={'query':'合成花卉'})))
    engine._append_tool_execution_result(ToolCall(call_id='synthetic-call',func_name='query_memory'),result)
    assert len(runtime._chat_history)==1
    history=runtime._chat_history
    refs=tuple(collect_reply_memory_references(history,'synthetic-turn'))
    generator=object.__new__(BaseMaisakaReplyGenerator)
    monkeypatch.setattr(generator,'_build_keyword_reaction_prompt',lambda **kw:'')
    monkeypatch.setattr(generator,'_build_system_prompt',lambda **kw:'合成核心系统')
    monkeypatch.setattr(generator,'_build_final_user_message',lambda **kw:'当前问题：喜欢什么花？')
    monkeypatch.setattr(generator,'_select_temporary_reply_style',lambda:'')
    wire=_convert_messages(generator._build_request_messages(history,None,'',memory_references=refs))
    assert wire[-1]['content']=='当前问题：喜欢什么花？'
    assert invoke.await_count==1
    assert invoke.await_args.args[1]['chat_id']=='synthetic-session'
    if state=='success':
        assert history[0].content=='1. '+body
        assert len(refs)==1 and body in refs[0]
        assert wire[1]=={'role':'system','content':MEMORY_REFERENCE_POLICY}
        assert wire[2]=={'role':'user','content':refs[0]}
        assert len(wire)==4
    else:
        assert not refs
        assert len(wire)==2
        assert body not in str(wire)
        assert 'SYNTHETIC_PRIVATE_ERROR' not in str(history)
        assert history[0].success is (state=='filtered')
    assert collect_reply_memory_references(history,'other-turn')==[]

"""合成记忆经过真实正文构造、历史写入及SDK转换，非完整Planner执行。"""
from types import SimpleNamespace
import pytest
from src.services.memory_service import MemorySearchResult, MemoryHit
from src.maisaka.builtin_tool.query_memory import _build_success_content
from src.maisaka.reasoning_engine import MaisakaReasoningEngine
from src.core.tooling import ToolExecutionResult
from src.llm_models.payload_content.tool_option import ToolCall
from src.llm_models.model_client.openai_client import _convert_messages

@pytest.mark.parametrize('body', ['  条件：\n\t下雨不出门\n', '甲\r\n乙  ', '```python\nif rain:\n    stay_home()\n```\n'])
def test_memory_body_survives_history_and_wire(body):
    engine=object.__new__(MaisakaReasoningEngine)
    engine._runtime=SimpleNamespace(_chat_history=[])
    engine._active_logical_turn_id='synthetic-turn'
    content=_build_success_content(MemorySearchResult(hits=[MemoryHit(content=body)]),limit=1)
    result=ToolExecutionResult(tool_name='query_memory',success=True,content=content)
    engine._append_tool_execution_result(ToolCall(call_id='synthetic-call',func_name='query_memory'),result)
    history=engine._runtime._chat_history
    assert len(history)==1
    assert history[0].content=='1. '+body
    wire=_convert_messages([history[0].to_context_item()])
    assert wire==[{'role':'tool','tool_call_id':'synthetic-call','content':'1. '+body}]


def test_blank_content_still_falls_back_to_error():
    result=ToolExecutionResult(tool_name='synthetic',success=False,content=' \n ',error_message='合成失败')
    assert result.get_history_content()=='合成失败'

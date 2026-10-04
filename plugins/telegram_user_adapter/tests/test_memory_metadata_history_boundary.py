"""真实工具历史写回保留记忆参考及逻辑轮次，不启动运行时。"""
from types import SimpleNamespace
from unittest.mock import Mock
from src.maisaka.reasoning_engine import MaisakaReasoningEngine
from src.core.tooling import ToolExecutionResult
from src.llm_models.payload_content.tool_option import ToolCall
from src.maisaka.context.messages import ToolResultMessage
from src.maisaka.builtin_tool.query_memory import _build_replyer_memory_reference


def test_memory_metadata_survives_actual_history_append(monkeypatch):
    engine=object.__new__(MaisakaReasoningEngine)
    engine._runtime=SimpleNamespace(_chat_history=[])
    engine._active_logical_turn_id='synthetic-turn'
    monkeypatch.setattr(engine,'_build_tool_result_history_content',lambda *a:'合成工具结果')
    monkeypatch.setattr(engine,'_append_tool_result_media_messages',Mock())
    monkeypatch.setattr(engine,'_append_tool_post_history_messages',Mock())
    body='\n  条件：\n\t下雨不出门\n'
    reference=_build_replyer_memory_reference({'fallback_applied':True,'fallback_reason':'person_filter_miss','hits':[{'content':body}]})
    result=ToolExecutionResult(tool_name='query_memory',success=True,metadata={'replyer_memory_reference':reference})
    engine._append_tool_execution_result(ToolCall(call_id='synthetic-call',func_name='query_memory'),result)
    assert len(engine._runtime._chat_history)==1
    message=engine._runtime._chat_history[0]
    assert isinstance(message,ToolResultMessage)
    assert message.logical_turn_id=='synthetic-turn' and message.tool_name=='query_memory' and message.success
    assert message.metadata['replyer_memory_reference']==reference
    assert body in reference
    result.metadata['replyer_memory_reference']='mutated'
    assert message.metadata['replyer_memory_reference']==reference

"""合成媒体元数据，不下载或解码媒体；测试真实正文与索引拼接。"""
from types import SimpleNamespace
import pytest
from src.core.tooling import ToolExecutionResult
from src.llm_models.payload_content.tool_option import ToolCall
from src.maisaka.reasoning_engine import MaisakaReasoningEngine

@pytest.mark.parametrize('body', ['  条件：\n\t不要删除\n', '甲\r\n乙  ', '```python\n  pass\n```\n'])
def test_media_index_preserves_body(body):
    engine=object.__new__(MaisakaReasoningEngine)
    item=SimpleNamespace(content_type='image',mime_type='image/png',name='合成"<&图',metadata={})
    result=ToolExecutionResult(tool_name='synthetic',success=True,content=body,content_items=[item])
    call=ToolCall(call_id='synthetic-call',func_name='synthetic')
    output=engine._build_tool_result_history_content(call,result)
    prefix,separator,media=output.partition('\n\n<tool_result_media_list>')
    assert separator
    assert prefix==body
    assert 'msg_id="tool_result:synthetic-call:1"' in media
    assert '合成&quot;&lt;&amp;图' in media
    assert output.endswith('</tool_result_media_list>')
    assert result.content==body

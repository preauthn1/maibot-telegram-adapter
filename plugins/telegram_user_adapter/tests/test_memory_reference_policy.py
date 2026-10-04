"""实际请求装配中，只有非空记忆才启用独立来源约束。"""
import pytest
from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator
from src.llm_models.model_client.openai_client import _convert_messages
from src.maisaka.context.memory_reference_policy import MEMORY_REFERENCE_POLICY

@pytest.mark.parametrize('references', [(), ('', '  '), ('合成记忆\n  正文\n',), ('甲', '乙')])
def test_memory_policy_request_boundary(monkeypatch, references):
    generator=object.__new__(BaseMaisakaReplyGenerator)
    monkeypatch.setattr(generator, '_build_keyword_reaction_prompt', lambda **kw: '')
    monkeypatch.setattr(generator, '_build_system_prompt', lambda **kw: '合成人设')
    monkeypatch.setattr(generator, '_build_final_user_message', lambda **kw: '当前任务')
    monkeypatch.setattr(generator, '_select_temporary_reply_style', lambda: '')
    wire=_convert_messages(generator._build_request_messages([], None, '', memory_references=references))
    valid=[v for v in references if v.strip()]
    expected=[{'role':'system','content':'合成人设'}]
    if valid:
        expected.append({'role':'system','content':MEMORY_REFERENCE_POLICY})
    expected.extend({'role':'user','content':v} for v in valid)
    expected.append({'role':'user','content':'当前任务'})
    assert wire==expected

"""记录当前记忆metadata直达回复器的缺口；不是期望最终产品行为。"""
from datetime import datetime
from src.maisaka.context.messages import ToolResultMessage
from src.maisaka.builtin_tool.query_memory import _build_replyer_memory_reference
from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator
from src.llm_models.model_client.openai_client import _convert_messages


def test_current_tool_metadata_is_not_forwarded_implicitly(monkeypatch):
    reference = _build_replyer_memory_reference({'fallback_applied':True,
        'fallback_reason':'person_filter_miss','hits':[{'content':'记忆探针：豆包是兔子。'}]})
    history = [ToolResultMessage(content='工具探针', timestamp=datetime(2026,1,1),
        tool_call_id='synthetic-call',logical_turn_id='synthetic-turn',tool_name='query_memory',
        metadata={'replyer_memory_reference':reference})]
    generator=object.__new__(BaseMaisakaReplyGenerator)
    monkeypatch.setattr(generator,'_build_keyword_reaction_prompt',lambda **kw:'')
    monkeypatch.setattr(generator,'_build_system_prompt',lambda **kw:'合成系统')
    monkeypatch.setattr(generator,'_build_final_user_message',lambda **kw:'小林养什么？')
    monkeypatch.setattr(generator,'_select_temporary_reply_style',lambda:'')
    wire=_convert_messages(generator._build_request_messages(history,None,''))
    assert wire == [{'role':'system','content':'合成系统'},{'role':'user','content':'小林养什么？'}]
    assert history[0].metadata['replyer_memory_reference']==reference
    from src.maisaka.context.reply_memory import collect_reply_memory_references
    refs=tuple(collect_reply_memory_references(history,'synthetic-turn'))
    forwarded=_convert_messages(generator._build_request_messages(history,None,'',memory_references=refs))
    from src.maisaka.context.memory_reference_policy import MEMORY_REFERENCE_POLICY
    assert forwarded == [wire[0], {'role':'system','content':MEMORY_REFERENCE_POLICY}, {'role':'user','content':reference}, wire[-1]]
    assert '人物定向检索未命中' in forwarded[2]['content']
    assert '工具探针' not in str(forwarded)
    stale=tuple(collect_reply_memory_references(history,'different-turn'))
    assert _convert_messages(generator._build_request_messages(history,None,'',memory_references=stale))==wire

"""真实窗口筛选的能力边界，不把全量历史实呼误称运行时记忆。"""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import pytest
from src.maisaka.chat_loop_service import MaisakaChatLoopService
from src.maisaka.context.messages import SessionBackedMessage
from src.common.data_models.message_component_data_model import MessageSequence

@pytest.mark.parametrize('limit,expected_count,retained', [(10,20,False),(20,40,False),(30,60,False),(40,62,True)])
def test_distant_correction_retention_window(limit,expected_count,retained):
    texts=['更正：豆包是兔子，不是猫，主人仍是小林。'] + [f'无关合成消息{i}' for i in range(60)] + ['小林的宠物是什么？']
    history=[]
    for i,text in enumerate(texts):
        seq=MessageSequence([]);seq.text(text)
        history.append(SessionBackedMessage(raw_message=seq,visible_text=text,timestamp=datetime(2026,1,1)+timedelta(seconds=i),message_id=f'synthetic-{i}'))
    selected,reason=MaisakaChatLoopService.select_llm_context_messages(history,request_kind='expression_selector',max_context_size=limit,is_group_chat=True,enable_visual_message=False)
    assert len(selected)==expected_count
    assert any(m is history[0] for m in selected) is retained
    assert selected[-1] is history[-1]
    assert [m.message_id for m in selected]==[m.message_id for m in history[-expected_count:]]
    assert len(history)==62
    export=os.environ.get('MAIBOT_ASSEMBLED_PROMPT_OUTPUT')
    if export:
        path=Path(export)/f'assembled-window-audit-{limit}.json'
        path.write_text(json.dumps({'scope':'real context selector; synthetic user-only history; no persistent memory retrieval or LLM','configured_limit':limit,'input_count':len(history),'selected_count':len(selected),'correction_retained':retained,'selection_reason':reason},ensure_ascii=False))
        path.chmod(0o600)

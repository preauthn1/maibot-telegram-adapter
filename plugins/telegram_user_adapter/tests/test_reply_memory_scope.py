from datetime import datetime
import pytest
from src.maisaka.context.messages import ToolResultMessage
from src.maisaka.context.reply_memory import collect_reply_memory_references


def item(turn='current', name='query_memory', success=True, reference='\n  合成记忆\n'):
    return ToolResultMessage(content='不可自动注入的工具正文',timestamp=datetime(2026,1,1),
        tool_call_id='synthetic',logical_turn_id=turn,tool_name=name,success=success,
        metadata={'replyer_memory_reference':reference})


def test_collect_only_current_successful_memory_and_preserve_whitespace():
    rows=[item(turn='old'),item(name='other_tool'),item(success=False),item(),item(),item(reference='第二条')]
    assert collect_reply_memory_references(rows,'current')==['\n  合成记忆\n','第二条']
    assert len(rows)==6

@pytest.mark.parametrize('turn', ['', ' ', None])
def test_no_inferred_turn(turn):
    assert collect_reply_memory_references([item()],turn)==[]

@pytest.mark.parametrize('reference', [None, [], {}, 12, '', ' \n'])
def test_invalid_metadata_is_not_stringified(reference):
    assert collect_reply_memory_references([item(reference=reference)],'current')==[]

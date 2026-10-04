"""实际 Hook 反序列化拒绝输入消息冒充模型输出。"""
import pytest
from src.plugin_runtime.hook_payloads import deserialize_prompt_items
from src.llm_models.request_snapshot import serialize_context_item_snapshot
from src.llm_models.payload_content.context_item import ContextItemBuilder, RoleType
from src.llm_models.payload_content.context_protocol import ContextProtocolMode


@pytest.mark.parametrize('role', [RoleType.User, RoleType.System])
def test_request_message_rejected_as_output(role):
    item = ContextItemBuilder().set_role(role).add_text_content('合成内容').build()
    with pytest.raises(ValueError):
        deserialize_prompt_items([serialize_context_item_snapshot(item)], mode=ContextProtocolMode.MODEL_OUTPUT)


def test_tool_result_rejected_as_model_output():
    from src.llm_models.payload_content.context_item import ContextItemMeta, FunctionCallOutputItem
    item = FunctionCallOutputItem(
        meta=ContextItemMeta.create(logical_turn_id='synthetic-turn'),
        call_id='synthetic-call', output='合成工具结果', tool_name='synthetic_tool')
    with pytest.raises(ValueError, match='非模型输出 Item'):
        deserialize_prompt_items([serialize_context_item_snapshot(item)],
                                 mode=ContextProtocolMode.MODEL_OUTPUT)


def test_assistant_output_roundtrip():
    item = ContextItemBuilder().set_role(RoleType.Assistant).add_text_content('完整回答').build()
    result = deserialize_prompt_items([serialize_context_item_snapshot(item)], mode=ContextProtocolMode.MODEL_OUTPUT, original_items=[item])
    assert result[0] is item

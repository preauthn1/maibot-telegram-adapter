"""代码中的标签是内容，不应被当成工具标记删除。"""
from plugins.telegram_user_adapter.command_guard import strip_tool_markup
import pytest


@pytest.mark.parametrize('text', [
    '```html\n<div>你好</div>\n```',
    '使用 `<item/>` 表示空元素。',
    '```xml\n<tool_call>这是示例</tool_call>\n```',
])
def test_code_is_preserved(text):
    assert strip_tool_markup(text) == text


def test_markup_outside_code_still_removed():
    assert strip_tool_markup('看 `<div>` </tool_call>') == '看 `<div>`'

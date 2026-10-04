"""合法结构化输出不应因 URL 被命令修饰改写。"""
import pytest
from plugins.telegram_user_adapter.command_guard import protect_commands, format_command_segments, strip_tool_markup


@pytest.mark.parametrize('text', [
    '{"url":"https://example.com","label":"v1中文"}',
    '{"html":"<div>内容</div>","example":"<tool_call>demo</tool_call>"}',
    '["<item/>", "[TOOL_CALLS]"]',
    '[{"command":"curl https://example.com","label":"v2中文"}]',
])
def test_json_survives_command_pipeline(text):
    protected = protect_commands(strip_tool_markup(text))
    assert protected == text
    assert format_command_segments(protected) == (text, None)


def test_shell_still_formatted():
    assert format_command_segments('curl https://example.com') == ('`curl https://example.com`', 'md')

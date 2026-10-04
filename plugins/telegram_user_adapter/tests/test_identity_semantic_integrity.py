"""身份提示不应损坏技术回答或要求虚构身份。"""
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.chat.utils.identity_guard import guard_identity, build_identity_prompt_block

@pytest.mark.parametrize('text', ['这个 API 返回 401，先检查 token。', 'Claude 和 Qwen 的参数不一样。', '我是自动助手，不确定具体模型版本。', '不知道，暂时没有验证。'])
def test_identity_guard_preserves_response(text):
    result = guard_identity(text)
    assert result.text == text
    assert not result.used_deflection
    assert not result.triggered


def test_identity_prompt_separates_role_and_facts():
    prompt = build_identity_prompt_block('测试角色')
    assert '一个真实的人' not in prompt
    assert '岔开话题' not in prompt
    assert '自动助手' in prompt
    assert '不要编造' in prompt

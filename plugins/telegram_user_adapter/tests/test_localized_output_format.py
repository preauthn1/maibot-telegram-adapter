"""系统级输出约束在三种语言中均允许用户要求的格式。"""
import pytest
from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator as Generator


@pytest.mark.parametrize('locale, marker', [('zh-cn', '保留用户明确要求'), ('en-us', 'Preserve punctuation'), ('ja-jp', '形式は保持')])
def test_localized_format_boundary(monkeypatch, locale, marker):
    monkeypatch.setattr(Generator, '_get_prompt_locale', staticmethod(lambda: locale))
    text = Generator._build_replyer_output_instruction()
    assert marker in text
    assert 'JSON' in text

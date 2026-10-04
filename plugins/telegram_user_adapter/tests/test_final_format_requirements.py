"""默认口语提示不应禁止用户明确要求的结构化格式。"""
import pytest
from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator


@pytest.mark.parametrize('requirement', ['只输出 JSON：{"ok":true}', '原样保留 (a+b)*c', '只输出代码，不加解释'])
def test_final_message_respects_requested_format(monkeypatch, requirement):
    generator = object.__new__(BaseMaisakaReplyGenerator)
    monkeypatch.setattr(generator, '_build_target_message_block', lambda _: '')
    monkeypatch.setattr(generator, '_build_reply_attachment_prompt', lambda **kw: '')
    text = generator._build_final_user_message([], None, reply_requirements=requirement)
    assert text.count(requirement) == 1
    assert '不要输出多余说明、括号' not in text
    assert '必须保留并遵循该格式' in text

"""字节快照仍应保留文本读取的通用换行语义。"""
import pytest
from src.chat.utils import scene_context as module


@pytest.mark.parametrize('newline', [b'\n', b'\r\n', b'\r'])
def test_profile_newline_compatibility(tmp_path, monkeypatch, newline):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, '_style_cache', {})
    monkeypatch.setattr(module, '_style_cache_at', 0.0)
    monkeypatch.setattr(module, '_style_signature', ())
    path = tmp_path / 'data/plugins/a/chats/-1/SKILL.md'
    path.parent.mkdir(parents=True)
    content = newline.join([b'---', b'style_enabled: true', b'style_max_chars: 80',
                            b'max_emoji: 0', b'manual_style_enabled: true', b'---', b'KEEP_RULE'])
    path.write_bytes(content)
    result = module._load_chat_style('-1')
    assert 'KEEP_RULE' in result
    assert '不使用 emoji' in result
    assert path.read_bytes() == content

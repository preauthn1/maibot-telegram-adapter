"""损坏画像不应阻断其他会话的有效规则。"""
from src.chat.utils import scene_context as module


def test_bad_utf8_does_not_discard_other_chat(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, '_style_cache', {})
    monkeypatch.setattr(module, '_style_cache_at', 0.0)
    root = tmp_path / 'data/plugins/adapter/chats'
    bad = root / '-1/SKILL.md'
    good = root / '-2/SKILL.md'
    bad.parent.mkdir(parents=True)
    good.parent.mkdir(parents=True)
    bad.write_bytes(b'\xff\xfeinvalid')
    good.write_text('---\nstyle_enabled: true\nstyle_max_chars: 80\nmax_emoji: 0\nmanual_style_enabled: true\n---\nVALID_CHAT_RULE\n', encoding='utf-8')
    assert 'VALID_CHAT_RULE' in module._load_chat_style('-2')
    assert module._load_chat_style('-1') == ''

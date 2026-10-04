"""禁止 emoji 不应导致整份会话画像失效。"""
from src.chat.utils import scene_context as module


def test_zero_emoji_keeps_other_constraints(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, '_style_cache', {})
    monkeypatch.setattr(module, '_style_cache_at', 0.0)
    path = tmp_path / 'data/plugins/adapter/chats/-1/SKILL.md'
    path.parent.mkdir(parents=True)
    path.write_text('---\nstyle_enabled: true\nstyle_max_chars: 80\nmax_chars: 150\nmax_emoji: 0\nallow_emoji_only: true\nmanual_style_enabled: true\n---\n保留必要条件。\n', encoding='utf-8')
    result = module._load_chat_style('-1')
    assert '150 字符' in result
    assert '保留必要条件' in result
    assert '不使用 emoji' in result
    assert '可以偶尔用纯 emoji' not in result

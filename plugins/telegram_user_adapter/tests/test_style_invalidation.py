"""画像撤回和冲突不等待缓存过期。"""
from src.chat.utils import scene_context as module


def test_changes_invalidate_cached_styles(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, '_style_cache', {})
    monkeypatch.setattr(module, '_style_cache_at', 0.0)
    monkeypatch.setattr(module, '_style_signature', ())
    header = '---\nstyle_enabled: true\nstyle_max_chars: 80\nmax_emoji: 0\nmanual_style_enabled: true\n---\n'
    path = tmp_path / 'data/plugins/a/chats/-1/SKILL.md'
    path.parent.mkdir(parents=True)
    path.write_text(header + 'OLD_RULE')
    assert 'OLD_RULE' in module._load_chat_style('-1')
    path.write_text(header + 'NEW_RULE')
    assert 'NEW_RULE' in module._load_chat_style('-1')
    duplicate = tmp_path / 'data/plugins/b/chats/-1/SKILL.md'
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text(header + 'OTHER_RULE')
    assert module._load_chat_style('-1') == ''
    duplicate.unlink()
    assert 'NEW_RULE' in module._load_chat_style('-1')
    path.unlink()
    assert module._load_chat_style('-1') == ''

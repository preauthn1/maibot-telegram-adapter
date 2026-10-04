"""重复来源不能靠目录顺序覆盖，独立会话仍应可读。"""
import logging
from src.chat.utils import scene_context as module


def test_duplicate_sources_are_not_arbitrarily_selected(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, '_style_cache', {})
    monkeypatch.setattr(module, '_style_cache_at', 0.0)
    header = '---\nstyle_enabled: true\nstyle_max_chars: 80\nmax_emoji: 0\nmanual_style_enabled: true\n---\n'
    for plugin, chat, marker in [('a', '-1', 'RULE_A'), ('z', '-1', 'RULE_Z'), ('a', '-2', 'UNIQUE_RULE')]:
        path = tmp_path / 'data/plugins' / plugin / 'chats' / chat / 'SKILL.md'
        path.parent.mkdir(parents=True)
        path.write_text(header + marker, encoding='utf-8')
    with caplog.at_level(logging.WARNING):
        assert module._load_chat_style('-1') == ''
    assert 'UNIQUE_RULE' in module._load_chat_style('-2')
    assert '重复来源' in caplog.text

"""超长人工规则明确拒绝，但不连带其他会话。"""
import logging
from src.chat.utils import scene_context as module


def test_oversize_isolated_without_truncation(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, '_style_cache', {})
    monkeypatch.setattr(module, '_style_cache_at', 0.0)
    header = '---\nstyle_enabled: true\nstyle_max_chars: 80\nmax_emoji: 1\nmanual_style_enabled: true\n---\n'
    paths = []
    for chat_id, body in [('-1', 'X' * 6001), ('-2', 'VALID_RULE')]:
        path = tmp_path / 'data/plugins/adapter/chats' / chat_id / 'SKILL.md'
        path.parent.mkdir(parents=True)
        path.write_text(header + body, encoding='utf-8')
        paths.append(path)
    with caplog.at_level(logging.WARNING):
        assert 'VALID_RULE' in module._load_chat_style('-2')
    rejected = module._load_chat_style('-1')
    assert 'P90 为 80' in rejected
    assert '最多 1 个 emoji' in rejected
    assert 'X' * 100 not in rejected
    assert '未截断' in caplog.text
    assert paths[0].read_text() == header + 'X' * 6001

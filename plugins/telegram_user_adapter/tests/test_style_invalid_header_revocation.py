"""真实加载入口拒绝损坏头部，并撤回先前缓存的人工规则。"""
from src.chat.utils import scene_context as module


def test_invalid_header_with_later_delimiter_revokes_cached_prompt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, '_style_cache', {})
    path = tmp_path/'data/plugins/adapter/chats/test/SKILL.md'
    path.parent.mkdir(parents=True)
    header = '---\nstyle_enabled: true\nstyle_max_chars: 80\nmax_emoji: 1\nmanual_style_enabled: true\n'
    body = '仅使用合成人工规则标记。'
    valid = header + '---\n' + body
    path.write_text(valid)
    assert body in module._load_chat_style('test')
    # 假分隔符后仍有真分隔符，不能误把中间损坏文本当人工正文。
    path.write_text(header + '---not-a-delimiter\n损坏头部\n---\n' + body)
    assert module._load_chat_style('test') == ''
    path.write_text(valid)
    assert body in module._load_chat_style('test')

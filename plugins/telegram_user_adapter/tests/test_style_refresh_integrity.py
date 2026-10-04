"""画像刷新幂等性与主程序读取验证，不发送群消息。"""
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from telegram_user_adapter.style_profiles import derive_style_controls, merge_style_frontmatter
from src.chat.utils import scene_context


def test_refresh_replaces_peer_fields_and_preserves_manual_body():
    controls = derive_style_controls(['测试'] * 20, ['a', 'abcd'])
    assert controls.peer_median_chars == 2.5
    first = merge_style_frontmatter('---\nmax_chars: 22\n---\n人工正文', controls)
    second = merge_style_frontmatter(first, controls)
    assert first == second
    assert second.count('peer_style_samples:') == 1
    assert second.endswith('人工正文')
    assert 'max_chars: 22' in second


def test_core_reads_only_current_chat(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scene_context, '_style_cache', {})
    monkeypatch.setattr(scene_context, '_style_cache_at', 0.0)
    controls = derive_style_controls(['测试'] * 20, ['入口？', 'abcd'] * 40)
    path = tmp_path / 'data/plugins/test/chats/123/SKILL.md'
    path.parent.mkdir(parents=True)
    path.write_text(merge_style_frontmatter('', controls), encoding='utf-8')
    stream = SimpleNamespace(platform='telegram', group_id='123', user_id='')
    text = scene_context.build_chat_style_context_block(stream)
    assert '80 条' in text
    assert '自然追问' in text
    stream.group_id = '456'
    assert scene_context.build_chat_style_context_block(stream) == ''

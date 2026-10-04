"""生成提示应准确描述画像来源，不把账号身份等同真人作者。"""
from src.chat.utils import scene_context as module


def test_owner_source_not_described_as_automatic_outbound(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, '_style_cache', {})
    path = tmp_path / 'data/plugins/adapter/chats/-1/SKILL.md'
    path.parent.mkdir(parents=True)
    path.write_text('---\nstyle_enabled: true\nstyle_source: owner_inbound_v1\nstyle_owner_samples: 25\nstyle_max_chars: 80\nmax_emoji: 1\n---\n')
    result = module._load_chat_style('-1')
    assert '本账号入站记录' in result
    assert '不证明真人作者身份' in result
    assert '包含自动生成内容' not in result
    assert '不是目标长度' in result

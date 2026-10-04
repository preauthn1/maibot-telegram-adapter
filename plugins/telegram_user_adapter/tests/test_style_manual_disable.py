"""自动刷新不得重新启用人工关闭的风格画像。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.style_profiles import sync_style_profiles


def test_sync_preserves_explicit_manual_disable(tmp_path):
    (tmp_path / 'account_profile.json').write_text(json.dumps({'user_id': 'owner'}))
    transcripts = tmp_path / 'transcripts'
    transcripts.mkdir()
    rows = [{'direction': 'in', 'sender_id': 'owner', 'chat_id': '-1',
             'message_id': i, 'text': f'合成主人表达{i}'} for i in range(25)]
    (transcripts / 'chat_test.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    profile = tmp_path / 'chats' / '-1' / 'SKILL.md'
    profile.parent.mkdir(parents=True)
    original = '---\nstyle_enabled: false\nmax_chars: 80\n---\n人工风险说明，原样保留。\n'
    profile.write_text(original)
    assert sync_style_profiles(tmp_path) == []
    assert profile.read_text() == original

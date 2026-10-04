"""自动回复不能反过来充当主人的风格训练样本。"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.style_profiles import _collect_outbound_messages


def test_style_samples_exclude_automatic_outbound(tmp_path):
    root = tmp_path / 'transcripts'
    root.mkdir()
    rows = [
        {'direction': 'out', 'sender_id': 'owner', 'chat_id': '-1', 'message_id': 1, 'text': '自动回复'},
        {'direction': 'out', 'chat_id': '-1', 'message_id': 2, 'text': '无作者自动回复'},
        {'direction': 'in', 'sender_id': 'peer', 'chat_id': '-1', 'message_id': 3, 'text': '他人消息'},
        {'direction': 'in', 'sender_id': 'owner', 'chat_id': '-1', 'message_id': 4, 'text': '主人原话'},
    ]
    (root / 'chat_test.jsonl').write_text('\n'.join(json.dumps(row) for row in rows))
    assert _collect_outbound_messages(tmp_path, 'owner') == {'-1': ['主人原话']}

"""群聊统计保留引用回复正文，排除私聊和来源不明记录。"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.style_profiles import _collect_peer_messages


def test_peer_corpus_scope_and_reply_body(tmp_path):
    folder = tmp_path / 'transcripts'
    folder.mkdir()
    rows = [
        dict(direction='in', chat_id='g', sender_id='peer', message_id=1,
             is_private=False, text='[回复<甲:123>：旧消息？]，说：现在好了'),
        dict(direction='in', chat_id='g', sender_id='peer', message_id='1',
             is_private=False, text='重复写回'),
        dict(direction='in', chat_id='dm', sender_id='peer', message_id=2,
             is_private=True, text='私聊内容'),
        dict(direction='in', chat_id='g', sender_id='owner', message_id=3,
             is_private=False, text='账号自己'),
        dict(direction='in', chat_id='g', sender_id='', message_id=4,
             is_private=False, text='来源不明'),
        dict(direction='in', chat_id='g', sender_id='peer', message_id=5,
             is_private=False, text='[回复<损坏的引用头'),
        dict(direction='in', chat_id='g', sender_id='peer', message_id=6,
             is_private=False, text='[文件:附件]'),
    ]
    (folder / 'chat_g.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows))
    assert _collect_peer_messages(tmp_path, 'owner') == {'g': ['现在好了']}

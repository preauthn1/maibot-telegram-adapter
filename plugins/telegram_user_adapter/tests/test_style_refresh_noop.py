"""无变化刷新不写文件，也不虚报更新。"""
import json
import sys
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter import style_profiles as module


def test_repeat_refresh_does_not_write_or_report_update(tmp_path, monkeypatch):
    (tmp_path/'account_profile.json').write_text(json.dumps({'user_id':'1'}))
    transcripts=tmp_path/'transcripts'
    transcripts.mkdir()
    (transcripts/'chat_test.jsonl').write_text('\n'.join(json.dumps({
        'direction':'in','sender_id':'1','chat_id':'test','message_id':str(i),
        'text':f'合成文本{i}'}) for i in range(25)))
    assert module.sync_style_profiles(tmp_path) == ['test']
    profile=tmp_path/'chats/test/SKILL.md'
    before=profile.read_bytes()
    writer=Mock(wraps=module.atomic_write_profile)
    monkeypatch.setattr(module,'atomic_write_profile',writer)
    assert module.sync_style_profiles(tmp_path) == []
    writer.assert_not_called()
    assert profile.read_bytes() == before
    with (transcripts/'chat_test.jsonl').open('a') as handle:
        handle.write('\n'+json.dumps({'direction':'in','sender_id':'1','chat_id':'test',
            'message_id':'new','text':'新的合成样本'}))
    assert module.sync_style_profiles(tmp_path) == ['test']
    writer.assert_called_once()
    assert 'style_owner_samples: 26' in profile.read_text()

"""仅撤回来源明确、样本不足的自动画像，不改未知来源。"""
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.style_profiles import sync_style_profiles

@pytest.mark.parametrize('count', [0, 3])
def test_revoke_marked_profile_when_samples_disappear(tmp_path, count):
    (tmp_path/'account_profile.json').write_text(json.dumps({'user_id':'owner'}))
    root = tmp_path/'transcripts'
    root.mkdir()
    rows = [{'direction':'in','sender_id':'owner','chat_id':'-1','message_id':i,'text':f'样本{i}'} for i in range(count)]
    (root/'chat_test.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    profiles = tmp_path/'chats'
    for chat, source in [('-1', 'style_source: owner_inbound_v1\n'), ('-2','')]:
        path = profiles/chat/'SKILL.md'
        path.parent.mkdir(parents=True)
        path.write_text('---\nstyle_enabled: true\n'+source+'style_owner_samples: 25\nmax_chars: 80\n---\n人工说明\n')
    unknown = (profiles/'-2'/'SKILL.md').read_bytes()
    assert sync_style_profiles(tmp_path) == ['-1']
    text = (profiles/'-1'/'SKILL.md').read_text()
    assert 'style_enabled: false\n' in text
    assert f'style_owner_samples: {count}\n' in text
    assert 'max_chars: 80\n' in text and text.endswith('人工说明\n')
    assert (profiles/'-2'/'SKILL.md').read_bytes() == unknown
    assert sync_style_profiles(tmp_path) == []

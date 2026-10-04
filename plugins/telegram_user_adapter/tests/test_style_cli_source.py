"""独立 CLI 必须复用来源过滤和人工关闭保护。"""
import json
import subprocess
import sys
from pathlib import Path


def test_cli_does_not_label_generated_text_as_owner(tmp_path):
    (tmp_path/'account_profile.json').write_text(json.dumps({'user_id':'owner'}))
    logs = tmp_path/'transcripts'
    logs.mkdir()
    rows = [{'direction':'out','chat_id':'-1','message_id':i,'text':f'自动回复{i}'} for i in range(25)]
    rows += [{'direction':'in','sender_id':'owner','chat_id':'-2','message_id':i,'text':f'主人消息{i}'} for i in range(25)]
    (logs/'chat_test.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    p = tmp_path/'chats'/'-2'/'SKILL.md'
    p.parent.mkdir(parents=True)
    original = '---\nstyle_enabled: false\nmax_chars: 80\n---\n人工说明\n'
    p.write_text(original)
    script = Path(__file__).resolve().parents[1]/'scripts'/'generate_style_profiles.py'
    result = subprocess.run([sys.executable, str(script), '--data-dir', str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0
    assert not (tmp_path/'chats'/'-1'/'SKILL.md').exists()
    assert p.read_text() == original

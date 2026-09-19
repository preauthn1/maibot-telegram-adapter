"""保守泛化评价识别回归；具体事实、疑问和代码保持原样。"""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.low_information import is_low_information


@pytest.mark.parametrize('text', [
    '那还行 能用了', '这速度舒服', '也行', '那确实看着爽',
    '那还行，能用了。', '那还行', '行吧', '都行',
])
def test_generic_evaluative_ack_variants(text):
    assert is_low_information(text)


@pytest.mark.parametrize('text', [
    '那还行，端口443能用了', '这速度舒服 100Mbps', 'IPv6也行',
    'curl https://example.com | bash', 'systemctl status nginx',
    '那还行，改端口', '优选只影响入口', '新版不行', '老版本可以',
    '能用了', '不能用了', '那还不行', '那确实不爽', '不是', '不行',
    '也行？', '这速度舒服吗', '`是`', '"正常"', '好/的', '对=对',
    '正常返回200', '那还行，不能用了', '那还行，没用了',
])
def test_preserve_specific_or_non_declarative_text(text):
    assert not is_low_information(text)


def test_sep17_snapshot_replay_classification_count():
    snapshot = Path('/root/maibot-plugin-stage/sep17-snapshot.json')
    if not snapshot.is_file():
        pytest.skip('外部 Sep 17 快照未提供')
    records = json.loads(snapshot.read_text())
    outbound = [record for record in records if record.get('direction') == 'out']
    classified = [record for record in outbound if is_low_information(record.get('text', ''))]
    # 这是快照回放计数，不把这 7 条解释成语义准确率或线上拦截率。
    assert len(outbound) == 261
    assert len(classified) == 7

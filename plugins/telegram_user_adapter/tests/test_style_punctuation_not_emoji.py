"""纯标点反应不能成为允许纯emoji的采样证据。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.style_profiles import derive_style_controls


def test_punctuation_only_is_not_emoji_evidence():
    controls = derive_style_controls(['普通文字'] * 18 + ['？？？', '……'])
    assert not controls.allow_emoji_only


def test_actual_emoji_still_counts():
    controls = derive_style_controls(['普通文字'] * 18 + ['😂', '👍'])
    assert controls.allow_emoji_only

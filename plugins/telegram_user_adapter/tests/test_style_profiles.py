"""同群语言基线的画像回归测试。"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram_user_adapter.style_profiles import derive_style_controls, render_style_frontmatter


def test_peer_baseline_is_saved_without_copying_peer_text():
    owner_messages = [f"自己的消息{i}" for i in range(20)]
    peer_messages = ["这个入口在哪？", "我这里也复现了", "报错贴一下看看"] * 30

    controls = derive_style_controls(owner_messages, peer_messages)
    rendered = render_style_frontmatter(controls)

    assert controls.style_enabled
    assert controls.peer_sample_count == 90
    assert controls.peer_median_chars > 0
    assert controls.peer_question_rate > 0
    assert "peer_style_samples: 90" in rendered
    assert "这个入口在哪" not in rendered
    assert "我这里也复现了" not in rendered


def test_peer_baseline_is_zero_without_peer_history():
    controls = derive_style_controls([f"自己的消息{i}" for i in range(20)])

    assert controls.peer_sample_count == 0
    assert controls.peer_median_chars == 0
    assert controls.peer_question_rate == 0.0

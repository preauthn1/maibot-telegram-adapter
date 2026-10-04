"""自动风格字段应携带可复查的采样版本和数量。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.style_profiles import derive_style_controls, merge_style_frontmatter


def test_generated_profile_records_source_and_replaces_owned_metadata():
    controls = derive_style_controls(['合成表达'] * 25)
    existing = '---\nmax_chars: 80\nstyle_source: owner_inbound_v1\nstyle_owner_samples: 999\n---\n人工说明\n'
    first = merge_style_frontmatter(existing, controls)
    second = merge_style_frontmatter(first, controls)
    assert first == second
    assert first.count('style_source:') == 1
    assert 'style_source: owner_inbound_v1\n' in first
    assert first.count('style_owner_samples:') == 1
    assert 'style_owner_samples: 25\n' in first
    assert 'max_chars: 80\n' in first
    assert first.endswith('人工说明\n')

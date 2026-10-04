"""有歧义的画像头不能通过最后一个键覆盖前面的显式设置。"""
import pytest
from src.chat.utils.scene_context import _parse_style_frontmatter


@pytest.mark.parametrize('raw', [
    '---\nstyle_enabled: false\nstyle_enabled: true\n---\n正文',
    '---\nstyle_enabled: true\n---not-a-delimiter\n正文',
    '---\nmax_emoji: 0\nmax_emoji: 2\n---\n正文',
])
def test_ambiguous_frontmatter_rejected(raw):
    assert _parse_style_frontmatter(raw) == {}


def test_valid_frontmatter_and_body_keys_separated():
    assert _parse_style_frontmatter('---\nstyle_enabled: true\nmax_emoji: 0\n---\nmax_emoji: 2') == {
        'style_enabled': 'true', 'max_emoji': '0'}

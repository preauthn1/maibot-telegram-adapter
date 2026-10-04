"""添加自动元数据时，不改变人工画像正文的缩进与前导空行。"""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.style_profiles import derive_style_controls, merge_style_frontmatter


@pytest.mark.parametrize('body', ['\n\n人工画像\n', '    缩进代码或示例\n下一行\n', '\t保留制表符\n'])
def test_new_frontmatter_preserves_exact_existing_body(body):
    controls = derive_style_controls(['合成样本'] * 20)
    result = merge_style_frontmatter(body, controls)
    assert result.split('---\n', 2)[2] == body
    assert merge_style_frontmatter(result, controls) == result

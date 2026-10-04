"""出站清洗必须保留条件、共情、引用、技术文本和标点。"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.humanize import humanize_chat_text


@pytest.mark.parametrize('text', [
    '我理解你的感受，先休息一下。',
    '然而，这不代表请求成功。',
    '只有备份完成，并且校验通过，才能删除旧文件。',
    '他说“不是”，不是说“是”。',
    '运行 `printf "a  b"`，不要改空格。',
    'https://example.org/a... 不要删掉路径。',
    '好的。',
    '需要我帮你看看吗？',
    '⚠️ 不要断电',
    '第一步：备份\n第二步：验证\n第三步：再迁移',
])
def test_default_preserves_meaning(text):
    result = humanize_chat_text(text)
    assert result.text == text
    assert not result.changed
    assert not result.became_empty


def test_empty_input_is_not_fabricated():
    assert humanize_chat_text('').text == ''

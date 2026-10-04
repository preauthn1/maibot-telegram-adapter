"""长期记忆命中正文传入回复器时保留原始空白。"""
import pytest
from src.maisaka.builtin_tool.query_memory import _build_replyer_memory_reference

@pytest.mark.parametrize('content', [
    '条件：\n如果下雨：\n    不出门\n否则：\n    去公园',
    '\n  def check():\n\treturn False\n\n',
])
def test_memory_reference_preserves_body(content):
    result = _build_replyer_memory_reference({'hits':[{'content':content}]})
    assert result.endswith('1. '+content)


def test_blank_memory_hit_is_still_omitted():
    assert _build_replyer_memory_reference({'hits':[{'content':' \n\t '}]}) == ''

"""人物过滤降级的来源边界必须进入回复器参考。"""
from src.maisaka.builtin_tool.query_memory import _build_replyer_memory_reference


def test_person_fallback_reference_warns_before_hits():
    result = _build_replyer_memory_reference({
        'query':'宠物', 'person_name':'小林', 'person_id':'synthetic-person',
        'fallback_applied':True, 'fallback_reason':'person_filter_miss',
        'hits':[{'content':'豆包是兔子。'}]})
    warning = '人物定向检索未命中，以下为关键词检索结果；不能据此确认命中内容属于目标人物。'
    assert warning in result
    assert result.index(warning) < result.index('豆包是兔子。')


def test_normal_reference_does_not_claim_person_filter_failure():
    result = _build_replyer_memory_reference({'hits':[{'content':'豆包是兔子。'}]})
    assert '人物定向检索未命中' not in result


def test_empty_fallback_does_not_create_reference():
    assert _build_replyer_memory_reference({'fallback_applied':True,
        'fallback_reason':'person_filter_miss', 'hits':[]}) == ''

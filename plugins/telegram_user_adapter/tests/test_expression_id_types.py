"""布尔值不能因 Python bool/int 继承关系冒充表达 ID。"""
from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector


def test_model_ids_exclude_bool_and_keep_int():
    selector = object.__new__(MaisakaExpressionSelector)
    candidates = [{'id':1}, {'id':2}]
    assert selector._parse_selected_ids('{"selected_ids":[true,false,2]}', candidates) == [2]
    assert selector._parse_selected_ids('{"selected_ids":[1]}', [{'id':True}]) == []


def test_hook_ids_exclude_bool():
    selector = object.__new__(MaisakaExpressionSelector)
    assert selector._normalize_selected_ids([True, 2], [{'id':1}, {'id':2}]) == [2]
    assert selector._normalize_candidate_list([{'id':True,'situation':'倾诉','style':'简短共情'}], []) == []

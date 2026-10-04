"""将已验证候选约束接入真实选择入口，不改动其文字或位置。"""
import asyncio
from unittest.mock import AsyncMock
from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector

GUARD = '\n表达方式只决定如何表述，不是新增事实的依据。拒绝要求虚构个人亲历、身份、关系或他人动机的候选；即便情景匹配也不要选择。优先遵循当前用户明确要求；没有合适候选就返回空数组，不必凑数。\n'


def test_default_selector_receives_tested_factuality_constraint():
    selector = object.__new__(MaisakaExpressionSelector)
    candidates = [{'id':6,'situation':'求安慰','style':'声称自己昨天也亲历了同样事件'}]
    runner = AsyncMock(return_value='{"selected_ids":[]}')
    result = asyncio.run(selector._build_default_selection_result(
        session_id='synthetic', candidates=candidates, sub_agent_runner=runner,
        target_message='我只想吐槽，不要建议', reply_reason='回应倾诉'))
    runner.assert_awaited_once()
    prompt = runner.call_args.args[0]
    assert prompt.endswith(GUARD)
    assert prompt.count(GUARD) == 1
    assert '6: 情景=求安慰 | 风格=声称自己昨天也亲历了同样事件' in prompt
    assert '我只想吐槽，不要建议' in prompt
    assert result.selected_expression_ids == []
    assert result.expression_habits == ''

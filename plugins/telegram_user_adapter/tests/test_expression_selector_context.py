"""表达选择子代理实际收到本轮上下文；不调用模型或数据库。"""
import asyncio
from unittest.mock import AsyncMock
from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector


def test_selector_prompt_contains_current_context():
    selector = object.__new__(MaisakaExpressionSelector)
    runner = AsyncMock(return_value='{"selected_ids":[]}')
    asyncio.run(selector._build_default_selection_result(
        session_id='synthetic', candidates=[{'id':1, 'situation':'倾诉', 'style':'简短共情'}],
        sub_agent_runner=runner, chat_history='之前请求排障',
        target_message='现在只想吐槽，不要建议', reply_reason='用户已改变意图'))
    runner.assert_awaited_once()
    prompt = runner.call_args.args[0]
    for marker in ('之前请求排障', '现在只想吐槽，不要建议', '用户已改变意图', '简短共情'):
        assert marker in prompt

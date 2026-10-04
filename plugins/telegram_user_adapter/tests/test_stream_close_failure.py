"""流清理异常不得覆盖正文、原始失败或取消。"""
import asyncio
import pytest
from openai.types.chat import ChatCompletionChunk
from src.llm_models.model_client.openai_client import _default_stream_response_handler
from src.config.model_configs import ReasoningParseMode, ToolArgumentParseMode

@pytest.mark.parametrize('outcome', ['success', 'error', 'cancel'])
def test_close_failure_preserves_primary_outcome(outcome):
    async def run():
        original = ValueError('synthetic primary')
        closes = []
        class Stream:
            async def __aiter__(self):
                if outcome == 'error':
                    raise original
                if outcome == 'cancel':
                    raise asyncio.CancelledError()
                yield ChatCompletionChunk.model_validate({'id':'synthetic','object':'chat.completion.chunk',
                    'created':0,'model':'synthetic','choices':[{'index':0,'delta':{'content':'完整正文'},'finish_reason':'stop'}]})
            async def close(self):
                closes.append(True)
                raise OSError('synthetic secret must not be logged')
        async def call():
            return await _default_stream_response_handler(Stream(), None,
                reasoning_parse_mode=ReasoningParseMode.NONE,
                tool_argument_parse_mode=ToolArgumentParseMode.STRICT,
                reasoning_key='reasoning_content', logical_turn_id='synthetic')
        if outcome == 'success':
            response, _ = await call()
            assert response.content == '完整正文'
        elif outcome == 'error':
            with pytest.raises(ValueError) as caught:
                await call()
            assert caught.value is original
        else:
            with pytest.raises(asyncio.CancelledError):
                await call()
        assert closes == [True]
    asyncio.run(run())


def test_cancellation_during_close_is_not_swallowed():
    async def run():
        closing = asyncio.Event()
        finished = []
        class Stream:
            async def __aiter__(self):
                yield ChatCompletionChunk.model_validate({'id':'synthetic','object':'chat.completion.chunk',
                    'created':0,'model':'synthetic','choices':[{'index':0,'delta':{'content':'完整正文'},'finish_reason':'stop'}]})
            async def close(self):
                closing.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    finished.append(True)
        before = set(asyncio.all_tasks())
        task = asyncio.create_task(_default_stream_response_handler(Stream(), None,
            reasoning_parse_mode=ReasoningParseMode.NONE,
            tool_argument_parse_mode=ToolArgumentParseMode.STRICT,
            reasoning_key='reasoning_content', logical_turn_id='synthetic'))
        await asyncio.wait_for(closing.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert finished == [True]
        assert not (set(asyncio.all_tasks()) - before)
    asyncio.run(run())

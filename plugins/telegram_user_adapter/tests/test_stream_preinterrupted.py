"""已停止的流不应再消费内容或触发底层读取副作用。"""
import asyncio
import pytest
from src.llm_models.model_client.openai_client import _default_stream_response_handler
from src.llm_models.exceptions import ReqAbortException
from src.config.model_configs import ReasoningParseMode, ToolArgumentParseMode


def test_preinterrupted_stream_does_not_read():
    async def run():
        reads, closes = [], []
        class Stream:
            def __aiter__(self):
                return self
            async def __anext__(self):
                reads.append(True)
                raise StopAsyncIteration
            async def close(self):
                closes.append(True)
        flag = asyncio.Event()
        flag.set()
        before = set(asyncio.all_tasks())
        with pytest.raises(ReqAbortException):
            await _default_stream_response_handler(Stream(), flag,
                reasoning_parse_mode=ReasoningParseMode.NONE,
                tool_argument_parse_mode=ToolArgumentParseMode.STRICT,
                reasoning_key='reasoning_content', logical_turn_id='synthetic')
        assert reads == []
        assert closes == [True]
        assert set(asyncio.all_tasks()) == before
    asyncio.run(run())

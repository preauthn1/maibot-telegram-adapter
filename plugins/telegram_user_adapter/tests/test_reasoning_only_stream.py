"""上游只有 reasoning 字段时，不得把它提升为可见正文。"""
import asyncio
import pytest
from openai.types.chat import ChatCompletionChunk
from src.llm_models.model_client.openai_client import _default_stream_response_handler
from src.config.model_configs import ReasoningParseMode, ToolArgumentParseMode
from src.llm_models.exceptions import EmptyResponseException

@pytest.mark.parametrize('mode', [ReasoningParseMode.AUTO, ReasoningParseMode.NATIVE, ReasoningParseMode.NONE])
def test_reasoning_only_never_becomes_visible_answer(mode):
    async def run():
        closed = []
        class Stream:
            async def __aiter__(self):
                for delta, reason in [({'role':'assistant','content':''}, None),
                                      ({'reasoning_content':'SYNTHETIC_PRIVATE_REASONING'}, None), ({}, 'stop')]:
                    yield ChatCompletionChunk.model_validate({'id':'synthetic','object':'chat.completion.chunk',
                        'created':0,'model':'synthetic','choices':[{'index':0,'delta':delta,'finish_reason':reason}]})
            async def close(self):
                closed.append(True)
        try:
            response, _ = await _default_stream_response_handler(Stream(), None,
                reasoning_parse_mode=mode, tool_argument_parse_mode=ToolArgumentParseMode.STRICT,
                reasoning_key='reasoning_content',logical_turn_id='synthetic')
        except EmptyResponseException:
            assert mode == ReasoningParseMode.NONE
        else:
            assert not response.content
            assert mode != ReasoningParseMode.NONE
            assert response.reasoning_content == 'SYNTHETIC_PRIVATE_REASONING'
        assert closed == [True]
    asyncio.run(run())

"""同一 SSE delta 的正文与推理必须分别保留。"""
import asyncio
import json
import httpx
import pytest
from openai import AsyncOpenAI
from src.config.model_configs import ReasoningParseMode, ToolArgumentParseMode
from src.llm_models.model_client.openai_client import _default_stream_response_handler

@pytest.mark.parametrize('mode', [ReasoningParseMode.AUTO, ReasoningParseMode.NATIVE, ReasoningParseMode.NONE])
@pytest.mark.parametrize('fragmented', [False, True])
def test_content_and_reasoning_in_same_delta(mode, fragmented):
    async def run():
        closed = []
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                parts = [('正确正文', 'SYNTHETIC_REASONING')]
                if fragmented:
                    parts = [('正', 'SYNTHETIC_'), ('确', 'REASONING'), ('正文', None)]
                for index, (content, reasoning) in enumerate(parts):
                    event = {'id':'synthetic','created':0,'object':'chat.completion.chunk','model':'synthetic',
                             'choices':[{'index':0,'finish_reason':'stop' if index == len(parts)-1 else None,
                                 'delta':{'content':content,'reasoning_content':reasoning}}]}
                    payload = ('data: '+json.dumps(event, ensure_ascii=False)+'\n\n').encode()
                    for offset in range(len(payload)):
                        yield payload[offset:offset+1]
                yield b'data: [DONE]\n\n'
            async def aclose(self):
                closed.append(True)
        async def transport(request):
            return httpx.Response(200, headers={'content-type':'text/event-stream'}, stream=Body())
        async with AsyncOpenAI(api_key='synthetic',base_url='https://synthetic.invalid/v1',max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))) as client:
            stream = await client.chat.completions.create(model='synthetic',messages=[{'role':'user','content':'测试'}],stream=True)
            response, _ = await _default_stream_response_handler(stream,None,
                reasoning_parse_mode=mode,tool_argument_parse_mode=ToolArgumentParseMode.STRICT,
                reasoning_key='reasoning_content',logical_turn_id='synthetic')
        assert response.content == '正确正文'
        if mode == ReasoningParseMode.NONE:
            assert not response.reasoning_content
        else:
            assert response.reasoning_content == 'SYNTHETIC_REASONING'
        assert closed == [True]
    asyncio.run(run())


@pytest.mark.parametrize('mode', [ReasoningParseMode.AUTO, ReasoningParseMode.NATIVE, ReasoningParseMode.NONE])
def test_nonstream_mixed_fields_match_stream_contract(mode):
    from openai import OpenAI
    from src.llm_models.model_client.openai_client import _default_normal_response_parser
    def transport(request):
        return httpx.Response(200, json={
            'id':'synthetic','created':0,'object':'chat.completion','model':'synthetic',
            'choices':[{'index':0,'finish_reason':'stop','message':{
                'role':'assistant','content':'正确正文','reasoning_content':'SYNTHETIC_REASONING'}}]})
    with OpenAI(api_key='synthetic',base_url='https://synthetic.invalid/v1',max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
        raw = client.chat.completions.create(model='synthetic',
            messages=[{'role':'user','content':'测试'}],stream=False)
        response, _ = _default_normal_response_parser(raw,
            reasoning_parse_mode=mode,tool_argument_parse_mode=ToolArgumentParseMode.STRICT,
            reasoning_key='reasoning_content',logical_turn_id='synthetic')
    assert response.content == '正确正文'
    assert (response.reasoning_content or '') == ('' if mode == ReasoningParseMode.NONE else 'SYNTHETIC_REASONING')

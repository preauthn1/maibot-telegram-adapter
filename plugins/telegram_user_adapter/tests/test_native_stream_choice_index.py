"""原生流解析按候选 index 而不是数组位置选择正文。"""
import asyncio
import pytest
import json
import httpx
from openai import AsyncOpenAI
from src.llm_models.model_client.openai_client import _default_stream_response_handler
from src.config.model_configs import ReasoningParseMode, ToolArgumentParseMode

@pytest.mark.parametrize('separate', [False, True])
@pytest.mark.parametrize('other_payload', ['text', 'reasoning', 'tool'])
@pytest.mark.parametrize('missing_primary', [False, True])
@pytest.mark.parametrize('primary_tool', [False, True, 'malformed'])
def test_native_stream_ignores_other_choices(separate, monkeypatch, other_payload, missing_primary, primary_tool):
    import src.llm_models.model_client.openai_client as client_module
    finish_reasons = []
    monkeypatch.setattr(client_module, '_log_length_truncation', lambda reason, model: finish_reasons.append(reason))
    async def run():
        closed = []
        other = {'index':1,'delta':{'content':'错误候选'},'finish_reason':'length'}
        if other_payload == 'reasoning':
            other['delta'] = {'reasoning_content':'SYNTHETIC_OTHER_REASONING'}
        elif other_payload == 'tool':
            other['delta'] = {'tool_calls':[{'index':0,'id':'other','type':'function',
                'function':{'name':'other_tool','arguments':'not-json'}}]}
        primary = {'index':0,'delta':{'content':'正确正文'},'finish_reason':'stop'}
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                batches = ([[other], [other]] if separate else [[other]]) if missing_primary else (
                    [[primary], [other]] if separate else [[other, primary]])
                if primary_tool and not missing_primary:
                    start = {'index':0,'delta':{'tool_calls':[{'index':0,'id':'primary','type':'function',
                        'function':{'name':'lookup','arguments':'{"city":'}}]},'finish_reason':None}
                    end = {'index':0,'delta':{'tool_calls':[{'index':0,
                        'function':{'arguments':'"杭州"}'}}]},'finish_reason':'tool_calls'}
                    second_start = {'index':0,'delta':{'tool_calls':[{'index':1,'id':'secondary','type':'function',
                        'function':{'name':'weather','arguments':'{"days":'}}]},'finish_reason':None}
                    second_end = {'index':0,'delta':{'tool_calls':[{'index':1,
                        'function':{'arguments':'2}'}}]},'finish_reason':None}
                    if primary_tool == 'malformed':
                        second_end['delta']['tool_calls'][0]['function']['arguments'] = 'broken}'
                    # 同一候选内两个工具参数交错，工具 index 与候选 index 不能混淆。
                    batches = ([[start], [second_start], [other], [second_end], [end]] if separate else
                               [[other, start], [second_start], [second_end], [end]])
                for choices in batches:
                    event = {'id':'synthetic','object':'chat.completion.chunk',
                             'created':0,'model':'synthetic','choices':choices}
                    payload = ('data: ' + json.dumps(event, ensure_ascii=False) + '\n\n').encode()
                    for index in range(len(payload)):
                        yield payload[index:index + 1]
                yield b'data: [DONE]\n\n'
            async def aclose(self):
                closed.append(True)
        async def transport(request):
            return httpx.Response(200, headers={'content-type':'text/event-stream'}, stream=Stream())
        async def parse():
            async with AsyncOpenAI(api_key='synthetic', base_url='https://synthetic.invalid/v1',
                    max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))) as client:
                stream = await client.chat.completions.create(model='synthetic',
                    messages=[{'role':'user','content':'合成测试'}], stream=True)
                return await _default_stream_response_handler(stream, None,
                    reasoning_parse_mode=ReasoningParseMode.AUTO, tool_argument_parse_mode=ToolArgumentParseMode.STRICT,
                    reasoning_key='reasoning_content',logical_turn_id='synthetic')
        if missing_primary:
            from src.llm_models.exceptions import EmptyResponseException
            with pytest.raises(EmptyResponseException):
                await parse()
            assert closed == [True]
            return
        if primary_tool == 'malformed':
            from src.llm_models.exceptions import RespParseException
            with pytest.raises(RespParseException):
                await parse()
            assert closed == [True]
            return
        response, _ = await parse()
        assert not response.reasoning_content
        if primary_tool:
            assert not response.content
            assert response.tool_calls is not None
            assert len(response.tool_calls) == 2
            assert response.tool_calls[0].func_name == 'lookup'
            assert response.tool_calls[0].args == {'city':'杭州'}
            assert response.tool_calls[1].func_name == 'weather'
            assert response.tool_calls[1].args == {'days':2}
            assert response.tool_calls[0].call_id != response.tool_calls[1].call_id
            assert finish_reasons == ['tool_calls']
        else:
            assert response.content == '正确正文'
            assert not response.tool_calls
            assert finish_reasons == ['stop']
        assert closed == [True]
    asyncio.run(run())

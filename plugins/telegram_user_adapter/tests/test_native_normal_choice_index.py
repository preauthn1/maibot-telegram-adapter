"""非流式主候选按 index 选择，缺失时不冒用其他候选。"""
import pytest
import json
import httpx
from openai import OpenAI
from src.llm_models.model_client.openai_client import _default_normal_response_parser
from src.config.model_configs import ReasoningParseMode, ToolArgumentParseMode
from src.llm_models.exceptions import EmptyResponseException

@pytest.mark.parametrize('missing', [False, True])
@pytest.mark.parametrize('other_payload', ['text', 'reasoning', 'tool'])
@pytest.mark.parametrize('primary_tool', [False, True])
def test_normal_primary_choice(missing, monkeypatch, other_payload, primary_tool):
    import src.llm_models.model_client.openai_client as module
    reasons = []
    monkeypatch.setattr(module, '_log_length_truncation', lambda reason, model: reasons.append(reason))
    choices = [{'index':1,'finish_reason':'length','message':{'role':'assistant','content':'错误候选'}}]
    if other_payload == 'reasoning':
        choices[0]['message'] = {'role':'assistant','content':None,'reasoning_content':'SYNTHETIC_OTHER_REASONING'}
    elif other_payload == 'tool':
        choices[0]['message'] = {'role':'assistant','content':None,'tool_calls':[
            {'id':'other','type':'function','function':{'name':'other_tool','arguments':'not-json'}}]}
    if not missing:
        choices.append({'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'正确正文'}})
    if primary_tool and not missing:
        choices[-1] = {'index':0,'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':'primary','type':'function','function':{'name':'lookup','arguments':'{"city":"杭州"}'}}]}}
    requests = []
    def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'id':'synthetic','object':'chat.completion',
            'created':0,'model':'synthetic','choices':choices,
            'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}})
    with OpenAI(api_key='synthetic', base_url='https://synthetic.invalid/v1', max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
        response = client.chat.completions.create(model='synthetic',
            messages=[{'role':'user','content':'合成测试'}], stream=False)
    assert len(requests) == 1
    assert requests[0]['stream'] is False
    assert response.usage is not None
    assert response.usage.total_tokens == 15
    def parse():
        return _default_normal_response_parser(response,
            reasoning_parse_mode=ReasoningParseMode.AUTO,
            tool_argument_parse_mode=ToolArgumentParseMode.STRICT,
            reasoning_key='reasoning_content', logical_turn_id='synthetic')
    if missing:
        with pytest.raises(EmptyResponseException):
            parse()
    else:
        parsed, _ = parse()
        assert not parsed.reasoning_content
        if primary_tool:
            assert not parsed.content
            assert parsed.tool_calls is not None
            assert len(parsed.tool_calls) == 1
            tool = parsed.tool_calls[0]
            assert tool.func_name == 'lookup'
            assert tool.args == {'city':'杭州'}
            assert reasons == ['tool_calls']
        else:
            assert parsed.content == '正确正文'
            assert not parsed.tool_calls
            assert reasons == ['stop']

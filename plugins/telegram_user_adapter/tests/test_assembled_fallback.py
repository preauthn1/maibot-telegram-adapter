"""调用真实评测入口，以合成 SDK 响应覆盖空流回退，不外呼。"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import evaluate_assembled_prompts as runner

@pytest.mark.parametrize('fallback_error', [False, True])
@pytest.mark.parametrize('stream_case', ['empty', 'text', 'tool', 'length', 'unfinished', 'refusal'])
@pytest.mark.parametrize('real_sdk', [False, True])
def test_empty_stream_fallback_records_both_attempts(tmp_path, monkeypatch, fallback_error, stream_case, real_sdk):
    import httpx
    from openai import OpenAI as SDKClient
    source = tmp_path / 'exports'
    source.mkdir()
    for index in range(3):
        (source / f'assembled-{index}.json').write_text(json.dumps({
            'scope':'real assembly with synthetic profile/selection; not production user configuration',
            'sample_id':str(index),'expected':'好','messages':[{'role':'user','content':'只回好'}]}))
    (tmp_path/'config').mkdir()
    (tmp_path/'config/model_config.toml').write_text('synthetic')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner.tomllib, 'loads', lambda _: {
        'model_task_config':{'replyer':{'model_list':['test'],'temperature':0,'max_tokens':20}},
        'models':[{'name':'test','model_identifier':'test','api_provider':'test','extra_params':{'stream_options':{'include_usage':True}}}],
        'api_providers':[{'name':'test','auth_type':'bearer','client_type':'openai','api_key':'synthetic','base_url':'https://synthetic.invalid/v1'}]})
    calls = []
    closed_streams = []
    class FragmentedSSE(httpx.SyncByteStream):
        def __init__(self, payload):
            self.payload = payload
        def __iter__(self):
            # 按字节切分，覆盖 data 行、JSON 与多字节 UTF-8 跨读取边界。
            for index in range(len(self.payload)):
                yield self.payload[index:index + 1]
        def close(self):
            closed_streams.append(self)
    class Delta:
        content = '好' if stream_case == 'text' else ''
        def model_dump(self, **kwargs) -> dict[str, object]:
            if stream_case == 'refusal':
                return {'refusal': 'synthetic refusal'}
            return {'tool_calls': [{}]} if stream_case == 'tool' else {}
    class Stream:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def __iter__(self):
            yield NS(model='test', usage=NS(model_dump=lambda: {'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}), choices=[NS(index=0, finish_reason={'length':'length','unfinished':None}.get(stream_case,'stop'), delta=Delta())])
    class Client:
        def __init__(self, **kwargs):
            self.chat = NS(completions=NS(create=self.create))
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def create(self, **kwargs):
            calls.append(kwargs)
            if kwargs['stream']: return Stream()
            if fallback_error: raise RuntimeError('synthetic private error')
            return NS(model='test',usage=NS(model_dump=lambda: {'prompt_tokens':10,'completion_tokens':3,'total_tokens':13}),choices=[NS(finish_reason='stop',message=NS(content='好'))])
    def transport(request):
        body = json.loads(request.content)
        calls.append({**body, 'extra_body':body})
        if body['stream']:
            delta = Delta().model_dump()
            delta['content'] = Delta.content
            event = {'id':'synthetic','object':'chat.completion.chunk','created':1,'model':'test',
                     'choices':[{'index':0,'finish_reason':{'length':'length','unfinished':None}.get(stream_case,'stop'),'delta':delta}],
                     'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}}
            if stream_case == 'text':
                # 多候选顺序不保证与 index 一致，不能把首元素当主答案。
                event['choices'].insert(0, {'index':1,'finish_reason':'stop',
                                            'delta':{'content':'错误候选'}})
            return httpx.Response(200, headers={'content-type':'text/event-stream'},
                                  stream=FragmentedSSE(('data: '+json.dumps(event, ensure_ascii=False)+'\n\ndata: [DONE]\n\n').encode()))
        if fallback_error:
            return httpx.Response(500, json={'error':{'message':'synthetic private error','type':'server_error'}})
        return httpx.Response(200, json={'id':'synthetic','object':'chat.completion','created':1,'model':'test',
            'usage':{'prompt_tokens':10,'completion_tokens':3,'total_tokens':13},
            'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'好'}}]})
    def sdk_factory(**kwargs):
        return SDKClient(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    monkeypatch.setattr(runner, 'OpenAI', sdk_factory if real_sdk else Client)
    monkeypatch.setattr(sys, 'argv', ['runner', str(source), '--stream', '--empty-stream-fallback'])
    expect_pass = stream_case == 'text' or (stream_case == 'empty' and not fallback_error)
    if not expect_pass:
        with pytest.raises(SystemExit): runner.main()
    else:
        runner.main()
    rows = json.loads(next(source.glob('live-assembled-*/results.json')).read_text())['results']
    assert [c['stream'] for c in calls] == ([True,False]*3 if stream_case == 'empty' else [True]*3)
    for call in calls:
        if not call['stream']:
            assert 'stream_options' not in call['extra_body']
    if real_sdk:
        assert len(closed_streams) == 3
        assert len({id(stream) for stream in closed_streams}) == 3
    assert len(rows) == 3
    # 直接审计本次入口写出的文件，避免手造报告掩盖两轮归属错误。
    from audit_assembled_prompt_budget import audit
    result_path = next(source.glob('live-assembled-*/results.json'))
    if stream_case == 'empty' and fallback_error:
        with pytest.raises(ValueError, match='usage'):
            audit(source, result_path)
    else:
        budget = audit(source, result_path)
        expected_tokens = ({'prompt_tokens':60,'completion_tokens':15,'total_tokens':75}
                           if stream_case == 'empty' else
                           {'prompt_tokens':30,'completion_tokens':6,'total_tokens':36})
        assert budget['reported_token_totals'] == expected_tokens
        assert all(r['attempt_count'] == (2 if stream_case == 'empty' else 1)
                   for r in budget['samples'])
    for row in rows:
        if stream_case != 'empty':
            assert not row.get('fallback_attempted', False)
            assert row['passed'] is expect_pass
            continue
        assert row['fallback_attempted'] is True
        assert row['stream_attempt']['output'] == ''
        assert row['passed'] is (not fallback_error)
        if fallback_error:
            assert row['usage'] is None
            assert row['stream_attempt']['usage']['total_tokens'] == 12
            assert row['error_type'] == ('InternalServerError' if real_sdk else 'RuntimeError')
            assert 'synthetic private error' not in json.dumps(row)
        else:
            assert row['output'] == '好'

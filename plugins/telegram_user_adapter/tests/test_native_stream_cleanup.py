"""真实 SDK 流中途取消时，应关闭 HTTP 流而不是等客户端整体退出。"""
import asyncio
import json
import httpx
import pytest
from openai import AsyncOpenAI
from src.llm_models.model_client.openai_client import _default_stream_response_handler
from src.config.model_configs import ReasoningParseMode, ToolArgumentParseMode


@pytest.mark.parametrize('failure', ['cancel', 'read_error', 'read_timeout', 'interrupt_flag', 'silent_interrupt'])
@pytest.mark.parametrize('first_fragment', [True, False])
@pytest.mark.parametrize('public_entry', [False, True])
def test_cancel_native_stream_closes_transport(failure, first_fragment, public_entry, monkeypatch):
    async def run():
        from src.llm_models.exceptions import ReqAbortException
        waiting = asyncio.Event()
        interrupt = asyncio.Event()
        closed = []
        class HangingStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                event = {'id':'synthetic','object':'chat.completion.chunk','created':0,
                         'model':'synthetic','choices':[{'index':0,'delta':{'content':'部分'},'finish_reason':None}]}
                if first_fragment:
                    yield ('data: '+json.dumps(event)+'\n\n').encode()
                waiting.set()
                if failure == 'interrupt_flag':
                    interrupt.set()
                    yield ('data: '+json.dumps(event)+'\n\n').encode()
                    return
                if failure == 'read_error':
                    raise httpx.ReadError('synthetic transport break')
                if failure == 'read_timeout':
                    raise httpx.ReadTimeout('synthetic transport timeout')
                await asyncio.Event().wait()
            async def aclose(self):
                closed.append(True)
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200,headers={'content-type':'text/event-stream'},stream=HangingStream()))) as http:
            async with AsyncOpenAI(api_key='synthetic',base_url='https://synthetic.invalid/v1',http_client=http,max_retries=0) as sdk:
                snapshots = []
                if public_entry:
                    from src.llm_models.model_client import openai_client as native_module
                    from src.llm_models.model_client.base_client import ResponseRequest
                    from src.config.model_configs import APIProvider, ModelInfo
                    from src.llm_models.payload_content.context_item import ContextItemBuilder, RoleType
                    monkeypatch.setattr(native_module, 'AsyncOpenAI', lambda **kwargs: sdk)
                    monkeypatch.setattr(native_module, 'save_failed_request_snapshot',
                                        lambda **kwargs: snapshots.append(type(kwargs['error']).__name__))
                    native = native_module.OpenaiClient(APIProvider(name='synthetic',auth_type='none',
                        base_url='https://synthetic.invalid/v1',client_type='openai'))
                    request = ResponseRequest(model_info=ModelInfo(name='synthetic',model_identifier='synthetic',
                        api_provider='synthetic',force_stream_mode=True),
                        context_items=[ContextItemBuilder().set_role(RoleType.User).add_text_content('测试').build()],
                        interrupt_flag=interrupt)
                    operation = native.get_response(request)
                else:
                    stream = await sdk.chat.completions.create(model='synthetic',messages=[{'role':'user','content':'测试'}],stream=True)
                    operation = _default_stream_response_handler(stream,interrupt,
                        reasoning_parse_mode=ReasoningParseMode.NONE,tool_argument_parse_mode=ToolArgumentParseMode.STRICT,
                        reasoning_key='reasoning_content',logical_turn_id='synthetic')
                before_tasks = set(asyncio.all_tasks())
                task = asyncio.create_task(operation)
                await asyncio.wait_for(waiting.wait(),2)
                if failure == 'cancel':
                    task.cancel()
                if failure == 'silent_interrupt':
                    interrupt.set()
                expected = {'cancel': asyncio.CancelledError, 'read_error': httpx.ReadError,
                            'read_timeout': httpx.ReadTimeout, 'interrupt_flag': ReqAbortException, 'silent_interrupt': ReqAbortException}[failure]
                original_type = expected
                if public_entry and failure in ('read_error', 'read_timeout'):
                    from src.llm_models.exceptions import NetworkConnectionError
                    expected = NetworkConnectionError
                with pytest.raises(expected) as caught:
                    await asyncio.wait_for(task, 1)
                if public_entry and failure in ('read_error', 'read_timeout'):
                    assert isinstance(caught.value.__cause__, original_type)
                if public_entry:
                    assert snapshots == ([original_type.__name__] if failure in ('read_error', 'read_timeout') else [])
                assert closed == [True]
                await asyncio.sleep(0)
                assert not (set(asyncio.all_tasks()) - before_tasks)
    asyncio.run(run())

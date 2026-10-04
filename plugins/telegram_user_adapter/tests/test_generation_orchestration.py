"""真实生成编排和 context_factory；模型、检索、插件及数据入口隔离。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from test_low_information_outbound import make_codec, send
from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator
from src.llm_models.payload_content.context_item import ContextItemBuilder, RoleType


@pytest.mark.parametrize('answer', ['Alpine', '{"ok":true,"label":"v1中文"}', '```html\n<div>你好</div>\n```'])
@pytest.mark.parametrize('retry_first', [False, 'empty', 'network', 'success_diagnostic_failure', 'transport_read', 'transport_timeout', 'transport_exhausted'])
@pytest.mark.parametrize('stream_mode', [False, True])
@pytest.mark.parametrize('interrupt_enabled', [False, True])
def test_generation_invokes_context_factory(monkeypatch, tmp_path, answer, retry_first, stream_mode, interrupt_enabled):

    from src.chat.replyer import maisaka_generator_base as module
    from src.chat.message_receive.chat_manager import BotChatSession
    from src.chat.utils import scene_context
    import os
    import json
    import tomllib
    from pathlib import Path
    live = os.environ.get('MAIBOT_LIVE_INTEGRATION') == '1'
    if live and interrupt_enabled:
        pytest.skip('中断配置组合仅离线执行')
    if live and stream_mode:
        pytest.skip('现有在线入口只支持非流式')
    if live and retry_first:
        pytest.skip('故障注入仅离线执行，真实模型评测不重复计数')
    cfg = tomllib.loads(Path('config/model_config.toml').read_text()) if live else None
    artifact_dir = Path(os.environ['MAIBOT_INTEGRATION_OUTPUT']).resolve() if live else None
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, 'global_config', SimpleNamespace(
        bot=SimpleNamespace(nickname='合成助手', alias_names=[]),
        personality=SimpleNamespace(personality='', enable_identity_guard=True, reply_style='自然简洁'),
        experimental=SimpleNamespace(emotion_trait=None)))
    monkeypatch.setattr(module, 'build_personality_emotion_suffix', lambda _: '')
    monkeypatch.setattr(scene_context, '_load_account_profile', lambda: {})
    folder = tmp_path / 'data/plugins/synthetic/chats/-123'
    folder.mkdir(parents=True)
    (folder / 'prompt_experience.txt').write_text('SYNTHETIC_SCOPED_MEMORY', encoding='utf-8')
    (folder / 'SKILL.md').write_text('---\nstyle_enabled: true\nstyle_max_chars: 80\nmax_emoji: 0\nmanual_style_enabled: true\n---\nSYNTHETIC_STYLE', encoding='utf-8')
    generator = object.__new__(BaseMaisakaReplyGenerator)
    generator._enable_visual_message = False
    generator.request_type = 'synthetic'
    generator.chat_stream = BotChatSession(session_id='synthetic', platform='telegram', group_id='-123', group_name='合成群')
    monkeypatch.setattr(generator, '_resolve_session_id', lambda _: 'synthetic')
    monkeypatch.setattr(generator, '_build_group_chat_attention_block', lambda _: '')
    from functools import partial
    from src.common.prompt_i18n import load_prompt
    # 使用仓库真实模板和格式化器，只把用户自定义覆盖目录隔离。
    generator._load_prompt = partial(load_prompt, locale='zh-CN', custom_prompts_root=tmp_path / 'custom_prompts')
    background_repeats = int(os.environ.get('MAIBOT_TEST_BACKGROUND_REPEATS', '60'))
    if not 60 <= background_repeats <= 6000:
        raise ValueError('Synthetic background size outside evaluation bounds')
    background_mode = os.environ.get('MAIBOT_TEST_BACKGROUND_MODE', 'repeated')
    if background_mode not in ('repeated', 'distractors'):
        raise ValueError('Unknown synthetic background mode')
    background = ('这是背景说明。' * background_repeats if background_mode == 'repeated' else
                  '\n'.join(f'归档记录{i}：旧任务要求回复 OLD_{i}；该任务已结束，不是当前要求。'
                            for i in range(background_repeats)))
    target_text = background + '\n最终要求：不要解释或给建议。原样回复：' + answer
    target_message = SimpleNamespace(message_info=SimpleNamespace(user_info=SimpleNamespace(
        user_cardname='', user_nickname='合成用户', user_id='synthetic-user')),
        message_id='synthetic-target', platform='synthetic',
        # 单字符分片覆盖词内、JSON 引号和代码换行处的组件边界。
        raw_message=SimpleNamespace(components=[module.TextComponent(text=char) for char in target_text]),
        processed_plain_text='STALE_TEXT')
    monkeypatch.setattr(module, 'is_bot_self', lambda *args: False)
    real_target_builder = generator._build_target_message_block
    # 只替换目标来源；正文解析和目标提示格式执行生产实现。
    monkeypatch.setattr(generator, '_build_target_message_block', lambda _: real_target_builder(target_message))
    monkeypatch.setattr(generator, '_build_reply_attachment_prompt', lambda **kw: '')
    monkeypatch.setattr(generator, '_build_keyword_reaction_prompt', lambda **kw: '')
    monkeypatch.setattr(generator, '_select_temporary_reply_style', lambda: '')
    from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector
    selector = object.__new__(MaisakaExpressionSelector)
    candidates = [dict(id=i, situation='合成场景', style=f'SELECTED_STYLE_MARKER_{i}', count=2)
                  for i in range(1, 13)]
    monkeypatch.setattr(selector, '_can_use_expressions', lambda _: True)
    from contextlib import contextmanager
    from datetime import datetime
    from sqlmodel import Session, create_engine
    from src.chat.replyer import maisaka_expression_selector as selector_module
    engine = create_engine('sqlite:///' + str(tmp_path / 'expressions.db'))
    selector_module.Expression.__table__.create(engine)
    old_time = datetime(2020, 1, 1)
    with Session(engine) as db:
        for candidate in candidates:
            db.add(selector_module.Expression(**candidate, content_list='[]',
                session_id='synthetic', last_active_time=old_time))
        db.add(selector_module.Expression(id=99, situation='其他会话', style='OTHER_SESSION_STYLE',
            content_list='[]', count=2, session_id='other', last_active_time=old_time))
        db.commit()
    @contextmanager
    def isolated_db(auto_commit=True):
        with Session(engine) as db:
            try:
                yield db
                if auto_commit:
                    db.commit()
            except Exception:
                db.rollback()
                raise
    monkeypatch.setattr(selector_module, 'get_db_session', isolated_db)
    monkeypatch.setattr(selector_module, 'global_config', SimpleNamespace(expression=SimpleNamespace(
        expression_checked_only=False, expression_selection_mode='legacy', expression_groups=[])))
    selected = {}
    async def selection_hook(name, **kwargs):
        if name == 'expression.select.before_select':
            selected['id'] = kwargs['candidates'][0]['id']
        return SimpleNamespace(aborted=False, kwargs=kwargs)
    monkeypatch.setattr(selector, '_get_runtime_manager', lambda: SimpleNamespace(invoke_hook=selection_hook))
    async def selection_runner(prompt):
        assert f"SELECTED_STYLE_MARKER_{selected['id']}" in prompt
        return json.dumps({'selected_ids': [selected['id']]})
    # 保留真实回复上下文桥接，只替换它引用的选择器实例。
    monkeypatch.setattr(module, 'maisaka_expression_selector', selector)
    manager = SimpleNamespace(invoke_hook=AsyncMock(return_value=SimpleNamespace(kwargs={})))
    monkeypatch.setattr(generator, '_get_runtime_manager', lambda: manager)
    from uuid import uuid4
    sample_id = uuid4().hex
    captured = []
    # 离线覆盖全部重试/流式组合；不改变已有在线评测输入。
    memory_reference = '【长期记忆检索结果-内部参考】\n人物定向检索未命中，归属尚未确认。\n  合成记忆：\n\t下雨不出门\n'
    memory_references = () if live else (memory_reference,)
    transport_attempts = []
    closed_stream_attempts = []
    async def model_call(*, context_factory, options):
        items = await context_factory(SimpleNamespace(api_provider=SimpleNamespace(client_type='openai')))
        captured[:] = items  # 重试保留最终请求快照，不把两次请求拼成一次。
        # 完整提示装配之后走真实 provider 转换，包含 system 与表达上下文。
        from src.llm_models.model_client.openai_client import _convert_messages, _sanitize_messages_for_toolless_request
        wire = _convert_messages(_sanitize_messages_for_toolless_request(items))
        expected_messages = [{'role': i.role.value, 'content': ''.join(getattr(p, 'text', '') for p in i.parts)} for i in items]
        observed_messages = []
        for message in wire:
            content = message.get('content')
            if isinstance(content, list):
                fragments = []
                for part in content:
                    if part['type'] != 'text':
                        raise AssertionError('Unexpected non-text part in text-only integration')
                    fragments.append(part['text'])
                content = ''.join(fragments)
            assert isinstance(content, str)
            observed_messages.append({'role': message['role'], 'content': content})
        assert observed_messages == expected_messages
        if not live:
            assert sum(m['content'] == memory_reference for m in observed_messages) == 1
            assert observed_messages[-2]['content'] == memory_reference
            assert target_text in observed_messages[-1]['content']
        assert any(message['role'] == 'system' for message in wire)
        export_root = os.environ.get('MAIBOT_ASSEMBLED_PROMPT_OUTPUT')
        if export_root and not live and not retry_first and not stream_mode and not interrupt_enabled:
            export_path = Path(export_root) / ('assembled-' + sample_id + '.json')
            export_path.parent.mkdir(parents=True, exist_ok=True)
            with export_path.open('x', encoding='utf-8') as handle:
                json.dump({'scope': 'real assembly with synthetic profile/selection; not production user configuration',
                           'sample_id': sample_id, 'expected': answer, 'messages': wire},
                          handle, ensure_ascii=False, indent=2)
            export_path.chmod(0o600)
        output = answer
        if not live:
            import httpx
            from openai import AsyncOpenAI
            from src.llm_models.model_client.openai_client import _default_normal_response_parser
            from src.config.model_configs import ReasoningParseMode, ToolArgumentParseMode
            sdk_requests = []
            stream_closures = []
            class BytewiseSSE(httpx.AsyncByteStream):
                def __init__(self, payload):
                    self.payload = payload.encode('utf-8')
                    self.attempt = len(attempts)
                async def __aiter__(self):
                    # 刻意切断中文 UTF-8 字符及 SSE 行边界，验证 SDK 增量解码。
                    for index, byte in enumerate(self.payload):
                        if (retry_first == 'transport_exhausted' or (retry_first in ('transport_read', 'transport_timeout') and len(attempts) == 1)) and index > len(self.payload) // 2:
                            raise (httpx.ReadTimeout if retry_first == 'transport_timeout' else httpx.ReadError)('synthetic interrupted SSE')
                        yield bytes([byte])
                async def aclose(self):
                    stream_closures.append(True)
                    closed_stream_attempts.append(self.attempt)
            def synthetic_transport(request):
                transport_attempts.append(len(attempts))
                sdk_requests.append(json.loads(request.content))
                assert sdk_requests[-1]['stream'] is stream_mode
                if not stream_mode and (retry_first == 'transport_exhausted' or (retry_first in ('transport_read', 'transport_timeout') and len(attempts) == 1)):
                    raise (httpx.ReadTimeout if retry_first == 'transport_timeout' else httpx.ReadError)('synthetic read failure')
                if stream_mode:
                    events = []
                    stream_answer = ('FAILED_ATTEMPT_ONLY_错误残片' if
                        len(attempts) == 1 and retry_first in ('transport_read', 'transport_timeout')
                        else answer)
                    for fragment in stream_answer:
                        events.append({'id': 'synthetic', 'object': 'chat.completion.chunk',
                            'created': 0, 'model': 'synthetic-model', 'choices': [{'index': 0,
                            'finish_reason': None, 'delta': {'content': fragment,
                                'reasoning_content': 'SYNTHETIC_PRIVATE_REASONING'}}]})
                    events.append({'id': 'synthetic', 'object': 'chat.completion.chunk',
                        'created': 0, 'model': 'synthetic-model', 'choices': [{'index': 0,
                        'finish_reason': 'stop', 'delta': {}}]})
                    # 联合验证主候选隔离：非主候选排在数组前面且携带错误正文。
                    for event in events:
                        event['choices'].insert(0, {'index': 1, 'finish_reason': 'length',
                            'delta': {'content': 'OTHER_CANDIDATE_MUST_NOT_LEAK'}})
                    payload = ''.join('data: ' + json.dumps(event, ensure_ascii=False) + '\n\n' for event in events)
                    return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                                          stream=BytewiseSSE(payload + 'data: [DONE]\n\n'))
                return httpx.Response(200, json={'id': 'synthetic', 'object': 'chat.completion',
                    'created': 0, 'model': 'synthetic-model', 'choices': [
                    {'index': 1, 'finish_reason': 'length', 'message': {'role': 'assistant',
                        'content': 'OTHER_CANDIDATE_MUST_NOT_LEAK'}}, {'index': 0,
                    'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': answer,
                        'reasoning_content': 'SYNTHETIC_PRIVATE_REASONING'}}]})
            # 只替换 HTTP 传输；真实装配→provider转换→SDK编码/解码→原生解析。
            async with httpx.AsyncClient(transport=httpx.MockTransport(synthetic_transport)) as http:
                from src.llm_models.model_client import openai_client as native_module
                monkeypatch.setattr(native_module, 'save_failed_request_snapshot', lambda **kwargs: None)
                constructor_calls = []
                def sdk_factory(**kwargs):
                    constructor_calls.append(dict(kwargs))
                    return AsyncOpenAI(**kwargs, http_client=http)
                # 保留 provider 配置解析和客户端构造器，只注入内存 HTTP transport。
                with monkeypatch.context() as constructor_patch:
                    constructor_patch.setattr(native_module, 'AsyncOpenAI', sdk_factory)
                    native = native_module.OpenaiClient(provider_config)
                assert len(constructor_calls) == 1
                assert constructor_calls[0]['base_url'].rstrip('/') == provider_config.base_url.rstrip('/')
                assert constructor_calls[0]['max_retries'] == provider_config.max_retry
                async with native.client:
                    from src.llm_models.model_client.base_client import ResponseRequest
                    request = ResponseRequest(model_info=selected_model, context_items=items,
                        temperature=options['temperature'], max_tokens=options['max_tokens'],
                        extra_params=dict(options['extra_params']),
                        interrupt_flag=asyncio.Event() if interrupt_enabled else None)
                    before_tasks = set(asyncio.all_tasks())
                    # 走公开入口：同时覆盖协议校验、默认解析器选择、turn绑定和诊断附加。
                    parsed = await native.get_response(request)
                    # SDK 的异步生成器终结可能晚一个调度周期；等待其自然完成，
                    # 不主动取消来制造“无残留”的假通过。
                    await asyncio.sleep(0)
                    finalizers = set(asyncio.all_tasks()) - before_tasks
                    if finalizers:
                        _, pending = await asyncio.wait(finalizers, timeout=1)
                        assert not pending
                    assert not (set(asyncio.all_tasks()) - before_tasks)
                    assert parsed.generation_trace is not None
                    assert parsed.generation_trace.provider == provider_config.name
                    assert parsed.generation_trace.model == selected_model.model_identifier
            if stream_mode:
                assert stream_closures == [True]
            assert len(sdk_requests) == 1
            assert sdk_requests[0]['messages'] == wire
            assert sdk_requests[0]['model'] == selected_model.model_identifier
            assert parsed.wire_protocol == 'chat_completions'
            assert parsed.request_wire_payload['messages'] == wire
            parsed_text = parsed.content
            assert isinstance(parsed_text, str) and parsed_text == answer
            assert parsed.usage is None
            output = parsed_text
        if live:
            import requests
            from uuid import uuid4
            task = cfg['model_task_config']['replyer']
            model_info = next(m for m in cfg['models'] if m['name'] == task['model_list'][0])
            provider = next(p for p in cfg['api_providers'] if p['name'] == model_info['api_provider'])
            messages = [{'role': i.role.value, 'content': ''.join(getattr(p, 'text', '') for p in i.parts)} for i in items]
            body = dict(options['extra_params'])
            body.update(model=options['model_identifier'], messages=messages, temperature=options['temperature'], max_tokens=options['max_tokens'], stream=False)
            evidence = {'scope': 'real template/personality/context_factory and HTTP model; retrieval/plugins mocked; local sender', 'sample_id': sample_id, 'messages': messages, 'request_model': body['model'], 'temperature': body['temperature'], 'max_tokens': body['max_tokens']}
            try:
                response = await asyncio.to_thread(requests.post, provider['base_url'].rstrip('/') + '/chat/completions', headers={'Authorization': 'Bearer ' + provider['api_key']}, json=body, timeout=120)
                response.raise_for_status()
                data = response.json()
                choice = data['choices'][0]
                output = choice['message'].get('content')
                evidence.update(output=output, finish_reason=choice.get('finish_reason'), model=data.get('model'))
            except Exception as exc:
                evidence['error_type'] = type(exc).__name__
                raise RuntimeError(type(exc).__name__) from None
            finally:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / ('request-' + sample_id + '.json')).write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
            assert evidence['finish_reason'] == 'stop' and output
        return SimpleNamespace(response=output, reasoning='', model_name=evidence.get('model', '') if live else 'synthetic-model',
            output_items=(ContextItemBuilder().set_role(RoleType.Assistant).add_text_content(output).build(),) ,
            tool_calls=[], generation_attempts=(), prompt_tokens=0, completion_tokens=0, total_tokens=0)
    from src.services.llm_service import LLMServiceClient
    from src.llm_models.model_client.base_client import APIResponse
    from src.llm_models.utils_model import LLMOrchestrator
    should_retry = retry_first in ('empty', 'network', 'transport_read', 'transport_timeout')
    attempts = []
    async def execute(request):
        attempts.append(request)
        if retry_first in ('empty', 'network') and len(attempts) == 1:
            from src.llm_models.exceptions import EmptyResponseException, NetworkConnectionError
            error_type = NetworkConnectionError if retry_first == 'network' else EmptyResponseException
            raise error_type('synthetic transient failure')
        assert request.trace_context.session_id == 'synthetic'
        async def built_context(_client):
            return request.context_items
        raw = await model_call(context_factory=built_context, options={
            'model_identifier': request.model_info.model_identifier,
            'temperature': request.temperature, 'max_tokens': request.max_tokens,
            'extra_params': dict(request.extra_params),
        })
        # 上游返回模型名单独存于评测证据，不改写选模身份或迁移占用计数。
        assert request.model_info.name == selected_model_name
        return APIResponse(output_items=raw.output_items)
    orchestrator_call = AsyncMock(side_effect=execute)
    model = LLMServiceClient(task_name='replyer', request_type='synthetic', session_id='synthetic')
    assert isinstance(model._orchestrator, LLMOrchestrator)
    selected_model_name = cfg['model_task_config']['replyer']['model_list'][0] if live else 'synthetic-model'
    selected_config = next(m for m in cfg['models'] if m['name'] == selected_model_name) if live else {}
    from src.config.model_configs import ModelInfo, APIProvider
    from src.llm_models import utils_model as runtime_module
    # 保留真实选模，仅隔离配置查询和客户端注册表。
    model_fields = dict(selected_config)
    model_fields.update(name=selected_model_name, api_provider='synthetic-provider')
    if not live:
        model_fields['force_stream_mode'] = stream_mode
    model_fields.setdefault('model_identifier', 'synthetic-model')
    selected_model = ModelInfo(**model_fields)
    provider_config = APIProvider(max_retry=2, retry_interval=1, auth_type='none',
        name='synthetic-provider', base_url='https://synthetic.invalid/v1', client_type='openai')
    fake_client = SimpleNamespace(api_provider=provider_config, get_response=orchestrator_call)
    # model_copy(update=...) 不执行字段校验；用真实构造器校验隔离任务。
    task_fields = model._orchestrator.model_for_task.model_dump()
    task_fields.update(model_list=[selected_model_name], selection_strategy='sequential')
    task_config = type(model._orchestrator.model_for_task)(**task_fields)
    # 由真实刷新方法同步新任务和使用状态，不预先手工初始化结果。
    monkeypatch.setattr(runtime_module, 'ensure_configured_clients_loaded', lambda: None)
    synthetic_config = SimpleNamespace(models=[selected_model], api_providers=[provider_config],
        model_task_config=SimpleNamespace(replyer=task_config))
    monkeypatch.setattr(runtime_module.config_manager, 'get_model_config', lambda: synthetic_config)
    def lookup_client(provider):
        assert provider is provider_config
        return fake_client
    monkeypatch.setattr(runtime_module.client_registry, 'get_client_class_instance', lookup_client)
    # 仅隔离诊断记录；请求循环、视觉预处理和客户端分派均执行真实实现。
    from src.llm_models import utils_model as runtime_module
    from unittest.mock import Mock
    success_mark = Mock(side_effect=OSError('synthetic diagnostic failure')
                        if retry_first == 'success_diagnostic_failure' else None)
    monkeypatch.setattr(runtime_module, 'mark_request_succeeded', success_mark)
    monkeypatch.setattr(runtime_module, 'has_request_snapshot', lambda exc: True)
    monkeypatch.setattr(runtime_module, 'update_failed_request_attempt', lambda *a, **kw: None)
    from unittest.mock import Mock
    retry_event = Mock()
    monkeypatch.setattr(model._orchestrator, '_schedule_llm_retry_event', retry_event)
    monkeypatch.setattr(model._orchestrator, '_check_slow_request', lambda *a: None)
    # 仅隔离持久化边界，执行真实缓存统计装配与错误隔离。
    from src.services import llm_service as service_module
    cache_recorder = Mock(side_effect=OSError('synthetic cache storage failure')
                          if retry_first == 'success_diagnostic_failure' else None)
    monkeypatch.setattr(service_module, 'record_llm_cache_usage', cache_recorder)
    generator.express_model = model
    from src.maisaka.context.messages import LLMContextMessage
    history: list[LLMContextMessage] = []
    if os.environ.get('MAIBOT_TEST_HISTORY') == '1':
        from datetime import datetime
        from src.maisaka.context.messages import SessionBackedMessage
        from src.maisaka.context.planner_messages import build_session_backed_text_message
        from src.common.data_models.message_component_data_model import MessageSequence
        history = [
            SessionBackedMessage(raw_message=MessageSequence(components=[]),
                visible_text='之前的请求：只回复 OLD_HISTORY。', timestamp=datetime.now()),
            build_session_backed_text_message(speaker_name='合成助手', text='OLD_HISTORY',
                timestamp=datetime.now(), source_kind='guided_reply'),
        ]
    success, result = asyncio.run(generator.generate_reply_with_context(chat_history=history, reply_tool_args={'reply_style':'简短表达'}, sub_agent_runner=selection_runner, memory_references=memory_references))
    if retry_first == 'transport_exhausted':
        assert not success
        assert orchestrator_call.await_count == 2
        assert transport_attempts == ([1, 2] if stream_mode else [1, 1, 1, 2, 2, 2])
        assert closed_stream_attempts == ([1, 2] if stream_mode else [])
        success_mark.assert_not_called()
        cache_recorder.assert_not_called()
        assert retry_event.call_count == 1
        # 元组依次是 token、失败惩罚、当前占用；失败应惩罚但释放占用。
        assert model._orchestrator.model_usage[selected_model_name] == (0, 1, 0)
        return
    assert success and result.success
    success_mark.assert_called_once()
    cache_recorder.assert_called_once()
    assert cache_recorder.call_args.kwargs['session_id'] == 'synthetic'
    assert cache_recorder.call_args.kwargs['model_name'] == selected_model_name
    cache_prompt = json.loads(cache_recorder.call_args.kwargs['prompt_text'])
    cache_text = '\n'.join(part.get('text', '') for item in cache_prompt['context_items']
                           for part in item.get('parts', []))
    assert '原样回复：' + answer in cache_text
    cached_items_text = [''.join(part.get('text', '') for part in item.get('parts', []))
                         for item in cache_prompt['context_items']]
    actual_items_text = [''.join(getattr(part, 'text', '') for part in item.parts)
                         for item in captured]
    assert cached_items_text == actual_items_text
    assert result.completion.response_text == answer
    if not live and retry_first in ('transport_read', 'transport_timeout'):
        # 分开核对 SDK 内部重试与调度器重试；流响应开始后 SDK 不自动重放。
        assert transport_attempts == ([1, 2] if stream_mode else [1, 1, 1, 2])
        assert closed_stream_attempts == ([1, 2] if stream_mode else [])
    assert orchestrator_call.await_count == (2 if should_retry else 1)
    if should_retry:
        assert attempts[0] is attempts[1]
        retry_event.assert_called_once_with(
            model_name=selected_model_name, attempt=2, max_attempts=2,
            reason='网络错误' if retry_first in ('network', 'transport_read', 'transport_timeout') else '模型返回空回复',
            retry_interval=1)
    else:
        retry_event.assert_not_called()
    assert attempts[-1].trace_context.model_attempt == len(attempts)
    recorded = attempts[-1].trace_context.generation_attempts
    assert len(recorded) == 1
    assert recorded[0].status == 'succeeded'
    # 检查最终返回对象，而非仅检查调度器内部存在记录。
    serialized = json.loads(json.dumps(result.generation_attempts, ensure_ascii=False))
    assert len(serialized) == 1
    assert serialized[0]['attempt_id'] == recorded[0].attempt_id
    assert serialized[0]['status'] == 'succeeded'
    assert serialized[0]['workflow_attempt'] == 1
    assert serialized[0]['provider_attempt'] == len(attempts)
    assert serialized[0]['model_attempt'] == len(attempts)
    assert serialized[0]['model'] == recorded[0].model
    assert serialized[0]['request_items'] and serialized[0]['output_items']
    output_texts = [part['text'] for item in serialized[0]['output_items']
                    for part in item.get('parts', []) if part.get('type') == 'text']
    assert output_texts == [answer]
    if stream_mode and retry_first in ('transport_read', 'transport_timeout'):
        # 首轮输出独立标记，而非正确答案前缀，避免重复拼接恰巧看不出来。
        assert 'FAILED_' not in json.dumps(serialized, ensure_ascii=False)
        assert 'FAILED_' not in cache_recorder.call_args.kwargs['prompt_text']
        assert 'FAILED_' not in result.completion.response_text
    assert recorded[0].provider_attempt == len(attempts)
    assert recorded[0].model_attempt == len(attempts)
    assert recorded[0].request_items == tuple(captured)
    assert recorded[0].model == attempts[-1].model_info.model_identifier
    assert result.completion.model_name == selected_model_name
    assert model._orchestrator.model_usage[selected_model_name] == (0, 0, 0)
    texts = [''.join(getattr(p, 'text', '') for p in getattr(i, 'parts', ())) for i in captured]
    for marker in ('SYNTHETIC_SCOPED_MEMORY', 'SYNTHETIC_STYLE', '角色与事实边界', '不使用 emoji'):
        assert marker in texts[0]
    # 表达块按生产设计是历史后的独立 user item，不在人设 system item 中。
    import re
    marker = f"SELECTED_STYLE_MARKER_{selected['id']}"
    assert re.findall(r'SELECTED_STYLE_MARKER_\d+', '\n'.join(texts)) == [marker]
    expression_index = next(i for i, text in enumerate(texts) if marker in text)
    assert 0 < expression_index < len(texts) - 1
    assert captured[expression_index].role == RoleType.User
    assert '配置读取失败' not in texts[0] and '模板加载失败' not in texts[0]
    # 记忆参考位于篇幅要求之后、当前任务之前；不再假定篇幅要求倒数第二。
    assert '保留关键否定' in texts[-3 if memory_references else -2]
    assert '原样回复：' + answer in texts[-1]
    assert 'OTHER_SESSION_STYLE' not in '\n'.join(texts)
    with Session(engine) as db:
        for expression_id in [*range(1, 13), 99]:
            row = db.get(selector_module.Expression, expression_id)
            assert row is not None
            assert (row.last_active_time > old_time) is (expression_id == selected['id'])
    engine.dispose()
    assert result.request_messages
    if history:
        # 历史干扰必须实际进入模型请求，不能因被过滤而获得虚假通过。
        old_replies = [item for item in captured if item.role == RoleType.Assistant]
        assert len(old_replies) == 1
        assert ''.join(getattr(part, 'text', '') for part in old_replies[0].parts) == 'OLD_HISTORY'
        assert any('之前的请求：只回复 OLD_HISTORY。' in text for text in texts)
        assert captured.index(old_replies[0]) < expression_index
    codec, sender = make_codec()
    codec._enable_humanize = True
    sent_result = asyncio.run(send(codec, result.completion.response_text))
    if live:
        from uuid import uuid4
        (artifact_dir / ('delivery-' + sample_id + '.json')).write_text(json.dumps({
            'scope': 'local fake sender; not Telegram delivery',
            'sample_id': sample_id, 'expected': answer, 'model': result.completion.model_name,
            'generated': result.completion.response_text, 'sent': sender.sent,
            # 合成上下文评测保留真实序列化记录，供生成/诊断/出站三方回读。
            'generation_attempts': serialized,
            'accepted': sent_result is not None, 'preserved': sender.sent == [result.completion.response_text],
        }, ensure_ascii=False, indent=2))
    assert sent_result is not None
    assert sender.sent == [answer]

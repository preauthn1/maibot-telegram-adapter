"""隔离真实 replyer 装配→联网 SDK→真实历史工厂的连续评测（不发送消息）。"""
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import argparse
import asyncio
import errno
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
SUBSTITUTES = [
    '合成 BotChatSession/用户消息与固定自动助手人格；未运行构造器/服务生命周期',
    '固定透传 Hook manager；不加载实际插件 Hook',
    'sub_agent_runner=None：真实 _build_reply_context 按生产分支跳过表达检索',
    '无长期记忆参考、账号档案、群注意力、关键词反应、附件或临时风格',
    'LLM 服务替换为仅调用真实 context_factory 并导出请求的边界；不测试原生客户端/模型调度重试',
    '联网父进程使用 OpenAI SDK；生成后不执行 replyer after_response/出站处理/发送提交',
    '实际原始可见生成经 guided_reply 工厂模拟已发送历史；不是 Telegram 已发送证明',
]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    path.chmod(0o600)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text(message):
    content = message['content']
    if isinstance(content, str):
        return content
    require(all(p['type'] == 'text' for p in content), '非纯文本请求')
    return ''.join(p['text'] for p in content)


def prepare_request(model, task, messages):
    body = dict(model=model['model_identifier'], messages=messages,
        temperature=task['temperature'], max_tokens=task['max_tokens'], stream=False)
    blocked = set(body) | {'stream_options', 'extra_body', 'extra_headers', 'extra_query', 'timeout'}
    configured = model.get('extra_params', {})
    return body, {k: v for k, v in configured.items() if k not in blocked}, sorted(set(configured) & blocked)


def isolation():
    require(os.readlink('/proc/self/ns/net') != os.environ.get('RUNTIME_DIALOGUE_PARENT_NET'), '网络未隔离')
    mounts = Path('/proc/self/mountinfo').read_text().splitlines()
    for name in ('data', 'logs'):
        require(any(line.split()[4] == str(ROOT / name) and ' - tmpfs ' in line for line in mounts), '缺少 tmpfs')
    try:
        fd = os.open(ROOT / 'src/__init__.py', os.O_WRONLY)
    except OSError as exc:
        require(exc.errno == errno.EROFS, '源文件未得到 EROFS')
    else:
        os.close(fd)
        raise RuntimeError('源文件可写')
    return {'network_namespace_separate': True, 'data_logs_tmpfs': True, 'source_open_EROFS': True}


async def worker(payload, output):
    # 必须先验证隔离，再导入任何生产模块。
    protection = isolation()
    sys.path.insert(0, str(ROOT))
    from src.chat.message_receive.chat_manager import BotChatSession
    from src.chat.replyer import maisaka_generator_base as module
    from src.chat.utils import scene_context
    from src.common.data_models.message_component_data_model import MessageSequence
    from src.common.prompt_i18n import load_prompt
    from src.llm_models.model_client.openai_client import _convert_messages, _sanitize_messages_for_toolless_request
    from src.maisaka.context.planner_messages import build_session_backed_text_message
    from src.maisaka.reasoning_engine import MaisakaReasoningEngine

    module.global_config = SimpleNamespace(
        bot=SimpleNamespace(nickname='合成助手', alias_names=[]),
        personality=SimpleNamespace(personality='', enable_identity_guard=True, reply_style='自然简洁'),
        experimental=SimpleNamespace(emotion_trait=None))
    module.build_personality_emotion_suffix = lambda _: ''
    module.is_bot_self = lambda *a: False
    scene_context._load_account_profile = lambda: {}
    generator = object.__new__(module.BaseMaisakaReplyGenerator)
    generator.chat_stream = BotChatSession(session_id='synthetic-runtime-v2', platform='telegram',
        group_id='synthetic-runtime-v2', group_name='合成评测群')
    generator.request_type = 'synthetic-runtime-evaluation'
    generator._enable_visual_message = False
    generator._resolve_session_id = lambda _: 'synthetic-runtime-v2'
    generator._build_group_chat_attention_block = lambda _: ''
    generator._build_keyword_reaction_prompt = lambda **kw: ''
    generator._build_reply_attachment_prompt = lambda **kw: ''
    generator._select_temporary_reply_style = lambda: ''
    generator._load_prompt = partial(load_prompt, locale='zh-CN', custom_prompts_root=Path('/tmp/empty-prompts'))
    hook_calls = []

    async def hook(name, **kwargs):
        hook_calls.append(name)
        return SimpleNamespace(aborted=False, kwargs=kwargs)

    generator._get_runtime_manager = lambda: SimpleNamespace(invoke_hook=hook)
    engine = object.__new__(MaisakaReasoningEngine)
    engine._runtime = SimpleNamespace(_is_focus_mode_active_for_current_chat=lambda: False)

    def user_message(body, index):
        sequence = MessageSequence([])
        sequence.text(body)
        return SimpleNamespace(platform='telegram', message_id=f'user-{index}', session_id='synthetic-runtime-v2',
            timestamp=datetime(2026, 1, 1, 12, index), is_notify=False, raw_message=sequence,
            message_info=SimpleNamespace(user_info=SimpleNamespace(user_id='synthetic-user',
                user_nickname='合成用户', user_cardname='')))

    history = []
    for index, previous in enumerate(payload['previous']):
        history.append(await engine._build_history_message(user_message(previous['user'], index), source_kind='user'))
        history.append(build_session_backed_text_message(speaker_name='合成助手', text=previous['output'],
            timestamp=datetime(2026, 1, 1, 12, index), source_kind='guided_reply',
            message_id=f'generated-{index}', is_self_message=True))
    history_wire = _convert_messages(generator._build_history_messages(history, False))
    expected = payload['previous']
    require(len(history_wire) == 2 * len(expected), '历史条数错误')
    for index, previous in enumerate(expected):
        require(history_wire[2 * index]['role'] == 'user' and previous['user'] in text(history_wire[2 * index]), '用户历史丢失')
        require(history_wire[2 * index + 1]['role'] == 'assistant' and text(history_wire[2 * index + 1]) == previous['output'], '实际输出历史改变')
    if payload.get('verify_only'):
        save(output, {'isolation': protection, 'history': history_wire, 'verified_generated_replies': len(expected)})
        return

    class AssemblyCaptured(BaseException):
        """只在真实模型边界终止，不虚构生成结果。"""

    async def capture(*, context_factory, options):
        items = await context_factory(SimpleNamespace(api_provider=SimpleNamespace(client_type='openai')))
        wire = _convert_messages(_sanitize_messages_for_toolless_request(items))
        require(wire[0]['role'] == 'system', '缺少 system')
        require('模板加载失败' not in text(wire[0]) and '配置读取失败' not in text(wire[0]), '真实模板降级')
        require(wire[1:1 + len(history_wire)] == history_wire, '完整请求历史与真实工厂不符')
        require(payload['user'] in text(wire[-1]), '当前目标未装配')
        save(output, {'messages': wire, 'isolation': protection, 'hooks': hook_calls,
            'verified_generated_replies': len(expected), 'history': history_wire,
            'entrypoint': 'BaseMaisakaReplyGenerator.generate_reply_with_context/context_factory'})
        raise AssemblyCaptured()

    generator.express_model = SimpleNamespace(task_name='replyer', generate_response_with_context=capture)
    try:
        await generator.generate_reply_with_context(chat_history=history,
            reply_message=user_message(payload['user'], len(expected)), stream_id='synthetic-runtime-v2',
            sub_agent_runner=None, memory_references=())
    except AssemblyCaptured:
        return
    raise RuntimeError('未到达真实模型请求装配边界')


def assemble(run, name, payload):
    input_path = run / (name + '-input.json')
    output = run / (name + '-assembly.json')
    save(input_path, payload)
    with tempfile.TemporaryDirectory(prefix='runtime-dialogue-v2-') as temp:
        config = Path(temp) / 'config'
        shutil.copytree(ROOT / 'config', config)
        command = ['bwrap', '--die-with-parent', '--unshare-pid', '--unshare-net', '--ro-bind', '/', '/',
            '--tmpfs', '/tmp', '--tmpfs', str(ROOT / 'data'), '--tmpfs', str(ROOT / 'logs'),
            '--bind', str(config), str(ROOT / 'config'), '--bind', str(run), '/tmp/artifacts',
            '--proc', '/proc', '--dev', '/dev', '--chdir', str(ROOT),
            '--setenv', 'RUNTIME_DIALOGUE_PARENT_NET', os.readlink('/proc/self/ns/net'),
            '--setenv', 'PYTHONDONTWRITEBYTECODE', '1', str(ROOT / '.venv/bin/python'), '-O', str(Path(__file__).resolve()),
            '--worker', '/tmp/artifacts/' + input_path.name, '--output', '/tmp/artifacts/' + output.name]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        # 原始日志仅私有保存，终端只报告错误类型，避免配置堆栈公开。
        (run / (name + '-worker.log')).write_text(result.stdout + result.stderr)
        require(result.returncode == 0 and output.exists(), '装配 worker 失败：' + name)
    return json.loads(output.read_text())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', type=Path)
    parser.add_argument('--model', default='gpt-5.6-luna')
    parser.add_argument('--output', type=Path, default=Path('/root/maibot-runtime-dialogue-v2'))
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--assembly-only', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if args.worker:
        asyncio.run(worker(json.loads(args.worker.read_text()), args.output))
        return
    require(args.cases is not None, '必须提供冻结 --cases')
    cases = json.loads(args.cases.read_text())
    ids = [s['id'] for s in cases['scenarios']]
    require(len(ids) == len(set(ids)) and ids, '场景重复或空')
    for scenario in cases['scenarios']:
        require(len(scenario['turns']) >= 3, '每个场景至少三轮')
    config = tomllib.loads((ROOT / 'config/model_config.toml').read_text())
    model = next(m for m in config['models'] if m['name'] == args.model)
    provider = next(p for p in config['api_providers'] if p['name'] == model['api_provider'])
    require(provider['client_type'] == 'openai' and provider['auth_type'] == 'bearer', '不支持的 provider')
    task = config['model_task_config']['replyer']
    run = args.output / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    run.mkdir(parents=True, mode=0o700)
    protected = [p for d in ('src', 'config', 'prompts') for p in (ROOT / d).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    before = {str(p.relative_to(ROOT)): sha(p) for p in protected}
    save(run / 'source-before.json', before)
    save(run / 'cases.json', cases)
    report = {'scope': '真实完整装配与连续模型输出回填；不是生产端到端', 'substitutes': SUBSTITUTES,
        'fixture_sha256': sha(args.cases), 'script_sha256': sha(Path(__file__)), 'model': model['model_identifier'],
        'sdk_max_retries': 0, 'scenarios': {}, 'status': 'running'}
    save(run / 'report.json', report)
    print('RUN', run, flush=True)
    try:
        # 联网父进程只导入 SDK，不导入 src、插件或生产脚本。
        from openai import OpenAI
        with OpenAI(api_key=provider['api_key'], base_url=provider['base_url'], timeout=120, max_retries=0) as client:
            for scenario_index, scenario in enumerate(cases['scenarios']):
                previous = []
                rows = report['scenarios'][scenario['id']] = []
                for index, turn in enumerate(scenario['turns']):
                    name = f's{scenario_index + 1}-t{index + 1}'
                    assembly = assemble(run, name, {'previous': previous, 'user': turn['user']})
                    if args.assembly_only:
                        report['status'] = 'assembly_only_first_turn'
                        return
                    # 模型 extra_params 不得覆盖冻结的装配/传输标准字段。
                    body, extra_body, filtered_keys = prepare_request(model, task, assembly['messages'])
                    save(run / (name + '-request.json'), {**body, **extra_body})
                    report['effective_parameters'] = {key: value for key, value in body.items() if key != 'messages'}
                    report['effective_parameters']['extra_body'] = extra_body
                    report['filtered_extra_keys'] = filtered_keys
                    row = dict(turn=index + 1, user=turn['user'], request_file=name + '-request.json',
                        history_verified_replies=assembly['verified_generated_replies'])
                    rows.append(row)
                    save(run / 'report.json', report)
                    start = time.monotonic()
                    raw = client.chat.completions.with_raw_response.create(**body, extra_body=extra_body)
                    # 保存服务器原始 JSON（无请求头/凭据），不是手工合成 SDK 外壳。
                    raw_text = raw.http_response.text
                    (run / (name + '-raw-response.json')).write_text(raw_text)
                    data = raw.parse().model_dump()
                    choice = next(c for c in data['choices'] if c['index'] == 0)
                    answer = choice['message']['content']
                    row.update(http_status=raw.status_code, output=answer, finish_reason=choice['finish_reason'],
                        elapsed_seconds=round(time.monotonic() - start, 3), usage=data.get('usage'))
                    save(run / 'report.json', report)
                    require(isinstance(answer, str) and answer.strip() and choice['finish_reason'] == 'stop', '响应不完整')
                    if 'expected_exact' in turn:
                        row['expected_exact'] = turn['expected_exact']
                        row['exact_pass'] = answer == turn['expected_exact']
                    else:
                        row.update(rubric=turn['rubric'], rubric_status='pending_independent_review')
                    previous.append({'user': turn['user'], 'output': answer})
                    save(run / 'report.json', report)
                    print(name, 'complete', flush=True)
                assemble(run, f's{scenario_index + 1}-final-history', {'previous': previous, 'verify_only': True})
        require(not any(n == 'src' or n.startswith('src.') for n in sys.modules), '父进程导入生产模块')
        report['status'] = 'complete'
        report['parent_has_no_production_imports'] = True
    except Exception as exc:
        report['status'] = 'error'
        report['error_type'] = type(exc).__name__
        if hasattr(exc, 'status_code'):
            report['error_http_status'] = exc.status_code
        raise
    finally:
        after = {str(p.relative_to(ROOT)): sha(p) for p in protected}
        save(run / 'source-after.json', after)
        report['protected_manifest_unchanged'] = before == after
        report['completed_turns'] = sum('output' in row and row.get('finish_reason') == 'stop' for rows in report['scenarios'].values() for row in rows)
        save(run / 'report.json', report)
        require(before == after, '受保护文件改变')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('FAILED', type(exc).__name__, file=sys.stderr)
        raise SystemExit(1) from None

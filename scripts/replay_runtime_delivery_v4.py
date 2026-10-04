"""旧模型输出的离线发送回放；历史提交是参考实现，不证明生产 driver 闭环。"""
from collections import Counter
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile

from evaluate_runtime_dialogue_v2 import isolation, require, save, sha, text

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path('/root/maibot-runtime-dialogue-v2/20260927T131023Z-045effc9/report.json')
DEFAULT_CASES = ROOT / 'tests/fixtures/runtime_dialogue_v2_holdout.json'
SCOPE = '旧生成输出回放，非按新历史重新生成；手动成功发送提交为期望链路/参考实现，不证明生产 plugin_driver/send_service sent-history 闭环'


def validate_source(report, cases):
    expected = {s['id']: s['turns'] for s in cases['scenarios']}
    require(len(expected) == len(cases['scenarios']) and bool(expected), '重复或空场景')
    require(report['status'] == 'complete' and set(report['scenarios']) == set(expected), '源场景覆盖不符')
    for name, turns in expected.items():
        rows = report['scenarios'][name]
        require(len(rows) == len(turns), '轮数不符')
        for i, (row, turn) in enumerate(zip(rows, turns, strict=True), 1):
            require(row['turn'] == i and row['user'] == turn['user'], '原输入或顺序改变')
            require(row['finish_reason'] == 'stop' and isinstance(row['output'], str) and bool(row['output'].strip()), '不完整生成')
    return expected


def has_reasoning(value):
    if isinstance(value, dict):
        return any((k in {'reasoning', 'reasoning_content', 'thinking', 'chain_of_thought'} and bool(v)) or has_reasoning(v) for k, v in value.items())
    return isinstance(value, list) and any(has_reasoning(v) for v in value)


def accepted_texts(receipt, calls):
    """只接纳 fake transport 已确认文本；独立核对 codec 的顶层观测。"""
    if receipt['success'] is not True:
        require(not calls, '失败 receipt 却存在成功发送，不能静默丢弃')
        return []
    require(bool(calls), '成功 receipt 无发送证据')
    observations = receipt['text_observations']
    observed = [o['text'] for o in observations]
    require(observed == [c['text'] for c in calls], 'codec 观测与 transport 不符')
    return observed


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def get_entity(self, target):
        return target

    async def send_text(self, entity, text, **kwargs):
        if self.fail:
            raise RuntimeError('synthetic transport failure')
        call = {'id': str(10000 + len(self.calls)), 'text': text, 'entity': entity, 'kwargs': kwargs}
        self.calls.append(call)
        return SimpleNamespace(id=call['id'])


async def worker(payload, output):
    protection = isolation()  # 生产模块导入之前强制验证。
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'plugins'))
    from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator
    from src.common.data_models.message_component_data_model import MessageSequence
    from src.llm_models.model_client.openai_client import _convert_messages
    from src.maisaka.context.planner_messages import build_session_backed_text_message
    from src.maisaka.reasoning_engine import MaisakaReasoningEngine
    from src.plugin_runtime.host.message_utils import PluginMessageUtils
    from src.services.send_service import _build_reply_component
    from telegram_user_adapter.acknowledgement_context import acknowledgement_word
    from telegram_user_adapter.codecs.outbound import TelegramUserOutboundCodec
    from telegram_user_adapter.unlimited_mode import is_unlimited

    require(not is_unlimited(), '实验无限预算启用')
    engine = object.__new__(MaisakaReasoningEngine)
    engine._runtime = SimpleNamespace(_is_focus_mode_active_for_current_chat=lambda: False)
    generator = object.__new__(BaseMaisakaReplyGenerator)
    generator._enable_visual_message = False

    def convert(history):
        return _convert_messages(generator._build_history_messages(history, False))

    async def scenario(name, source_rows, fail_turns=()):
        # 每场景唯一 codec；不使用会放宽预算的测试 make_codec。
        sender = FakeTransport()
        codec = TelegramUserOutboundCodec(sender, logging.getLogger('delivery-v4'))
        codec.set_behavior(simulate_typing=False, typing_cps=6.0, min_think_delay=0,
                           max_typing_delay=0, enable_humanize=True, max_emoji=1, quote_probability=0.15)
        history, rows, expected_assistants, expected_roles = [], [], [], []
        budget = {'hourly_limit': codec._send_budget.hourly_limit, 'minute_limit': codec._send_budget.minute_limit,
                  'low_information_budget_seconds': codec._low_information_budget_seconds}
        for index, source in enumerate(source_rows, 1):
            before = convert(history)
            if rows:
                require(before == rows[-1]['next_history'], '下一轮实际历史与提交结果不符')
            sequence = MessageSequence([])
            sequence.text(source['user'])
            target_id = str(900 + index)
            target = SimpleNamespace(platform='telegram', message_id=target_id, session_id=name,
                timestamp=datetime(2026, 1, 1, 12, index), is_notify=False, raw_message=sequence,
                processed_plain_text=source['user'],
                message_info=SimpleNamespace(user_info=SimpleNamespace(user_id='synthetic-user',
                    user_nickname='合成用户', user_cardname='')))
            history.append(await engine._build_history_message(target, source_kind='user'))
            expected_roles.append('user')
            wire = PluginMessageUtils._component_to_dict(_build_reply_component(target_id, target), include_binary_data=False)
            require(wire['data']['target_message_content'] == source['user'], 'host 修改了原输入')
            segments = [wire, {'type': 'text', 'data': source['output']}]
            start = len(sender.calls)
            sender.fail = index in fail_turns
            receipt = await codec.send_outbound_message({'message_info': {'group_info': {'group_id': '123'}},
                                                         'raw_message': segments}, {})
            calls = sender.calls[start:]
            sent = accepted_texts(receipt, calls)
            # 明确是参考提交器，未通过生产 plugin_driver/send_service。
            for call in calls:
                history.append(build_session_backed_text_message(speaker_name='合成助手', text=call['text'],
                    timestamp=target.timestamp, source_kind='guided_reply', message_id=call['id'], is_self_message=True))
                expected_assistants.append(call['text'])
                expected_roles.append('assistant')
            after = convert(history)
            require([m['role'] for m in after] == expected_roles, '历史角色/数量改变')
            require([text(m) for m in after if m['role'] == 'assistant'] == expected_assistants, '已发送历史不匹配')
            user_history = [text(m) for m in after if m['role'] == 'user']
            require(all(s['user'] in h for s, h in zip(source_rows[:index], user_history, strict=True)), '用户历史丢失')
            require(len(after) - len(before) == 1 + len(sent), '失败草稿写入历史')
            rows.append({'turn': index, 'user': source['user'], 'original_response': source['output'],
                'status': 'blocked' if not sent else ('preserved' if sent == [source['output']] else 'modified'),
                'host_reply_component': wire, 'acknowledgement_qualified': acknowledgement_word(segments, int(target_id), None),
                'codec_receipt': receipt, 'successful_transport_calls': calls, 'sent_texts': sent,
                'history_before': before, 'next_history': after, 'history_verified': True,
                'typing_delay_simulated_zero': True, 'transport_failure_injected': sender.fail})
        return {'codec_instances': 1, 'budget': budget, 'turns': rows, 'final_history': convert(history)}

    results = {}
    for name, rows in payload['scenarios'].items():
        results[name] = await scenario(name, rows)
    # 单独的故障注入控制，不冒充那九轮模型结果。
    probes = await scenario('synthetic_failure_control', [
        {'user': '故障注入控制，不属于模型评测。', 'output': '检查远程端口443。'},
        {'user': '读取后续历史。', 'output': '查看容器状态。'}], fail_turns=(1,))
    require(probes['turns'][0]['status'] == 'blocked', '故障注入未失败')
    require(all(m['role'] != 'assistant' for m in probes['turns'][1]['history_before']), '失败草稿污染后续历史')
    modification = await scenario('synthetic_modified_control', [
        {'user': '合成命令格式控制，不属于模型评测。', 'output': 'systemctl status nginx'},
        {'user': '读取后续历史。', 'output': '检查远程端口443。'}])
    first = modification['turns'][0]
    require(first['status'] == 'modified', '改写控制未触发真实 codec 改写')
    require([text(m) for m in modification['turns'][1]['history_before'] if m['role'] == 'assistant'] == first['sent_texts'], '改写未回填')
    save(output, {'scope': SCOPE, 'isolation': protection, 'scenarios': results,
                  'synthetic_failure_control': probes, 'synthetic_modified_control': modification})


def manifest():
    return {str(p.relative_to(ROOT)): sha(p) for folder in ('src', 'config', 'prompts', 'plugins/telegram_user_adapter')
            for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.git' not in p.parts}


def run(source, cases_path, output):
    report, cases = json.loads(source.read_text()), json.loads(cases_path.read_text())
    validate_source(report, cases)
    require(report['fixture_sha256'] == sha(cases_path), '原 fixture 指纹不符')
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    before = manifest()
    save(output / 'source-before.json', before)
    raw_hashes = {}
    for si, name in enumerate(report['scenarios'], 1):
        for ti, row in enumerate(report['scenarios'][name], 1):
            raw_name = f's{si}-t{ti}-raw-response.json'
            raw_path = source.parent / raw_name
            data = json.loads(raw_path.read_text())
            require(not has_reasoning(data), '源包含思维链，不复制')
            choice = next(c for c in data['choices'] if c['index'] == 0)
            require(choice['message']['content'] == row['output'], '原 response 与 report 不符')
            shutil.copyfile(raw_path, output / raw_name)
            (output / raw_name).chmod(0o600)
            raw_hashes[raw_name] = sha(raw_path)
    save(output / 'input.json', {'scenarios': report['scenarios']})
    save(output / 'cases.json', cases)
    try:
        with tempfile.TemporaryDirectory(prefix='delivery-v4-') as temp:
            config = Path(temp) / 'config'
            shutil.copytree(ROOT / 'config', config)
            command = ['bwrap', '--die-with-parent', '--unshare-pid', '--unshare-net', '--ro-bind', '/', '/',
                '--tmpfs', '/tmp', '--tmpfs', str(ROOT / 'data'), '--tmpfs', str(ROOT / 'logs'),
                '--bind', str(config), str(ROOT / 'config'), '--bind', str(output), '/tmp/artifacts',
                '--proc', '/proc', '--dev', '/dev', '--chdir', str(ROOT),
                '--setenv', 'RUNTIME_DIALOGUE_PARENT_NET', os.readlink('/proc/self/ns/net'),
                '--setenv', 'PYTHONDONTWRITEBYTECODE', '1', str(ROOT / '.venv/bin/python'), '-O', str(Path(__file__).resolve()),
                '--worker', '/tmp/artifacts/input.json', '--output', '/tmp/artifacts/report.json']
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
            (output / 'worker.log').write_text(result.stdout + result.stderr)
            require(result.returncode == 0 and (output / 'report.json').exists(), '隔离 worker 失败，见私有日志')
        result = json.loads((output / 'report.json').read_text())
        rows = [r for s in result['scenarios'].values() for r in s['turns']]
        require(len(rows) == sum(len(s['turns']) for s in cases['scenarios']), '结果总数不符')
        result.update(status='complete', counts=dict(Counter(r['status'] for r in rows)), total_turns=len(rows),
            raw_response_sha256=raw_hashes, source_report_sha256=sha(source), fixture_sha256=sha(cases_path),
            script_sha256=sha(Path(__file__)), source_report=str(source),
            limitations=['无模型重跑、无 Telegram、无服务启动；本地 transport 成功仅为模拟成功',
                        '合成会话/真实输入；无生产画像、Hook、队列生命周期或 send_service 提交',
                        '每场景独立 codec，场景内连续状态；零 typing 延迟、真实单调时钟紧邻回放，非原始时间线',
                        '默认 guard/budget 未放宽；保留 humanize；真实历史工厂及 replyer/OpenAI 转换',
                        '生产 driver 顶层 observations/metadata 传递缺口不在本次修复范围'])
        require(not any(n == 'src' or n.startswith('src.') for n in sys.modules), '父进程生产导入')
        save(output / 'report.json', result)
    finally:
        after = manifest()
        save(output / 'source-after.json', after)
        require(before == after, '受保护文件改变')
    result['protected_manifest_unchanged'] = True
    save(output / 'report.json', result)
    print(json.dumps({'output': str(output), 'counts': result['counts'], 'total_turns': result['total_turns']}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--cases', type=Path, default=DEFAULT_CASES)
    parser.add_argument('--output', type=Path, default=Path('/root/maibot-delivery-v4'))
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if args.worker:
        asyncio.run(worker(json.loads(args.worker.read_text()), args.output))
    else:
        run(args.source, args.cases, args.output)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('FAILED', type(exc).__name__, str(exc), file=sys.stderr)
        raise SystemExit(1) from None

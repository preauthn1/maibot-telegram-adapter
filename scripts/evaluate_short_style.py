"""短回复提示的小样本配对实测；不导入或启动 MaiBot 服务。"""
import ast
import json
import tomllib
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
import requests
from dialogue_eval_metadata import completion_status
from evaluate_dialogue_smoke import build_identity_prompt_block


def main():
    tree = ast.parse(Path('src/chat/replyer/maisaka_generator_base.py').read_text())
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_build_requested_reply_style_message')
    styles = next(ast.literal_eval(n.value) for n in ast.walk(method) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'style_messages' for t in n.targets))
    variants = {'old': '请简短的回复，允许句子残缺，奇怪表达，倒装，省略，符合口语习惯，符合省力随意回复习惯', 'current': styles['简短表达']}
    cases = [
        ('ownership', '小林养猫，我养狗。只回复“我养狗，不养猫”，不加其他文字。', '我养狗，不养猫'),
        ('condition', '只有备份完成且恢复验证通过，才能删除旧库。请原样回复：备份完成且恢复验证通过后才能删除旧库。', '备份完成且恢复验证通过后才能删除旧库。'),
        ('negation', '检测不到本地端口监听，不代表远程服务停止。只回复：不能据此确定远程服务停止。', '不能据此确定远程服务停止。'),
    ]
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--open', action='store_true', dest='open_cases')
    parser.add_argument('--task-last', action='store_true', help='两组都使用当前生产装配的任务末尾顺序')
    parser.add_argument('--timeout', type=float, default=60.0)
    args = parser.parse_args()
    import math
    import time
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be finite and positive')
    if args.open_cases:
        cases = [
            ('ownership', '小林的猫叫团团，我的狗叫豆包。帮我简短介绍一下我们各自的宠物。', None),
            ('condition', '迁移完成了，但备份还没做恢复验证。负责人说只有备份完成且恢复验证通过才能删旧库。我现在可以删吗？简短说清理由。', None),
            ('negation', '我在笔记本上没看到端口监听，应用实际部署在远程服务器。这能证明应用停止了吗？简短说清楚。', None),
            ('emotion', '今天投稿被拒了，有点失落。不想听建议，也别替我推测准备过程，陪我说一句就好。', None),
        ]
    cfg = tomllib.loads(Path('config/model_config.toml').read_text())
    task = cfg['model_task_config']['replyer']
    model = next(m for m in cfg['models'] if m['name'] == task['model_list'][0])
    provider = next(p for p in cfg['api_providers'] if p['name'] == model['api_provider'])
    if provider.get('auth_type') != 'bearer' or provider.get('client_type') != 'openai':
        raise ValueError('unsupported provider')
    out = Path('data/dialogue-evaluations') / ('short-style-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    out.mkdir(parents=True)
    report = {'scope': 'synthetic prompt comparison; not full MaiBot runtime', 'suite': 'open_short_v1' if args.open_cases else 'exact_short_v1', 'variants': variants, 'records': []}
    for index, (name, text, expected) in enumerate(cases):
        for variant in (['old', 'current'] if index % 2 == 0 else ['current', 'old']):
            messages = [{'role': 'system', 'content': build_identity_prompt_block('测试助手')}, {'role': 'user', 'content': text}, {'role': 'user', 'content': variants[variant]}]
            if args.task_last:
                messages[1], messages[2] = messages[2], messages[1]
            report['message_order'] = 'style_then_task' if args.task_last else 'task_then_style'
            body = dict(model.get('extra_params', {}))
            body.update(model=model['model_identifier'], messages=messages, temperature=task['temperature'], max_tokens=task['max_tokens'], stream=False)
            row = {'case': name, 'variant': variant, 'messages': messages, 'expected': expected, 'temperature': body['temperature'], 'max_tokens': body['max_tokens']}
            row['read_timeout_seconds'] = args.timeout
            started = time.monotonic()
            try:
                response = requests.post(provider['base_url'].rstrip('/') + '/chat/completions', headers={'Authorization': 'Bearer ' + provider['api_key']}, json=body, timeout=(10, args.timeout))
                row['http_status'] = response.status_code
                response.raise_for_status()
                data = response.json()
                choice = data['choices'][0]
                row.update(output=choice['message'].get('content'), finish_reason=choice.get('finish_reason'), response_model=data.get('model'))
                row['completion_status'] = completion_status(row['output'], row['finish_reason'])
                row['exact_pass'] = (row['completion_status'] == 'complete' and row['output'] == expected) if expected is not None else None
            except Exception as exc:
                row.update(completion_status='error', error_type=type(exc).__name__, exact_pass=False)
            row['elapsed_seconds'] = round(time.monotonic() - started, 3)
            report['records'].append(row)
            (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    expected_records = len(cases) * len(variants)
    complete_records = sum(r['completion_status'] == 'complete' for r in report['records'])
    report['execution'] = {'expected_records': expected_records, 'complete_records': complete_records,
                           'status': 'complete' if complete_records == expected_records else 'incomplete'}
    (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(out / 'result.json')
    print(json.dumps([{k: r.get(k) for k in ('case', 'variant', 'output', 'completion_status', 'exact_pass', 'error_type')} for r in report['records']], ensure_ascii=False))


    return 0 if complete_records == expected_records else 1


if __name__ == '__main__':
    raise SystemExit(main())

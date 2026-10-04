"""对隔离导出的合成提示进行真实 SDK 外呼，不导入 MaiBot 运行时。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import tomllib
from uuid import uuid4
from openai import OpenAI


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--stream', action='store_true', help='真实 SSE 外呼与完整正文汇总')
    parser.add_argument('--disable-thinking', action='store_true', help='实验性请求参数，不修改生产配置')
    parser.add_argument('--empty-stream-fallback', action='store_true', help='仅实验：空正文无工具时非流式重试一次')
    args = parser.parse_args()
    if args.empty_stream_fallback and not args.stream:
        parser.error('fallback requires --stream')
    sources = sorted(args.source.glob('assembled-*.json'))
    if len(sources) != 3:
        raise ValueError('Expected three assembled synthetic prompts')
    records = [json.loads(p.read_text()) for p in sources]
    if len({r['sample_id'] for r in records}) != 3:
        raise ValueError('Duplicate sample identity')
    if any(r['scope'] != 'real assembly with synthetic profile/selection; not production user configuration' for r in records):
        raise ValueError('Unexpected input scope')
    cfg = tomllib.loads(Path('config/model_config.toml').read_text())
    task = cfg['model_task_config']['replyer']
    model = next(m for m in cfg['models'] if m['name'] == task['model_list'][0])
    provider = next(p for p in cfg['api_providers'] if p['name'] == model['api_provider'])
    if provider.get('auth_type') != 'bearer' or provider.get('client_type') != 'openai':
        raise ValueError('Unsupported provider')
    out = args.source / ('live-assembled-' + uuid4().hex[:8])
    out.mkdir(mode=0o700)
    results = []
    with OpenAI(api_key=provider['api_key'], base_url=provider['base_url'], timeout=120, max_retries=0) as client:
        for source, record in zip(sources, records):
            row = {'sample_id':record['sample_id'], 'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                   'expected':record['expected'], 'passed':False, 'stream':args.stream}
            start = time.monotonic()
            try:
                body = dict(model.get('extra_params', {}))
                body.update(model=model['model_identifier'], messages=record['messages'],
                            temperature=task['temperature'], max_tokens=task['max_tokens'], stream=args.stream)
                if args.disable_thinking:
                    body['thinking'] = {'type': 'disabled'}
                row['experimental_thinking_disabled'] = args.disable_thinking
                keys = ('model','messages','temperature','max_tokens','stream')
                response = client.chat.completions.create(**{k:body[k] for k in keys},
                    extra_body={k:v for k,v in body.items() if k not in keys})
                if args.stream:
                    row.update(output='', finish_reason=None, usage=None, chunks=0, event_shapes=[])
                    with response:
                        for event in response:
                            row['chunks'] += 1
                            # 只记录字段形状和长度，不保存推理正文或未知扩展字段的值。
                            row['event_shapes'].append({'choices': [
                                {'index': c.index, 'finish_reason': c.finish_reason,
                                 'delta_fields': {k: {'type': type(v).__name__,
                                     'length': len(v) if isinstance(v, (str, list, dict)) else None}
                                     for k, v in c.delta.model_dump(exclude_none=True).items()}}
                                for c in event.choices]})
                            row['response_model'] = event.model
                            if event.usage:
                                row['usage'] = event.usage.model_dump()
                            for choice in event.choices:
                                if choice.index != 0:
                                    continue
                                row['output'] += choice.delta.content or ''
                                if choice.finish_reason:
                                    row['finish_reason'] = choice.finish_reason
                else:
                    choice = response.choices[0]
                    row.update(output=choice.message.content, finish_reason=choice.finish_reason,
                               response_model=response.model, usage=response.usage.model_dump() if response.usage else None)
                if (args.empty_stream_fallback and not row['output'].strip()
                        and row['finish_reason'] == 'stop'
                        and not any('tool_calls' in c['delta_fields'] or 'function_call' in c['delta_fields']
                                    or 'refusal' in c['delta_fields']
                                    for e in row['event_shapes'] for c in e['choices'])):
                    row['stream_attempt'] = {k: row.get(k) for k in ('output','finish_reason','usage','response_model','chunks')}
                    row['fallback_attempted'] = True
                    # 首轮已归档；第二轮失败时不得沿用首轮用量造成重复计费统计。
                    row.update(output='', finish_reason=None, usage=None, response_model=None)
                    fallback_body = dict(body)
                    fallback_body['stream'] = False
                    # SSE 专用参数不能随非流式回退发送，否则严格上游会拒绝请求。
                    fallback_body.pop('stream_options', None)
                    fallback = client.chat.completions.create(**{k:fallback_body[k] for k in keys},
                        extra_body={k:v for k,v in fallback_body.items() if k not in keys})
                    choice = fallback.choices[0]
                    row.update(output=choice.message.content, finish_reason=choice.finish_reason,
                               response_model=fallback.model, usage=fallback.usage.model_dump() if fallback.usage else None)
                row['passed'] = row['finish_reason'] == 'stop' and row['output'] == record['expected']
            except Exception as exc:
                row['error_type'] = type(exc).__name__
            row['elapsed_seconds'] = time.monotonic() - start
            results.append(row)
            path = out / 'results.json'
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as handle:
                json.dump({'scope':'live SDK with exported synthetic runtime assembly; not production deployment',
                           'results':results}, handle, ensure_ascii=False, indent=2)
    print(json.dumps({'directory':str(out), 'count':len(results), 'passed':sum(r['passed'] for r in results)}, ensure_ascii=False))
    if not all(r['passed'] for r in results):
        raise SystemExit(1)

if __name__ == '__main__':
    main()

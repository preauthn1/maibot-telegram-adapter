"""固定事实回答的指令和原历史，仅移除实验事实消息做对照。"""
from pathlib import Path
from uuid import uuid4
from openai import OpenAI
import argparse
import hashlib
import json
import os
import tomllib


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--source-quotes', action='store_true', help='用相同引用原文代替结构化事实，诊断重复证据的作用')
    parser.add_argument('--repeat-candidate', action='store_true', help='重复原候选请求，检查单次改善是否稳定')
    args = parser.parse_args()
    if args.repeat_candidate and args.source_quotes:
        parser.error('Choose one control mode')
    raw = args.candidate.read_bytes()
    candidate = json.loads(raw)
    messages = candidate['messages']
    removed = []
    control = []
    for index, message in enumerate(messages):
        try:
            data = json.loads(message['content']) if message['role'] == 'user' else None
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict) and set(data) == {'experimental_fact_records'}:
            removed.append(index)
            if args.source_quotes:
                citations = []
                for fact in data['experimental_fact_records']:
                    for citation in fact['evidence']:
                        if citation not in citations:
                            citations.append(citation)
                control.append({'role':'user','content':json.dumps(
                    {'experimental_source_quotes':citations},ensure_ascii=False)})
        else:
            control.append(message)
    if len(removed) != 1:
        raise ValueError('Expected exactly one experimental fact message')
    if args.repeat_candidate:
        control = messages
        removed = []
    cfg = tomllib.loads(Path('config/model_config.toml').read_text())
    task = cfg['model_task_config']['replyer']
    model = next(m for m in cfg['models'] if m['name'] == task['model_list'][0])
    provider = next(p for p in cfg['api_providers'] if p['name'] == model['api_provider'])
    result = {'scope':'same instruction and dialogue; fact-message ablation only; not plain production baseline',
              'candidate_sha256':hashlib.sha256(raw).hexdigest(), 'removed_indices':removed,
              'messages':control, 'semantic_review':'pending',
              'control_mode':'repeat_candidate' if args.repeat_candidate else ('source_quotes' if args.source_quotes else 'omit_facts')}
    out = args.candidate.parent / ('control-' + uuid4().hex[:8])
    out.mkdir(mode=0o700)
    try:
        with OpenAI(api_key=provider['api_key'],base_url=provider['base_url'],timeout=120,max_retries=0) as client:
            response = client.chat.completions.create(model=model['model_identifier'], messages=control,
                temperature=0,max_tokens=task['max_tokens'],stream=False)
        choice = next(c for c in response.choices if c.index == 0)
        result.update(output=choice.message.content,finish_reason=choice.finish_reason,
                      usage=response.usage.model_dump() if response.usage else None)
        if not choice.message.content or choice.finish_reason != 'stop':
            raise ValueError('Incomplete response')
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    with os.fdopen(os.open(out/'results.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:
        json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'directory':str(out),'output':result.get('output'),'error_type':result.get('error_type')},ensure_ascii=False))
    if 'error_type' in result:
        raise SystemExit(1)

if __name__ == '__main__':
    main()

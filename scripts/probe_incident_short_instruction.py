"""实际事故历史固定，仅替换末条短答指令；不调用 Telegram 或导入运行时。"""
import argparse
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import tomllib
from uuid import uuid4
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
OLD = '请简短的回复，允许句子残缺，奇怪表达，倒装，省略，符合口语习惯，符合省力随意回复习惯'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--planner-reason-only', action='store_true', help='固定短答指令，仅替换规划理由，诊断事实概括遗漏')
    args = parser.parse_args()
    raw = args.snapshot.read_bytes()
    snapshot = json.loads(raw)
    attempt = snapshot['generation_attempts'][-1]
    wire = attempt['wire_request']
    messages = wire['messages']
    if not messages or messages[-1] != {'role': 'user', 'content': OLD}:
        raise ValueError('Unexpected last message; refuse ambiguous edit')
    tree = ast.parse((ROOT/'src/chat/replyer/maisaka_generator_base.py').read_text())
    replacements = [v.value for node in ast.walk(tree) if isinstance(node, ast.Dict)
                    for k, v in zip(node.keys, node.values)
                    if isinstance(k, ast.Constant) and k.value == '简短表达' and isinstance(v, ast.Constant)]
    if len(replacements) != 1:
        raise ValueError('Short instruction lookup ambiguous')
    candidate = copy.deepcopy(messages)
    candidate[-1]['content'] = replacements[0]
    if candidate[:-1] != messages[:-1]:
        raise ValueError('History changed')
    changed_index = len(messages) - 1
    if args.planner_reason_only:
        old_reason = '用户质疑麦麦是否亲测过。麦麦此前说的是官方免费额度，属于公开数据，不应虚构亲测经历。如实说明即可，不与对方争辩。'
        indices = [i for i,m in enumerate(messages) if m.get('content') == old_reason]
        if len(indices) != 1:
            raise ValueError('Planner reason mismatch')
        changed_index = indices[0]
        candidate = copy.deepcopy(messages)
        candidate[changed_index]['content'] = ('用户质疑此前“看视频分片很容易打满”的实际依据。此前发言不只有额度数字，'
            '还包含具体使用场景会迅速耗尽的推断；当前没有实测记录支持该推断。'
            '回答是否实测，并明确撤回缺乏依据的使用结论；不重复额度来替代证据，也不未经核验认定对方结论正确。')
    if any(a != b for i,(a,b) in enumerate(zip(messages,candidate)) if i != changed_index):
        raise ValueError('Unexpected additional change')
    cfg = tomllib.loads((ROOT/'config/model_config.toml').read_text())
    task = cfg['model_task_config']['replyer']
    model = next(m for m in cfg['models'] if m['name'] == task['model_list'][0])
    provider = next(p for p in cfg['api_providers'] if p['name'] == model['api_provider'])
    out = ROOT/'data/dialogue-evaluations'/('incident-short-ablation-'+uuid4().hex[:8])
    out.mkdir(mode=0o700)
    results = []
    for arm, current in [('old_short', messages), ('corrected_planner_reason' if args.planner_reason_only else 'current_short', candidate)]:
        result: dict = {'arm': arm, 'messages_sha256': hashlib.sha256(json.dumps(current,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
        try:
            # 同一当前配置模型、非流式、无隐式重试；不是历史供应商与全部参数复现。
            with OpenAI(api_key=provider['api_key'], base_url=provider['base_url'], timeout=120, max_retries=0) as client:
                response = client.chat.completions.create(model=model['model_identifier'],messages=current,temperature=0,max_tokens=task['max_tokens'],stream=False)
            choice = next(c for c in response.choices if c.index == 0)
            result.update(output=choice.message.content, finish_reason=choice.finish_reason)
            result['usage'] = {k:getattr(response.usage,k,None) for k in ('prompt_tokens','completion_tokens','total_tokens')}
            if not choice.message.content or choice.finish_reason != 'stop':
                raise ValueError('Incomplete response')
        except Exception as exc:
            result['error_type'] = type(exc).__name__
        results.append(result)
        with os.fdopen(os.open(out/(arm+'.json'),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as f:
            json.dump(result,f,ensure_ascii=False,indent=2)
    report = {'scope':'actual recorded messages; one selected message replaced; current provider settings; no Telegram send', 'snapshot_sha256':hashlib.sha256(raw).hexdigest(), 'changed_index': changed_index, 'only_selected_message_changed': all(a == b for i,(a,b) in enumerate(zip(messages,candidate)) if i != changed_index), 'mode': 'planner_reason' if args.planner_reason_only else 'short_instruction', 'message_count':len(messages), 'results':results}
    with os.fdopen(os.open(out/'report.json',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps({'directory':str(out),**report},ensure_ascii=False))
    return int(any('error_type' in r for r in results))

if __name__ == '__main__':
    raise SystemExit(main())

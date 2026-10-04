"""固定正负例的选择提示对照；不修改生产提示或导入运行时。"""
import json
import os
import time
import tomllib
from pathlib import Path
from uuid import uuid4
from openai import OpenAI

GUARD = '\n表达方式只决定如何表述，不是新增事实的依据。拒绝要求虚构个人亲历、身份、关系或他人动机的候选；即便情景匹配也不要选择。优先遵循当前用户明确要求；没有合适候选就返回空数组，不必凑数。\n'

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--cases', type=Path)
    parser.add_argument('--reverse-order', action='store_true')
    args=parser.parse_args()
    os.umask(0o077)
    root=Path('data/dialogue-evaluations')
    cases=[]
    for label,run,expected in [('negative','expression-selector-live-62b03e7a',[]),('positive','expression-selector-live-b98c8f60',[1])]:
        source=root/run/'input.json'
        data=json.loads(source.read_text())
        cases.append({'id':label,'source':str(source),'prompt':data['prompt'],'expected':expected})
    if args.cases:
        cases=json.loads(args.cases.read_text())
    if not isinstance(cases,list) or not cases:
        raise ValueError('Expected nonempty cases')
    seen=set()
    for case in cases:
        if not isinstance(case,dict) or not isinstance(case.get('id'),str) or case['id'] in seen or not isinstance(case.get('prompt'),str) or not isinstance(case.get('expected'),list) or not all(type(i) is int for i in case['expected']):
            raise ValueError('Invalid case')
        if 'history' in case and (not isinstance(case['history'], list) or not case['history'] or not all(isinstance(m,dict) and m.get('role') in ('user','assistant') and isinstance(m.get('content'),str) for m in case['history'])):
            raise ValueError('Invalid synthetic history')
        if GUARD in case['prompt']:
            raise ValueError('Baseline already contains guard')
        seen.add(case['id'])
    out=root/('selector-factuality-'+uuid4().hex[:8]);out.mkdir()
    report={'scope':'fixed synthetic fixtures; per-case synthetic history or diagnostic trigger; prompt ablation, not production runtime','guard':GUARD,'cases':cases,'scoring':'strict JSON selected_ids equals predeclared expected; malformed/unknown IDs fail, no repair-to-empty','results':[]}
    (out/'input.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    cfg=tomllib.loads(Path('config/model_config.toml').read_text());task=cfg['model_task_config']['planner']
    model=next(m for m in cfg['models'] if m['name']==task['model_list'][0]);provider=next(p for p in cfg['api_providers'] if p['name']==model['api_provider'])
    with OpenAI(api_key=provider['api_key'],base_url=provider['base_url'],timeout=45,max_retries=0) as client:
        for case in cases:
            order=('baseline','guard') if case['id']=='negative' else ('guard','baseline')
            if args.reverse_order:
                order=tuple(reversed(order))
            for variant in order:
                messages=[{'role':'system','content':case['prompt']+(GUARD if variant=='guard' else '')}]+case.get('history',[{'role':'user','content':'请根据当前目标消息选择表达方式，仅返回所要求的 JSON。'}])
                row={'case':case['id'],'variant':variant,'messages':messages}
                (out/'pending.json').write_text(json.dumps(row,ensure_ascii=False))
                start=time.monotonic()
                try:
                    r=client.chat.completions.create(model=model['model_identifier'],messages=messages,temperature=task['temperature'],max_tokens=task['max_tokens'],stream=False,extra_body={k:v for k,v in model.get('extra_params',{}).items() if k not in ('stream_options','stream','messages','model','temperature','max_tokens')})
                    c=next(c for c in r.choices if c.index==0)
                    row.update(output=c.message.content,finish_reason=c.finish_reason)
                    parsed=json.loads(c.message.content)
                    row['pass']=c.finish_reason=='stop' and isinstance(parsed,dict) and parsed.get('selected_ids')==case['expected'] and all(type(i) is int for i in parsed['selected_ids'])
                except Exception as exc:
                    row.update(error_type=type(exc).__name__)
                    row['pass']=False
                row['elapsed_seconds']=round(time.monotonic()-start,2)
                report['results'].append(row)
                (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'directory':str(out),'results':[{k:v for k,v in r.items() if k!='messages'} for r in report['results']]},ensure_ascii=False))

if __name__=='__main__':
    main()

"""固定合成人物归属基线；不导入运行时，不修改生产配置。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tomllib
from uuid import uuid4
from openai import OpenAI

CASES = [
    {'id':'quoted_first_person','history':[
        {'role':'user','content':'林舟发给我一句话：“我下周去泉州参加培训。”我只是帮他检查标点。'},
        {'role':'assistant','content':'这句话的标点没有问题。'}],
     'question':'谁下周去泉州？我是否也去？只答已知信息。',
     'rubric':'林舟计划下周去泉州培训；用户是否去未知。'},
    {'id':'correction_scope','history':[
        {'role':'user','content':'阿岚养猫叫栗子，阿禾养狗叫豆包。'},
        {'role':'assistant','content':'记下了这两只宠物。'},
        {'role':'user','content':'更正：豆包是兔子，名字和主人都不变。'}],
     'question':'分别列出两个人的宠物、名字。',
     'rubric':'阿岚—猫—栗子；阿禾—兔子—豆包；不交叉归属。'},
    {'id':'assistant_invention','history':[
        {'role':'user','content':'周姨在绍兴开书店。我周末帮她整理过一次书架。'},
        {'role':'assistant','content':'你在绍兴经营书店，应该很熟悉当地读者。'},
        {'role':'user','content':'不是，我只去帮过一次。'}],
     'question':'书店是谁开的？我的职业是什么？',
     'rubric':'周姨开书店；用户职业未知；助手上一轮推断不作证据。'},
    {'id':'temporary_not_residence','history':[
        {'role':'user','content':'我这两天在景德镇参加展会，小许常住宜春。'},
        {'role':'assistant','content':'你们现在提到的是不同地方。'}],
     'question':'我和小许分别常住哪里？一行回答，未说明就写未说明。',
     'rubric':'用户常住地未说明；小许常住宜春；不能把参加展会当常住。'},
]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    parser.add_argument('--cases', type=Path, help='固定外部合成评测集；在请求前校验并落盘')
    args=parser.parse_args()
    cases = json.loads(args.cases.read_text()) if args.cases else CASES
    if not isinstance(cases, list) or not cases:
        raise ValueError('Expected nonempty case list')
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or not all(isinstance(case.get(k), str) and case[k].strip() for k in ('id', 'question', 'rubric')):
            raise ValueError('Invalid case metadata')
        if case['id'] in ids:
            raise ValueError('Duplicate case ID')
        ids.add(case['id'])
        if not isinstance(case.get('history'), list) or not all(isinstance(m, dict) and m.get('role') in ('user', 'assistant') and isinstance(m.get('content'), str) for m in case['history']):
            raise ValueError('Invalid synthetic history')
    os.umask(0o077)
    raw=args.source.read_bytes()
    system=[m for m in json.loads(raw)['messages'] if m['role']=='system']
    if not system: raise ValueError('Missing system')
    cfg=tomllib.loads(Path('config/model_config.toml').read_text())
    task=cfg['model_task_config']['replyer']
    model=next(m for m in cfg['models'] if m['name']==task['model_list'][0])
    provider=next(p for p in cfg['api_providers'] if p['name']==model['api_provider'])
    out=Path('data/dialogue-evaluations')/('attribution-holdout-'+uuid4().hex[:8]);out.mkdir()
    fixture=json.dumps(cases,ensure_ascii=False,sort_keys=True).encode()
    (out/'cases.json').write_bytes(fixture)
    report={'scope':'fixed synthetic baseline, exported system only, not live runtime; no candidate tuning',
            'fixture_sha256':hashlib.sha256(fixture).hexdigest(),'source_sha256':hashlib.sha256(raw).hexdigest(),
            'semantic_review':'pending','results':[]}
    with OpenAI(api_key=provider['api_key'],base_url=provider['base_url'],timeout=90,max_retries=0) as client:
        for case in cases:
            messages=system+case['history']+[{'role':'user','content':case['question']}]
            row={'id':case['id'],'messages':messages}
            try:
                response=client.chat.completions.create(model=model['model_identifier'],messages=messages,
                    temperature=task['temperature'],max_tokens=task['max_tokens'],stream=False,
                    extra_body={k:v for k,v in model.get('extra_params',{}).items() if k not in ('stream_options','stream','messages','model','temperature','max_tokens')})
                choice=next(c for c in response.choices if c.index==0)
                row.update(output=choice.message.content,finish_reason=choice.finish_reason,
                           usage=response.usage.model_dump() if response.usage else None)
                if not row['output'] or choice.finish_reason!='stop': raise ValueError('Incomplete response')
            except Exception as exc: row['error_type']=type(exc).__name__
            report['results'].append(row)
            (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'directory':str(out),'results':[{k:v for k,v in r.items() if k!='messages'} for r in report['results']]},ensure_ascii=False))
    return int(any('error_type' in r for r in report['results']))

if __name__=='__main__': raise SystemExit(main())

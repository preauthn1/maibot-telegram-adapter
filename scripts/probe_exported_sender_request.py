"""原样调用隔离导出的请求及仅去目标身份的消融；不导入应用。"""
import json, os, re, hashlib, tomllib, argparse
from pathlib import Path
from uuid import uuid4
from copy import deepcopy
from openai import OpenAI

def main():
    p=argparse.ArgumentParser()
    p.add_argument('source',type=Path)
    p.add_argument('--control-first', action='store_true', help='先运行去身份对照，检查固定调用顺序影响')
    p.add_argument('--model-name', help='本次评测选用已配置模型名，不修改生产路由')
    a=p.parse_args()
    os.umask(0o077)
    raw=a.source.read_bytes(); record=json.loads(raw)
    from sender_probe_inputs import build_pair
    pair = build_pair(record)
    cfg=tomllib.loads(Path('config/model_config.toml').read_text())
    task=cfg['model_task_config']['replyer']
    model_name = a.model_name or task['model_list'][0]
    model=next(m for m in cfg['models'] if m['name']==model_name)
    provider=next(p for p in cfg['api_providers'] if p['name']==model['api_provider'])
    out=a.source.parent/('sender-live-'+uuid4().hex[:8]); out.mkdir()
    order = ('without_target_identity','assembled') if a.control_first else ('assembled','without_target_identity')
    report={'scope':record['scope'],'source_sha256':hashlib.sha256(raw).hexdigest(),'order':order,'results':[],
            'model_name':model_name, 'model_identifier':model['model_identifier'],
            'temperature':task['temperature'], 'max_tokens':task['max_tokens'],
            'probe_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with OpenAI(api_key=provider['api_key'],base_url=provider['base_url'],timeout=90,max_retries=0) as client:
        for variant in order:
            messages=pair[variant]
            row={'variant':variant,'messages':messages}
            try:
                r=client.chat.completions.create(model=model['model_identifier'],messages=messages,
                    temperature=task['temperature'],max_tokens=task['max_tokens'],stream=False,
                    extra_body={k:v for k,v in model.get('extra_params',{}).items() if k not in ('stream_options','stream','model','messages','temperature','max_tokens')})
                c=next(c for c in r.choices if c.index==0)
                row.update(output=c.message.content,finish_reason=c.finish_reason)
                if not row['output'] or c.finish_reason!='stop': raise ValueError('Incomplete output')
            except Exception as e: row['error_type']=type(e).__name__
            report['results'].append(row)
            (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'directory':str(out),'results':[{k:v for k,v in r.items() if k!='messages'} for r in report['results']]},ensure_ascii=False))
    return int(any('error_type' in r for r in report['results']))
if __name__=='__main__': raise SystemExit(main())

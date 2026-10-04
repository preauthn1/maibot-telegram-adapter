"""发送完整人数候选请求；仅验证传输完成，语义另行审阅。"""
import json
import os
import sys
import tomllib
import hashlib
from pathlib import Path
from uuid import uuid4
from openai import OpenAI


def main():
    os.umask(0o077)
    base=Path(sys.argv[1])
    records=[]
    for variant in ('off','on'):
        raw=(base/f'assembled-count-{variant}.json').read_bytes()
        record=json.loads(raw)
        records.append((variant,record,hashlib.sha256(raw).hexdigest()))
    off,on=[r[1]['messages'] for r in records]
    assert off[0]==on[0] and off[-1]==on[-1]
    assert on[:-2]+on[-1:]==off
    cfg=tomllib.loads(Path('config/model_config.toml').read_text())
    task=cfg['model_task_config']['replyer']
    model=next(m for m in cfg['models'] if m['name']==task['model_list'][0])
    provider=next(p for p in cfg['api_providers'] if p['name']==model['api_provider'])
    out=base/('count-live-'+uuid4().hex[:8]);out.mkdir()
    report={'scope':records[0][1]['scope'],'only_style_message_differs':True,'results':[]}
    with OpenAI(api_key=provider['api_key'],base_url=provider['base_url'],timeout=90,max_retries=0) as client:
        for variant,record,digest in records:
            row={'variant':variant,'source_sha256':digest,'messages':record['messages']}
            (out/'pending.json').write_text(json.dumps(row,ensure_ascii=False))
            try:
                response=client.chat.completions.create(model=model['model_identifier'],messages=record['messages'],temperature=task['temperature'],max_tokens=task['max_tokens'],stream=False,extra_body={k:v for k,v in model.get('extra_params',{}).items() if k not in ('stream_options','stream','messages','model','temperature','max_tokens')})
                c=next(c for c in response.choices if c.index==0)
                row.update(output=c.message.content,finish_reason=c.finish_reason)
                row['response_complete']=c.finish_reason=='stop' and isinstance(c.message.content, str) and bool(c.message.content.strip())
                row['semantic_review']='pending'
            except Exception as exc:
                row['error_type']=type(exc).__name__
                row['response_complete']=False
            report['results'].append(row)
            (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'directory':str(out),'results':[{k:v for k,v in r.items() if k!='messages'} for r in report['results']]},ensure_ascii=False))
    return int(not all(r['response_complete'] for r in report['results']))

if __name__=='__main__':
    raise SystemExit(main())

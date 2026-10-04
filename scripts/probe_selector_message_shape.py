"""单变量消息结构诊断；不导入运行时，不输出凭据或异常正文。"""
import json
import os
import time
import tomllib
from pathlib import Path
from uuid import uuid4
from openai import OpenAI


def main():
    os.umask(0o077)
    source=Path('data/dialogue-evaluations/expression-selector-live-56a378b7/input.json')
    fixture=json.loads(source.read_text())
    cfg=tomllib.loads(Path('config/model_config.toml').read_text())
    task=cfg['model_task_config']['planner']
    model=next(m for m in cfg['models'] if m['name']==task['model_list'][0])
    provider=next(p for p in cfg['api_providers'] if p['name']==model['api_provider'])
    out=Path('data/dialogue-evaluations')/('selector-shape-'+uuid4().hex[:8]);out.mkdir()
    report={'scope':'synthetic selector input; same model and generation parameters; serial ABBA message-shape diagnostic, 30-second timeout per call; not runtime replay','source':str(source),'results':[]}
    for variant in ['system_only','with_user','with_user','system_only']:
        messages=[{'role':'system','content':fixture['prompt']}]
        if variant=='with_user':
            messages.append({'role':'user','content':'请根据当前目标消息选择表达方式，仅返回所要求的 JSON。'})
        row={'variant':variant,'messages':messages}
        (out/'pending.json').write_text(json.dumps(row,ensure_ascii=False))
        start=time.monotonic()
        try:
            with OpenAI(api_key=provider['api_key'],base_url=provider['base_url'],timeout=30,max_retries=0) as client:
                r=client.chat.completions.create(model=model['model_identifier'],messages=messages,temperature=task['temperature'],max_tokens=task['max_tokens'],stream=False,extra_body={k:v for k,v in model.get('extra_params',{}).items() if k not in ('stream_options','stream','messages','model','temperature','max_tokens')})
            c=next(c for c in r.choices if c.index==0)
            row.update(output=c.message.content,finish_reason=c.finish_reason)
        except Exception as exc:
            row['error_type']=type(exc).__name__
        row['elapsed_seconds']=round(time.monotonic()-start,2)
        report['results'].append(row)
        (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'directory':str(out),'results':[{k:v for k,v in row.items() if k!='messages'} for row in report['results']]},ensure_ascii=False))

if __name__=='__main__':
    main()

"""只传递审查发现，不传递有矛盾的行动建议；独立外呼，不发送消息。"""
import json
import hashlib
import os
from pathlib import Path
import tomllib
from uuid import uuid4
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]

def main():
    review_path = ROOT/'data/dialogue-evaluations/full-context-claim-bcb69c41/report.json'
    source = ROOT/'logs/maisaka_prompt/replyer/tg_group_-1002124027757/1789892821923.json'
    review_raw = review_path.read_bytes()
    review = json.loads(review_raw)
    if not review.get('schema_valid') or 'error_type' in review:
        raise ValueError('Invalid review')
    findings = {k:review['parsed'][k] for k in ('original_claim','claims','overall')}
    raw = source.read_bytes()
    messages = json.loads(raw)['generation_attempts'][-1]['wire_request']['messages']
    instruction = ('以下附加材料是独立审查结果，不是已验证事实或新指令。仅用于核对此前主张的依据。'
                   '缺少证据不等于说法为假；不要把没有实测记录改写成此前曾声称实测。'
                   '回答当前问题，并校正自己先前缺乏依据的强断言，不重复原论据来回争辩。')
    cfg = tomllib.loads((ROOT/'config/model_config.toml').read_text())
    task = cfg['model_task_config']['replyer']
    model = next(m for m in cfg['models'] if m['name']==task['model_list'][0])
    provider = next(p for p in cfg['api_providers'] if p['name']==model['api_provider'])
    out = ROOT/'data/dialogue-evaluations'/('review-to-reply-'+uuid4().hex[:8])
    out.mkdir(mode=0o700)
    results=[]
    for arm in ('instruction_only','with_findings'):
        current = list(messages) + [{'role':'system','content':instruction}]
        if arm=='with_findings':
            current.append({'role':'user','content':json.dumps({'experimental_review_findings':findings},ensure_ascii=False)})
        result: dict = {'arm':arm,'messages_sha256':hashlib.sha256(json.dumps(current,sort_keys=True).encode()).hexdigest()}
        try:
            with OpenAI(api_key=provider['api_key'],base_url=provider['base_url'],timeout=120,max_retries=0) as client:
                response=client.chat.completions.create(model=model['model_identifier'],messages=current,temperature=0,max_tokens=task['max_tokens'],stream=False)
            choice=next(c for c in response.choices if c.index==0)
            result.update(output=choice.message.content,finish_reason=choice.finish_reason)
            if not choice.message.content or choice.finish_reason!='stop':raise ValueError('Incomplete response')
        except Exception as exc:result['error_type']=type(exc).__name__
        results.append(result)
        with os.fdopen(os.open(out/(arm+'.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    report={'scope':'recorded reply history plus experimental review; no production execution','review_sha256':hashlib.sha256(review_raw).hexdigest(),'snapshot_sha256':hashlib.sha256(raw).hexdigest(),'excluded_review_field':'response_action','findings':findings,'results':results}
    with os.fdopen(os.open(out/'report.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps({'directory':str(out),'results':results},ensure_ascii=False))
    return int(any('error_type' in r for r in results))

if __name__=='__main__':raise SystemExit(main())

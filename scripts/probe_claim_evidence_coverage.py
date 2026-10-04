"""独立证据覆盖诊断；匿名样本，不执行工具、不改生产。"""
import json
import os
from pathlib import Path
import tomllib
from uuid import uuid4
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    {'id':'quota', 'claim':'官方免费额度就十万次，看视频分片很容易打满',
     'evidence':['某服务每日免费请求额度是十万次。'], 'expected':'partial'},
    {'id':'capacity', 'claim':'这块电池容量是5000毫安时，玩游戏肯定撑不过两小时',
     'evidence':['产品规格写明电池容量为5000毫安时。'], 'expected':'partial'},
    {'id':'measured', 'claim':'这次测试持续90分钟，消耗了30%的电量',
     'evidence':['测试记录：开始时间10:00，结束时间11:30；开始电量100%，结束电量70%。'], 'expected':'supported'},
]
INSTRUCTION = ('你是独立的证据覆盖检查器，不是原发言者。仅依据提供的材料，把主张拆成可独立核对的子主张。'
 '分别判断证据是否足以支持，不能把数字规格当成实际使用效果的证据，也不能因为有人质疑就否认已有证据。'
 '只输出JSON对象：claims数组，每项含claim、evidence、status（supported或unsupported）、missing；'
 'overall为supported、partial或unsupported。不要提供改写答案，不增加外部知识。')


def main():
    cfg = tomllib.loads((ROOT/'config/model_config.toml').read_text())
    task = cfg['model_task_config']['planner']
    model = next(m for m in cfg['models'] if m['name'] == task['model_list'][0])
    provider = next(p for p in cfg['api_providers'] if p['name'] == model['api_provider'])
    out = ROOT/'data/dialogue-evaluations'/('claim-coverage-'+uuid4().hex[:8])
    out.mkdir(mode=0o700)
    results = []
    for case in CASES:
        item = {'id':case['id'], 'input':{k:case[k] for k in ('claim','evidence')}, 'expected':case['expected']}
        try:
            with OpenAI(api_key=provider['api_key'],base_url=provider['base_url'],timeout=90,max_retries=0) as client:
                response = client.chat.completions.create(model=model['model_identifier'],messages=[
                    {'role':'system','content':INSTRUCTION},
                    {'role':'user','content':json.dumps(item['input'],ensure_ascii=False)}],
                    temperature=0,max_tokens=1600,stream=False,response_format={'type':'json_object'})
            choice = next(c for c in response.choices if c.index == 0)
            item['output'] = choice.message.content
            if choice.finish_reason != 'stop':
                raise ValueError('Incomplete response')
            parsed = json.loads(choice.message.content or '')
            if not isinstance(parsed,dict) or not isinstance(parsed.get('claims'),list) or not parsed['claims']:
                raise ValueError('Invalid result schema')
            item['parsed'] = parsed
            item['label_match'] = parsed.get('overall') == case['expected']
            item['usage'] = {k:getattr(response.usage,k,None) for k in ('prompt_tokens','completion_tokens','total_tokens')}
        except Exception as exc:
            item['error_type'] = type(exc).__name__
        results.append(item)
        with os.fdopen(os.open(out/(case['id']+'.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:
            json.dump(item,f,ensure_ascii=False,indent=2)
    report = {'scope':'independent diagnostic; provided quota premise not externally verified; no production integration',
              'instruction':INSTRUCTION,'results':results,'count':len(results),
              'label_matches':sum(r.get('label_match',False) for r in results)}
    with os.fdopen(os.open(out/'report.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps({'directory':str(out),**report},ensure_ascii=False))
    return int(any('error_type' in r for r in results))

if __name__ == '__main__':
    raise SystemExit(main())

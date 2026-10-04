"""仅诊断：从原始用户消息抽取带逐字证据的事实，不注入生产。"""
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
    parser.add_argument('report', type=Path)
    parser.add_argument('--question-blind', action='store_true', help='诊断：抽取时不提供末轮问题，隔离问题预设影响')
    parser.add_argument('--fixed-instruction', action='store_true', help='配对诊断：无论是否提供问题均使用同一抽取指令')
    parser.add_argument('--evidence-chain', action='store_true', help='诊断：每项事实提供初始陈述与纠正的引用链')
    args = parser.parse_args()
    raw = args.report.read_bytes()
    report = json.loads(raw)
    messages = report['turns'][-1]['messages']
    users = [{'id':i, 'text':m['content']} for i,m in enumerate(messages)
             if m['role'] == 'user']
    # 最后一条问题独立标识；疑问句的预设不能成为事实证据。
    evidence = users[:-1]
    cfg = tomllib.loads(Path('config/model_config.toml').read_text())
    task = cfg['model_task_config']['replyer']
    model = next(m for m in cfg['models'] if m['name'] == task['model_list'][0])
    provider = next(p for p in cfg['api_providers'] if p['name'] == model['api_provider'])
    out = args.report.parent / ('fact-extraction-' + uuid4().hex[:8])
    out.mkdir(mode=0o700)
    result = {'scope':'diagnostic extraction only; no production injection',
              'source_sha256':hashlib.sha256(raw).hexdigest(), 'evidence':evidence,
              'question':users[-1]['text']}
    instruction = ('只从提供的用户陈述抽取与问题有关的事实，纠正覆盖原属性，不扩展关系。'
        '输出一个JSON对象，含facts数组和unknowns数组。每条fact含subject、relation、value、'
        'source_id、quote；quote必须逐字摘录对应用户陈述，且直接支持该关系。'
        'unknowns列出问题涉及但用户没有陈述的属性。问题本身不是证据。只输出JSON，不要代码围栏。')
    payload = {'statements':evidence}
    if not args.question_blind:
        payload['question'] = users[-1]['text']
    else:
        instruction = instruction.replace('与问题有关的事实', '明确陈述的个人事实').replace(
            'unknowns列出问题涉及但用户没有陈述的属性。问题本身不是证据。',
            '不要穷举未说明属性；unknowns可为空。')
    if args.fixed_instruction:
        instruction = ('只从statements抽取明确陈述的个人事实，纠正覆盖原属性，不扩展关系。'
            '可选question只作背景，不是事实来源，不改变抽取范围。输出JSON对象，含facts和unknowns数组。'
            '每条fact含subject、relation、value、source_id、quote；quote逐字摘录对应陈述。'
            '不要穷举未知属性，unknowns可为空。只输出JSON，不要代码围栏。')
    if args.evidence_chain:
        instruction += ('每项fact另加evidence数组，每项含source_id与quote。'
            '若关系来自较早陈述、值来自后来纠正，evidence必须同时引用两处，不得只引用纠正。'
            '原有source_id与quote保留为最新直接引用。')
    result['evidence_chain'] = args.evidence_chain
    result['fixed_instruction'] = args.fixed_instruction
    result['question_blind'] = args.question_blind
    result['request_payload'] = payload
    result['instruction'] = instruction
    try:
        with OpenAI(api_key=provider['api_key'],base_url=provider['base_url'],timeout=120,max_retries=0) as client:
            response = client.chat.completions.create(model=model['model_identifier'],
                messages=[{'role':'system','content':instruction},
                          {'role':'user','content':json.dumps(payload,ensure_ascii=False)}],
                temperature=0,max_tokens=task['max_tokens'],stream=False)
        choice = next(c for c in response.choices if c.index == 0)
        result['output'] = choice.message.content
        result['finish_reason'] = choice.finish_reason
        parsed = json.loads(choice.message.content or '')
        sources = {u['id']:u['text'] for u in evidence}
        facts = parsed['facts']
        if not isinstance(facts,list) or not isinstance(parsed['unknowns'],list) or choice.finish_reason != 'stop':
            raise ValueError('Invalid extraction structure')
        for fact in facts:
            for key in ('subject','relation','value','quote'):
                if not isinstance(fact[key],str) or not fact[key].strip():
                    raise ValueError('Empty fact field')
            if fact['quote'] not in sources[fact['source_id']]:
                raise ValueError('Evidence quote mismatch')
            if args.evidence_chain:
                chain = fact.get('evidence')
                if not isinstance(chain, list) or not chain:
                    raise ValueError('Missing evidence chain')
                for citation in chain:
                    if type(citation.get('source_id')) is not int or not isinstance(citation.get('quote'), str):
                        raise ValueError('Invalid chain citation')
                    if not citation['quote'].strip() or citation['quote'] not in sources[citation['source_id']]:
                        raise ValueError('Chain quote mismatch')
        result['quotes_verified'] = True
        result['semantic_support'] = 'pending; substring match does not prove entailment'
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    path = out/'results.json'
    with os.fdopen(os.open(path,os.O_CREAT|os.O_WRONLY|os.O_EXCL,0o600),'w') as f:
        json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'path':str(path),**result},ensure_ascii=False))
    if 'error_type' in result:
        raise SystemExit(1)

if __name__ == '__main__':
    main()

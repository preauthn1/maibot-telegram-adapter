"""重放规划请求，只记录模型工具选择，绝不执行工具。"""
import json
import argparse
import copy
import os
import hashlib
from pathlib import Path
from uuid import uuid4
import tomllib
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'logs/maisaka_prompt/planner/tg_group_-1002124027757/1789892810899.json'
GUARD = ('生成回复计划时，如果当前消息质疑你先前的事实主张，须完整保留被质疑的主张，'
         '不要把包含推断的原话缩写成其中较容易辩护的事实。区分可核实事实、推断和实测证据；'
         '历史助手断言不构成独立验证。reply_reference应指出哪些部分有依据、哪些缺乏依据，'
         '缺乏依据的强结论应建议撤回或限定；对方反驳本身也不是证明。不要以重复既有数字代替回答依据问题。')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--structured-review', action='store_true')
    args = parser.parse_args()
    raw = SOURCE.read_bytes()
    data = json.loads(raw)
    wire = data['generation_attempts'][-1]['wire_request']
    cfg = tomllib.loads((ROOT/'config/model_config.toml').read_text())
    task = cfg['model_task_config']['planner']
    model = next(m for m in cfg['models'] if m['name'] == task['model_list'][0])
    provider = next(p for p in cfg['api_providers'] if p['name'] == model['api_provider'])
    out = ROOT/'data/dialogue-evaluations'/('planner-claim-probe-'+uuid4().hex[:8])
    out.mkdir(mode=0o700)
    results = []
    for arm in (('structured_review',) if args.structured_review else ('baseline', 'claim_preservation')):
        tools = copy.deepcopy(wire['tools'])
        if arm == 'structured_review':
            reply = next(t['function'] for t in tools if t['function']['name'] == 'reply')
            parameters = reply['parameters']
            parameters['properties']['claim_review'] = {
                'type': 'object',
                'description': '仅用于内部审查：若本轮质疑先前回答，逐字提取被质疑的完整原话并区分证据与推断；否则填空字符串。不得只挑原话中容易辩护的一部分。',
                'properties': {k: {'type':'string','description':v} for k,v in {
                    'original_claim':'被质疑的完整原话，来自当前历史而非概括',
                    'available_evidence':'当前可见的独立证据，助手自己的断言不算',
                    'unsupported_inference':'未获证据支持的推断；没有则留空',
                    'response_action':'根据证据确定答复动作，不自动赞同质疑者'}.items()},
                'required':['original_claim','available_evidence','unsupported_inference','response_action']}
            parameters['required'] = list(parameters.get('required',[])) + ['claim_review']
        messages = list(wire['messages'])
        if arm == 'claim_preservation':
            messages.insert(1, {'role':'system','content':GUARD})
        result: dict = {'arm':arm, 'tool_schema':tools, 'messages_sha256':hashlib.sha256(json.dumps(messages,sort_keys=True).encode()).hexdigest()}
        try:
            with OpenAI(api_key=provider['api_key'],base_url=provider['base_url'],timeout=120,max_retries=0) as client:
                response = client.chat.completions.create(model=model['model_identifier'],messages=messages,tools=tools,temperature=0,max_tokens=task['max_tokens'],stream=False)
            choice = next(c for c in response.choices if c.index == 0)
            result.update(output=choice.message.content,finish_reason=choice.finish_reason,
                          tool_calls=[{'name':t.function.name,'arguments':t.function.arguments} for t in choice.message.tool_calls or [] if t.type == 'function'],
                          usage={k:getattr(response.usage,k,None) for k in ('prompt_tokens','completion_tokens','total_tokens')})
            if not choice.message.content and not choice.message.tool_calls:
                raise ValueError('No visible output or tool calls')
        except Exception as exc:
            result['error_type'] = type(exc).__name__
        results.append(result)
        with os.fdopen(os.open(out/(arm+'.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as handle:
            json.dump(result,handle,ensure_ascii=False,indent=2)
    report = {'source_sha256':hashlib.sha256(raw).hexdigest(),'scope':'recorded planner messages and tool schemas; current configured planner model; no tools executed', 'results':results}
    with os.fdopen(os.open(out/'report.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as handle:
        json.dump(report,handle,ensure_ascii=False,indent=2)
    print(json.dumps({'directory':str(out),**report},ensure_ascii=False))
    return int(any('error_type' in r for r in results))

if __name__ == '__main__':
    raise SystemExit(main())

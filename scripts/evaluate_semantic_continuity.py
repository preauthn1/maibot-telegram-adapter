"""真实多轮基线：复用隔离导出的 system，历史由本次模型真实返回构成。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tomllib
from uuid import uuid4
from openai import OpenAI


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--perspective-guard', action='store_true', help='仅实验：区分代写视角与对话事实归属')
    parser.add_argument('--replay-final', type=Path, help='固定已有报告最后一轮的用户/助手历史，隔离提示变量')
    parser.add_argument('--transfer', action='store_true', help='新场景：代写后切换人物及纠正归属')
    parser.add_argument('--fact-guard', action='store_true', help='仅实验：事实来源及属性边界')
    parser.add_argument('--neutral-location-probe', action='store_true', help='仅诊断：固定历史，移除最后问题的工作地预设')
    parser.add_argument('--omit-assistant-history', action='store_true', help='仅消融诊断：移除回放中的助手历史，不改变用户消息')
    parser.add_argument('--neutral-system', action='store_true', help='仅诊断：替换导出人设 system，不作为生产候选')
    parser.add_argument('--explicit-unknown-probe', action='store_true', help='仅诊断：明确用户工作地点未提供，检验错误前提抵抗')
    args = parser.parse_args()
    if args.explicit_unknown_probe and (not args.replay_final or args.neutral_location_probe):
        parser.error('--explicit-unknown-probe requires replay and the original final question')
    if args.neutral_system and not args.replay_final:
        parser.error('--neutral-system requires --replay-final')
    if args.omit_assistant_history and not args.replay_final:
        parser.error('--omit-assistant-history requires --replay-final')
    if args.neutral_location_probe and not args.replay_final:
        parser.error('--neutral-location-probe requires --replay-final')
    if args.fact_guard and args.perspective_guard:
        parser.error('Choose one experimental guard')
    if args.transfer and args.replay_final:
        parser.error('--transfer cannot be combined with --replay-final')
    raw = args.source.read_bytes()
    record = json.loads(raw)
    system = [m for m in record['messages'] if m['role'] == 'system']
    if not system:
        raise ValueError('Missing exported system')
    cfg = tomllib.loads(Path('config/model_config.toml').read_text())
    task = cfg['model_task_config']['replyer']
    model = next(m for m in cfg['models'] if m['name'] == task['model_list'][0])
    provider = next(p for p in cfg['api_providers'] if p['name'] == model['api_provider'])
    turns = [
        '我帮姐姐准备了三个月的面试，今天她没通过。我现在只想吐槽，先别给建议。',
        '刚才说错了，是两个月。她倒挺平静，我有点替她不甘心。',
        '先不聊这个了，帮我写一句发给她的话，别提准备时长，也别劝她再试一次。',
        '最后核对一下：谁参加面试、谁帮忙准备、准备多久？只用一行回答。',
    ]
    if args.transfer:
        turns = [
            '我弟弟在苏州工作，我在宁波。帮我用他的口吻写一句近况，只写一句，不添加没说过的经历。',
            '更正一下，他在无锡，不是苏州。我的城市不变。',
            '不代写了。今天我有点烦，只想聊两句，不要给解决方案。',
            '回到刚才的信息：分别说说我和弟弟在哪工作；没说过的不要补。',
        ]
    out = args.source.parent / ('semantic-continuity-' + uuid4().hex[:8])
    out.mkdir(mode=0o700)
    report = {'scope':'exported system only + fresh synthetic multi-turn dialogue; not full runtime reassembly',
              'source_sha256':hashlib.sha256(raw).hexdigest(), 'turns':[], 'semantic_review':'pending'}
    guard = '代写内容中的第一人称只属于委托者，不是助手的经历。结束代写后核对事实，用你、对方或明确称谓标明归属；只更新用户明确纠正的事实。回应情绪时区分谁有何种情绪，不默认事件当事人需要安慰。'
    if args.fact_guard:
        guard = '个人事实只依据用户明确陈述及纠正；助手先前代写或推测的内容不是新证据。不要从亲属称谓推断说话者性别，不要把所在地推成工作地或居住地。问题含未证实的前提时，简短指出已知和未说明的部分，不替用户补全。'
    report['suite'] = 'transfer_v1' if args.transfer else 'interview_v1'
    report['variant'] = 'fact_guard' if args.fact_guard else ('perspective_guard' if args.perspective_guard else 'baseline')
    report['experimental_instruction'] = guard if (args.perspective_guard or args.fact_guard) else None
    report['system_ablation'] = args.neutral_system
    history = ([{'role':'system','content':'你是中文对话助手。请准确回答用户当前的问题。'}]
               if args.neutral_system else list(system))
    if args.perspective_guard or args.fact_guard:
        history.append({'role':'system','content':guard})
    if args.replay_final:
        replay_bytes = args.replay_final.read_bytes()
        replay = json.loads(replay_bytes)
        if replay['source_sha256'] != report['source_sha256']:
            raise ValueError('Replay source mismatch')
        messages = replay['turns'][-1]['messages']
        dialogue = [m for m in messages if m['role'] in ('user', 'assistant')]
        if not dialogue or dialogue[-1]['role'] != 'user':
            raise ValueError('Replay must end in user request')
        prior = dialogue[:-1]
        report['omitted_assistant_messages'] = sum(m['role'] == 'assistant' for m in prior) if args.omit_assistant_history else 0
        if args.omit_assistant_history:
            prior = [m for m in prior if m['role'] != 'assistant']
        if args.explicit_unknown_probe:
            prior.append({'role':'user','content':'补充澄清：我只说了我在宁波，没有说我在哪工作，也没有说我的性别。'})
        report['explicit_unknown_probe'] = args.explicit_unknown_probe
        history.extend(prior)
        turns = [dialogue[-1]['content']]
        report['original_final_user'] = turns[0]
        report['diagnostic_probe'] = 'neutral_location' if args.neutral_location_probe else None
        if args.neutral_location_probe:
            turns = ['请分别列出我和弟弟已明确说过的地点信息，保留原来的关系，不补充未说明的信息。']
        report['suite'] = replay.get('suite', 'unspecified_replay')
        report['replay_sha256'] = hashlib.sha256(replay_bytes).hexdigest()
        report['scope'] = 'fixed prior dialogue replay; exported system only; not runtime reassembly'
    with OpenAI(api_key=provider['api_key'], base_url=provider['base_url'], timeout=120, max_retries=0) as client:
        for text in turns:
            history.append({'role':'user','content':text})
            row = {'user':text, 'messages':list(history)}
            try:
                response = client.chat.completions.create(model=model['model_identifier'], messages=history,
                    temperature=task['temperature'], max_tokens=task['max_tokens'], stream=False,
                    extra_body={k:v for k,v in model.get('extra_params',{}).items()
                                if k not in ('stream_options','stream','messages','model','temperature','max_tokens')})
                choice = next(c for c in response.choices if c.index == 0)
                row.update(output=choice.message.content, finish_reason=choice.finish_reason,
                           usage=response.usage.model_dump() if response.usage else None)
                if not choice.message.content or choice.finish_reason != 'stop':
                    raise ValueError('Incomplete visible response')
                history.append({'role':'assistant','content':choice.message.content})
            except Exception as exc:
                row['error_type'] = type(exc).__name__
            report['turns'].append(row)
            path = out/'results.json'
            with os.fdopen(os.open(path,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600),'w') as f:
                json.dump(report,f,ensure_ascii=False,indent=2)
            if 'error_type' in row:
                break
    print(json.dumps({'directory':str(out),'turns':len(report['turns']),
                      'outputs':[r.get('output') for r in report['turns']]},ensure_ascii=False))
    if len(report['turns']) != len(turns) or any('error_type' in r for r in report['turns']):
        raise SystemExit(1)

if __name__ == '__main__':
    main()

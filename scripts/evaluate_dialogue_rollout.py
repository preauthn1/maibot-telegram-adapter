"""连续真实生成回放：每轮历史只使用上一轮真实完整响应。"""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Any, Dict, List
import argparse
import json
import tomllib
import time

import requests
from evaluate_dialogue_smoke import build_identity_prompt_block
from dialogue_eval_metadata import completion_status, request_metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sdk', action='store_true', help='使用真实 OpenAI SDK 外呼；不导入生产运行时')
    parser.add_argument('--grounding', action='store_true')
    parser.add_argument('--heldout-grounding', action='store_true')
    parser.add_argument('--open-dialogue', action='store_true')
    parser.add_argument('--transfer', action='store_true', help='冻结的新迁移场景，不据结果改写候选')
    parser.add_argument('--runtime-history', action='store_true', help='经生产历史工厂和replyer转换回填真实助手响应')
    parser.add_argument('--intent-fit', action='store_true')
    parser.add_argument('--grounded-intent', action='store_true', help='独立实验候选，不写生产提示')
    parser.add_argument('--evidence-examples', action='store_true', help='独立事实边界示例候选，不发布')
    parser.add_argument('--relations', action='store_true', help='时间与归属关系回归')
    parser.add_argument('--paraphrase', action='store_true', help='无答案提示的事实复述')
    args = parser.parse_args()
    if args.runtime_history:
        parser.error('runtime-history 暂停：生产数据库路径基于源码目录，切换工作目录不足以隔离')
    # 在读取配置和创建产物前拒绝冲突，避免生成误标场景的实验记录。
    if sum((args.open_dialogue, args.heldout_grounding, args.transfer, args.relations, args.paraphrase)) > 1:
        parser.error('场景开关不能混用')
    if sum((args.intent_fit, args.grounding, args.grounded_intent, args.evidence_examples)) > 1:
        parser.error('实验规则单独比较，不混用')
    extra = (
        '\n共情只承接对方明确表达的处境，不添加失败阶段、持续时间、动机或共同经历。'
        '技术建议区分观察、假设和结论：检查必须说明适用位置或条件；单项未检出不等于已确定根因。'
        '优先给能取得直接证据的一步，不为了简短省掉关键适用条件。'
        if args.grounding else ''
    )
    if args.intent_fit:
        extra = ('\n先辨别当前这一轮是在分享趣事、表达感受还是请求信息。分享时回应趣味本身，'
                 '不因出现技术名词就自动科普原理、诊断或推荐购买；无需每次夸赞对方的表达。'
                 '明确求助时正常给有用信息；意图改变时随最新请求调整，不把闲聊规则当作永久禁令。')
    if args.grounded_intent:
        extra = ('\n回应当前交谈目的：分享趣事时接住趣味，明确求助时再提供信息；'
                 '不把技术名词自动当求助信号。共情不靠补写对方的准备、努力、动机或经历，'
                 '只承接已表达的事实和感受。遵守要求即可，不复述自己正在遵守哪些规则。')
    if args.evidence_examples:
        extra = ('\n以下示例只示范证据边界，不是当前用户的经历，也不是固定回复模板。'
                 '\n用户：实验失败了，只想吐槽。回应：唉，失败这一下真让人烦。'
                 '不要补写反复失败、准备很久或努力程度。'
                 '\n用户：网关报错，只给一步。回应：先看网关实际运行位置的对应错误日志，'
                 '用日志确认目标地址和失败阶段，再选检查；不要预设本机地址或协议。'
                 '\n连接拒绝只是某目标的连接结果，不等于已查明根因。'
                 '命令须适用于已知协议和执行位置；未知时说明条件。'
                 '其他聊天自然回应当前内容，不复述规则，不套示例台词。')
    config = tomllib.loads(Path('config/model_config.toml').read_text())
    task = config['model_task_config']['replyer']
    model = next(x for x in config['models'] if x['name'] == task['model_list'][0])
    provider = next(x for x in config['api_providers'] if x['name'] == model['api_provider'])
    if provider.get('auth_type') != 'bearer' or provider.get('client_type') != 'openai':
        raise ValueError('不支持此接口配置')
    run = Path('data/dialogue-evaluations') / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])
    run.mkdir(parents=True)
    scenarios = {
        'correction': ['我的测试环境是 Ubuntu，只确认收到这个信息。', '纠正一下，实际是 Alpine，不是 Ubuntu。只回复当前系统名称。', '现在把刚才撤回的系统名和当前系统名写成“旧→新”，不要加解释。'],
        'intent': ['部署失败真烦，我只想吐槽，不要建议也别追问。', '现在想解决了，Nginx 返回502，只给一个最小检查。', '先停，不排查了。只回“好”，不要继续建议。'],
    }
    if args.heldout_grounding:
        scenarios = {
            'emotion_unspecified': ['面试没通过，有点难受。只想说一下，不要建议也别追问。'],
            'emotion_explicit': ['我准备了三个月，连续三次面试都没通过，有点难受。不要建议也别追问。'],
            'evidence_missing': ['我在笔记本上检查端口没有监听，服务部署在远程容器里。这能证明远程服务挂了吗？简短回答。'],
            'attribution': ['小林说他养猫。我养的是狗。', '只回答我养的是什么。'],
        }
    if args.open_dialogue:
        if args.heldout_grounding:
            raise ValueError('场景开关不能混用')
        scenarios = {
            'casual': ['买的键盘到了，空格键声音像敲木鱼。', '别给购买建议，我就是觉得这个声音好笑。'],
            'emotion': ['今天投稿被拒了，有点失落。不要建议。', '我没说准备了多久，也没说被拒过几次。你知道哪些事实？'],
            'revision_history': ['旅行目的地原来定的是青岛，后来改成厦门。', '现在计划去哪里？', '我问的是改之前，不是现在。之前是哪儿？'],
        }
    if args.transfer:
        if args.open_dialogue or args.heldout_grounding:
            parser.error('场景开关不能混用')
        scenarios = {
            'sharing_to_help': ['新买的杯子倒水时咕噜咕噜，像在抱怨上班。', '现在认真问：这种声音能单独证明杯子有质量问题吗？只用一句话。'],
            'feeling_boundary': ['今天比赛没入选，有点闷。别给建议，也别猜我的准备过程。', '我有说过练了多久、参加过几次吗？'],
            'ownership_correction': ['小周的预约是周五，我的是周二。', '更正：我的改成周四，小周不变。只写“小周：星期几；我：星期几”。'],
        }
    if args.relations:
        scenarios = {
            'preparation_window': ['我准备了四个月，面试失败两次。只简短回应，不给建议。', '我有没有说两次面试都发生在这四个月内？只回答“已说明”或“未说明”。'],
            'ownership_duration': ['小林学琴五年，我参加过三次演出。只确认收到。', '我的学琴年限是多少？只回答“未知”或明确年数。'],
            'temporal_correction': ['我在三月报名，六月开始训练。只确认收到。', '更正：训练从七月开始，报名时间不变。只写“三月报名；七月训练”。'],
        }
    if args.paraphrase:
        scenarios = {
            'duration_attachment': ['我学法语八个月，参加过两次面试。帮我写一句简短的自我介绍，保留这些信息。'],
            'owner_attachment': ['阿宁住苏州六年，我去过杭州两次。用一句话概括我们两人的情况。'],
            'correction_attachment': ['项目二月立项，五月上线。更正一下：上线改到六月，立项不变。请写一句最新进度摘要。'],
            'uncertain_cause': ['周三改了配置，周五服务报错。目前没查原因。用一句话概括经过。'],
        }
    report = {'scope': 'synthetic sequential real model responses; not MaiBot runtime',
              'variant': 'evidence_examples' if args.evidence_examples else 'grounded_intent' if args.grounded_intent else 'intent_fit' if args.intent_fit else 'grounding' if args.grounding else 'current',
              'suite': 'paraphrase_v1' if args.paraphrase else 'relations_v1' if args.relations else 'transfer_v1' if args.transfer else 'open_dialogue_v1' if args.open_dialogue else 'heldout_grounding_v1' if args.heldout_grounding else 'rollout_v1',
              'expected_turns': sum(len(turns) for turns in scenarios.values()),
              'scenarios': {}}
    report['transport'] = 'openai_sdk_live' if args.sdk else 'requests_live'
    report['history_path'] = 'production_text_factory_and_replyer' if args.runtime_history else 'direct_http_messages'
    if args.runtime_history:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import os
        import tempfile
        # 导入生产模块的日志/数据库初始化限定在临时目录，不触碰生产数据。
        run = run.resolve()
        isolated_runtime = tempfile.TemporaryDirectory(prefix='maibot-rollout-')
        os.chdir(isolated_runtime.name)
        from src.maisaka.context.planner_messages import build_session_backed_text_message
        from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator
        history_generator = object.__new__(BaseMaisakaReplyGenerator)
    for name, inputs in scenarios.items():
        messages = [{'role':'system', 'content':build_identity_prompt_block('测试助手') + extra}]
        records = report['scenarios'][name] = []
        for text in inputs:
            messages.append({'role':'user', 'content':text})
            body = dict(model=model['model_identifier'], messages=messages,
                        temperature=task['temperature'], max_tokens=task['max_tokens'], stream=False)
            body.update(model.get('extra_params', {}))
            record: Dict[str, Any] = {'request':request_metadata(body)}
            started = time.monotonic()
            try:
                if args.sdk:
                    from openai import OpenAI
                    # 禁止 SDK 隐式重试，保留真实单次失败与超时证据。
                    with OpenAI(api_key=provider['api_key'], base_url=provider['base_url'],
                                timeout=120, max_retries=0) as client:
                        standard = {key: body[key] for key in ('model','messages','temperature','max_tokens','stream')}
                        extra_body = {key:value for key,value in body.items() if key not in standard}
                        raw = client.chat.completions.with_raw_response.create(**standard, extra_body=extra_body)
                        record['http_status'] = raw.status_code
                        data = raw.parse().model_dump()
                else:
                    response = requests.post(provider['base_url'].rstrip('/')+'/chat/completions',
                        headers={'Authorization':'Bearer '+provider['api_key']}, json=body, timeout=120)
                    record['http_status'] = response.status_code
                    response.raise_for_status()
                    data = response.json()
                choice = data['choices'][0]
                content = choice['message'].get('content')
                usage = data.get('usage') or {}
                record['usage'] = {key: usage[key] for key in (
                    'prompt_tokens', 'completion_tokens', 'total_tokens')
                    if type(usage.get(key)) is int and usage[key] >= 0}
                record.update(output=content, response_model=data.get('model'),
                              finish_reason=choice.get('finish_reason'),
                              completion_status=completion_status(content, choice.get('finish_reason')))
            except Exception as exc:
                record.update(completion_status='error', error_type=type(exc).__name__)
            record['elapsed_seconds'] = round(time.monotonic() - started, 3)
            records.append(record)
            (run/'rollout.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            if record['completion_status'] != 'complete':
                break
            history_text = record['output']
            if args.runtime_history:
                entry = build_session_backed_text_message(
                    speaker_name='测试]助手', text=history_text, timestamp=datetime.now(timezone.utc),
                    source_kind='guided_reply', message_id=uuid4().hex, is_self_message=True)
                items = history_generator._build_history_messages([entry], False)
                history_text = ''.join(getattr(part, 'text', '') for part in items[0].parts)
                if history_text != record['output']:
                    raise ValueError('Production history altered response')
                record['history_verified'] = True
                (run/'rollout.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            messages.append({'role':'assistant', 'content':history_text})
    print('REPORT', run/'rollout.json')
    print(json.dumps({name:[{k:r.get(k) for k in ('output','completion_status','error_type')} for r in rows]
                      for name,rows in report['scenarios'].items()}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()

"""独立模型冒烟测试：合成场景，不连接聊天平台，不输出凭据。"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
import argparse
import json
import importlib.util
import sys
import tomllib
import time

import requests
from dialogue_eval_metadata import completion_status, request_metadata

def build_identity_prompt_block(name: str) -> str:
    """按文件加载无依赖提示模块，不执行 src.chat 包的服务初始化。"""
    path = Path(__file__).resolve().parents[1] / 'src/chat/utils/identity_guard.py'
    module_name = '_dialogue_eval_identity'
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError('找不到独立提示模块')
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        return module.build_identity_prompt_block(name)
    finally:
        sys.modules.pop(module_name, None)

CASES = [
    ('technical_unseen', '网页突然 403，只能先做一个最小检查，你先查哪一项？'),
    ('acknowledgement_unseen', '我刚把截图发了，收到了就回“看到了”。'),
    ('empathy_unseen', '今天连续踩坑，已经不想再折腾了。'),
    ('memory_boundary_unseen', '你上周见过我家人吗？'),
    ('uncertainty_unseen', '这个域名是不是被封了？我还没给域名和错误信息。'),
    ('correction_unseen', '补充一下，问题不是证书，是 DNS 解析错了。'),
]

FEW_SHOT = """以下是教学示例，只示范回应动作，不是事实、经历或固定台词：
用户：我把截图发了，收到了回一句。
助手：我这边还没看到截图内容。
用户：服务是不是挂了？没有地址和日志。
助手：现在没法判断，先给地址或报错。
用户：折腾半天还是没好。
助手：确实挺烦的，先歇会儿也行。
用户：刚才说错了，是 DNS，不是证书。
助手：明白，按 DNS 方向查，不沿用前面的证书判断。
"""


COUNTER_CASES = [
    ('log_present', '日志正文：2026-01-01 ERROR certificate expired。以上就是日志，只确认看到这段文字即可，不要排查。'),
    ('detail_requested', '请完整列出证书过期的排查与续期步骤，包括备份、验证和回滚，不要只给第一步。'),
    ('memory_provided', '本轮明确提供的信息：我养了一只叫豆豆的猫。现在问：我的猫叫什么？只回答名字。'),
    ('no_advice', '我只是想吐槽今天很累，不需要建议，也不想被问问题。'),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--counterexamples', action='store_true')
    parser.add_argument('--interaction-boundary', action='store_true')
    parser.add_argument('--multiturn', action='store_true')
    parser.add_argument('--repeats', type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 3:
        raise ValueError('repeats 必须为 1 到 3')
    cases = COUNTER_CASES if args.counterexamples else CASES
    variants = ('baseline', 'fewshot')
    boundary = '尊重用户明确的交互范围：如果用户只想倾诉且不要建议，不给行动指令，休息、放松、喝水等也算建议；不追问、不邀约帮忙。只回应已表达的具体感受，不推断诊断。若用户明确请求建议，则正常提供，不把此规则泛化为永远不建议。'
    if args.interaction_boundary:
        variants = ('baseline', 'boundary')
        cases = [
            ('vent_fatigue', '今天累得够呛，我就抱怨一句，不要教我怎么做。'),
            ('vent_disappointment', '准备很久还是没通过，我只想有人听着，不要建议也别问原因。'),
            ('advice_requested', '今天累得够呛，给我一个简单可行的安排建议。'),
        ]
    if args.multiturn:
        if args.counterexamples or args.interaction_boundary:
            raise ValueError('multiturn 不与其他场景开关混用')
        variants = ('current',)
        def dialogue(*turns):
            return [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': text}
                    for i, text in enumerate(turns)]
        cases = [
            ('intent_changed', dialogue('只想吐槽，不要建议。', '嗯，我听着。', '现在想解决了，只给一个下一步：Nginx 返回502，先查什么？')),
            ('fact_corrected', dialogue('我用的是 Ubuntu。', '明白，Ubuntu。', '纠正一下，是 Alpine。现在只回答我使用哪个系统。')),
            ('provided_fact', dialogue('我的猫叫团团。', '记下了，团团。', '我猫叫什么？只回答名字。')),
            ('advice_withdrawn', dialogue('给我几个排障建议。', '可以先看日志和配置。', '先别排查了，也别问问题，我只是想说这事真烦。')),
        ]
    config = tomllib.loads(Path('config/model_config.toml').read_text())
    task = config['model_task_config']['replyer']
    model = next(x for x in config['models'] if x['name'] == task['model_list'][0])
    provider = next(x for x in config['api_providers'] if x['name'] == model['api_provider'])
    if provider.get('auth_type') != 'bearer' or provider.get('client_type') != 'openai':
        raise ValueError('此冒烟脚本仅支持已核对的 OpenAI bearer 接口')
    prompt = build_identity_prompt_block('测试助手') + '\n简洁自然地回复，信息不足时不要假装知道。'
    if args.interaction_boundary:
        # 主程序已采纳此规则；对照组必须剔除它，否则两组提示相同。
        if prompt.count(boundary) != 1:
            raise ValueError('交互边界规则与实验定义不一致，停止无效对照')
        prompt = prompt.replace(boundary + '\n', '')
    output = Path('data/dialogue-model-counterexamples.json' if args.counterexamples else 'data/dialogue-model-paired-smoke.json')
    if args.interaction_boundary:
        output = Path('data/dialogue-interaction-boundary.json')
    if args.multiturn:
        output = Path('data/dialogue-multiturn.json')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
    run_dir = Path('data/dialogue-evaluations') / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    output = run_dir / output.name
    def run(job):
        variant, case = job
        label, text = case
        addition = FEW_SHOT if variant == 'fewshot' else boundary if variant == 'boundary' else ''
        active_prompt = prompt + '\n' + addition
        start = time.monotonic()
        turns = text if isinstance(text, list) else [{'role': 'user', 'content': text}]
        body = dict(model=model['model_identifier'], messages=[
            {'role': 'system', 'content': active_prompt}] + turns,
            temperature=task['temperature'], max_tokens=task['max_tokens'], stream=False)
        body.update(model.get('extra_params', {}))
        metadata = request_metadata(body)
        try:
            response = requests.post(provider['base_url'].rstrip('/')+'/chat/completions',
                headers={'Authorization': 'Bearer '+provider['api_key']}, json=body, timeout=120)
            if response.status_code != 200:
                return {'case': label, 'variant': variant, 'request': metadata, 'status': response.status_code, 'ok': False}
            data = response.json()
            content = data['choices'][0]['message'].get('content')
            state = completion_status(content, data['choices'][0].get('finish_reason'))
            return {'case': label, 'variant': variant, 'request': metadata, 'input': text, 'output': content,
                    'ok': state == 'complete', 'completion_status': state,
                    'seconds': round(time.monotonic()-start, 2), 'usage': data.get('usage'),
                    'response_model': data.get('model'), 'response_id': data.get('id'),
                    'finish_reason': data['choices'][0].get('finish_reason')}
        except Exception as exc:
            return {'case': label, 'variant': variant, 'request': metadata, 'ok': False, 'error_type': type(exc).__name__}
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [(v, (f'{label}__r{repeat}', text))
                for repeat in range(1, args.repeats + 1)
                for label, text in cases for v in variants]
        results = list(pool.map(run, jobs))
    report = {'run_id': run_id, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'model': model['model_identifier'], 'scope': 'direct API synthetic smoke, not full MaiBot pipeline or A/B',
              'cases': results}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()

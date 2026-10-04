"""真实 embedding 的小样本召回对照；不导入服务、不改生产索引。"""
import json
import tomllib
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
import requests
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

def load_query_builder():
    """编译生产纯方法，不执行聊天包的初始化代码。"""
    import ast
    from typing import Any, List, Optional
    source = ROOT / 'src/chat/replyer/maisaka_expression_selector.py'
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MaisakaExpressionSelector')
    names = {'_format_expression_intent', '_build_expression_query_text'}
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if len(methods) != len(names):
        raise RuntimeError('query builder contract changed')
    namespace = dict(Any=Any, List=List, Optional=Optional)
    module = ast.Module(body=methods, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(source), 'exec'), namespace)
    builder = type('IsolatedQueryBuilder', (), {name: namespace[name] for name in names})
    namespace['MaisakaExpressionSelector'] = builder
    return builder._build_expression_query_text


def main():
    cfg = tomllib.loads((ROOT / 'config/model_config.toml').read_text())
    task = cfg['model_task_config']['embedding']
    model = next(m for m in cfg['models'] if m['name'] == task['model_list'][0])
    provider = next(p for p in cfg['api_providers'] if p['name'] == model['api_provider'])
    candidates = ['对方失落只想倾诉：简短承接感受，不提建议',
                  '对方明确请求技术排障：给出最小检查步骤',
                  '对方分享成功喜讯：简短庆祝，回应喜讯']
    cases = [
        ('emotion', '继续排查 Nginx 502', '先不排查了，投稿被拒有点失落，只想吐槽，不要建议。', 0),
        ('technical', '安慰投稿被拒的失落', '现在想解决技术问题，Nginx 返回502，请给一个最小排查步骤。', 1),
        ('celebrate', '安慰投稿被拒的失落', '新稿终于录用了！太开心了！', 2),
        ('implicit_technical', '用户在排查 Nginx 502，请继续提供最小检查步骤', '然后呢？', 1),
        ('implicit_emotion', '用户投稿被拒，只想被理解，不要建议', '就是这样。', 0),
    ]
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--heldout', action='store_true')
    parser.add_argument('--distractors', action='store_true')
    args = parser.parse_args()
    if args.distractors:
        candidates.extend([
            '对方失落只想倾诉：马上列出解决问题的建议和行动计划',
            '对方请求最小技术检查：展开长篇原理科普和所有可能原因',
            '对方分享成功喜讯：提醒别高兴太早，强调未来风险',
            '对方失落：断言自己也经历过完全相同的事情',
            '对方请求技术排障：不做检查，直接断言服务器已经宕机',
            '对方分享喜讯：转而夸耀自己的成功经历',
            '对方明确请求具体建议：给出可行建议并说明限制',
            '对方请求详细原理：分层解释技术背景与机制',
            '对方明确要求风险评估：说明潜在风险及不确定性',
        ])
    if args.heldout:
        # 在读取本轮结果前固定新场景；沿用已有权重，不据结果再调参。
        cases = [
            ('exam_success', '安慰考试失败的失落', '补考通过了！终于可以毕业了！', 2),
            ('backup_help', '陪用户分享毕业的喜悦', '先说正事，备份脚本报权限不足，请给一个检查步骤。', 1),
            ('loss_listen', '帮用户排查备份权限', '先放下电脑吧，我的猫走丢了，很难过，只想说说。', 0),
            ('continue_debug', '用户请求排查数据库连接超时，需要下一步检查', '接下来查哪里？', 1),
            ('continue_listen', '用户和朋友吵架很委屈，只想倾诉，不需要解决方案', '你能懂吗？', 0),
            ('continue_success', '用户刚宣布拿到奖学金，想一起庆祝', '真的等这一天好久了！', 2),
        ]
    build_query = load_query_builder()
    variants = ("reason_only", "target_plus_reason", "target_only")
    queries = [q for _, reason, target, _ in cases
               for q in (build_query(reason, {}), build_query(reason, {}, target_message=target),
                         build_query("", {}, target_message=target))]
    inputs = candidates + queries
    out = ROOT / 'data/dialogue-evaluations' / ('embedding-context-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    out.mkdir(parents=True)
    report = dict(scope='synthetic text; real HTTP embeddings; production query builder; cosine ranking only, not production MMR', model=model['model_identifier'], suite='heldout_v1' if args.heldout else 'development_v1', candidates=candidates, inputs=inputs, rows=[])
    try:
        body = dict(model.get('extra_params', {}))
        body.update(model=model['model_identifier'], input=inputs)
        response = requests.post(provider['base_url'].rstrip('/') + '/embeddings', headers={'Authorization': 'Bearer ' + provider['api_key']}, json=body, timeout=120)
        response.raise_for_status()
        data = response.json()
        items = sorted(data['data'], key=lambda item: item['index'])
        if [item['index'] for item in items] != list(range(len(inputs))):
            raise ValueError('embedding coverage mismatch')
        vectors = np.asarray([item['embedding'] for item in items], dtype=np.float64)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if vectors.ndim != 2 or not np.all(np.isfinite(vectors)) or not np.all(np.isfinite(norms)) or np.any(norms <= 0):
            raise ValueError('invalid embeddings')
        # 保存真实返回向量以支持离线复核，不保存请求头或配置。
        np.save(out / 'embeddings.npy', vectors, allow_pickle=False)
        normalized = vectors / norms
        for i, (name, reason, target, expected) in enumerate(cases):
            row = dict(case=name, expected_id=expected)
            for j, variant in enumerate(variants):
                scores = normalized[:len(candidates)] @ normalized[len(candidates) + len(variants)*i+j]
                ranking = np.argsort(-scores).tolist()
                row[variant] = dict(ranking=ranking, scores=scores.tolist(), top1_correct=ranking[0] == expected)
            report['rows'].append(row)
        report.update(status='complete', dimension=vectors.shape[1], returned_model=data.get('model'))
    except Exception as exc:
        report.update(status='failed', error_type=type(exc).__name__)
    (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(out / 'result.json')
    print(json.dumps({k:v for k,v in report.items() if k in ('status','error_type','dimension','rows')}, ensure_ascii=False))
    return 0 if report['status'] == 'complete' else 1

if __name__ == '__main__':
    raise SystemExit(main())

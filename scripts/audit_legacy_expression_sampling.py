"""隔离编译生产采样函数，固定种子审计；不加载数据库或修改配置。"""
import ast
import json
import random
from pathlib import Path
from typing import Any, Dict, List
from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]

def load_sampler():
    namespace = dict(List=List, Dict=Dict, Any=Any, random=random.Random(20260920))
    tree = ast.parse((ROOT/'src/learners/learner_utils_old.py').read_text(encoding='utf-8-sig'))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'weighted_sample','_compute_weights'}]
    if len(nodes) != 2:
        raise ValueError('sampling contract changed')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<production weighted sampling>', 'exec'), namespace)
    tree = ast.parse((ROOT/'src/chat/replyer/maisaka_expression_selector.py').read_text(encoding='utf-8-sig'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MaisakaExpressionSelector')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_sample_legacy_expression_candidates')
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<production legacy sampling>', 'exec'), namespace)
    return namespace['_sample_legacy_expression_candidates']

def main():
    source = ROOT/'data/dialogue-evaluations/embedding-context-20260919T225308Z-907773e2/result.json'
    data = json.loads(source.read_text())
    sampler = load_sampler()
    results = []
    for scenario, counts in [('all_count_one',[1]*12), ('all_count_two',[2]*12), ('preferred_rare',[1]*3+[20]*9)]:
        candidates = [dict(id=i, situation=text, style=text, count=counts[i]) for i,text in enumerate(data['candidates'])]
        if len(candidates) != 12:
            raise ValueError('candidate coverage changed')
        hits, sizes = Counter(), Counter()
        for _ in range(1000):
            selected = sampler(None, candidates)
            ids = [c['id'] for c in selected]
            assert len(ids) == len(set(ids))
            assert set(ids) <= set(range(12))
            hits.update(ids)
            sizes[len(ids)] += 1
        results.append(dict(scenario=scenario, runs=1000, pool_size_histogram=dict(sizes),
                            candidate_inclusion_counts=dict(sorted(hits.items())),
                            expected_candidate_inclusion={str(i):hits[i] for i in (0,1,2)}))
    out = ROOT/'data/dialogue-evaluations'/('legacy-sampling-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])
    out.mkdir()
    report = dict(seed=20260920, source=str(source), results=results, deployment='not_applied',
                  scope='Production sampler code, synthetic counts, fixed RNG; not live database distribution or model selection')
    (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(out/'result.json')
    print(json.dumps(results,ensure_ascii=False))

if __name__ == '__main__':
    main()

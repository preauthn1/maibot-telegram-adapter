"""按配对场景汇总匿名审核；仅提供审核建议，不发布提示。"""
import argparse
import json
from pathlib import Path
from validate_blind_review import validate


def summarize(original, reviewed, mapping, *, candidate_variant='intent_fit'):
    if not isinstance(candidate_variant, str) or not candidate_variant.strip() or candidate_variant == 'current':
        raise ValueError('Candidate must be distinct from baseline')
    validate(original, reviewed)
    if set(mapping) != {t['id'] for t in original['tasks']}:
        raise ValueError('Mapping IDs mismatch')
    groups = {}
    dimensions = ('grounding', 'intent_fit', 'continuity')
    for row in reviewed['tasks']:
        meta = mapping[row['id']]
        variant = meta['variant']
        pair = (meta['scenario'], meta['turn'])
        group = groups.setdefault(variant, {})
        if pair in group:
            raise ValueError('Duplicate scenario/turn in variant')
        group[pair] = row
    if set(groups) != {'current', candidate_variant}:
        raise ValueError('Expected current and the explicitly selected candidate variants')
    base, candidate = groups['current'], groups[candidate_variant]
    if not base or set(base) != set(candidate):
        raise ValueError('Unpaired or empty evaluation')
    regressions, improvements = [], []
    for pair in sorted(base):
        # 连续生成中助手历史会分叉，但用户题目必须逐轮一致。
        base_users = [m['content'] for m in base[pair]['context'] if m['role'] == 'user']
        candidate_users = [m['content'] for m in candidate[pair]['context'] if m['role'] == 'user']
        if base_users != candidate_users:
            raise ValueError('Paired user histories differ')
        for dim in dimensions:
            old, new = base[pair]['review'][dim], candidate[pair]['review'][dim]
            item = {'scenario': pair[0], 'turn': pair[1], 'dimension': dim,
                    'baseline': old, 'candidate': new}
            if old != 'fail' and new == 'fail':
                regressions.append(item)
            if old == 'fail' and new == 'pass':
                improvements.append(item)
    counts = {variant: {dim: {rating: sum(r['review'][dim] == rating for r in rows.values())
                              for rating in ('pass', 'fail', 'uncertain')}
                        for dim in dimensions} for variant, rows in groups.items()}
    return {'paired_turns': len(base), 'counts': counts,
            'new_failures': regressions, 'resolved_failures': improvements,
            'selection': 'retain_baseline' if regressions else 'further_review_required',
            'scope': 'single AI reviewer, small sequential sample; not causal or statistical proof',
            'deployment': 'not_applied'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    def load(name):
        return json.loads((args.directory / name).read_text(encoding='utf-8'))
    result = summarize(load('review.json'), load('reviewer-a.json'), load('private-mapping.json'))
    output = args.directory / 'decision-a.json'
    with output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

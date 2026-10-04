"""导出匿名开放式评审包；映射单独保存，不自动判定质量。"""
import argparse
import json
import random
from pathlib import Path
from uuid import uuid4


def build_packet(paths, seed):
    tasks, key = [], {}
    for source in paths:
        report = json.loads(source.read_text(encoding='utf-8'))
        observed = sum(len(rows) for rows in report['scenarios'].values())
        if observed != report['expected_turns']:
            raise ValueError('Incomplete source report')
        for scenario, rows in report['scenarios'].items():
            for index, row in enumerate(rows):
                if row.get('completion_status') != 'complete':
                    raise ValueError('Incomplete generation')
                messages = row['request']['messages']
                context = [{'role': m['role'], 'content': m['content']}
                           for m in messages if m['role'] in ('user', 'assistant')]
                if not context or context[-1]['role'] != 'user':
                    raise ValueError('Missing user context')
                identifier = uuid4().hex
                tasks.append({'id': identifier, 'context': context, 'response': row['output'],
                              'review': {dimension: None for dimension in
                                         ('grounding', 'intent_fit', 'continuity', 'naturalness')},
                              'evidence_quotes': [], 'rationale': ''})
                key[identifier] = {'source': str(source), 'scenario': scenario,
                                   'turn': index + 1, 'variant': report.get('variant'),
                                   'request_sha256': row['request']['request_sha256']}
    random.Random(seed).shuffle(tasks)
    packet = {'scope': 'Anonymized per-turn review; not yet evaluated',
              'rubric': {
                  'grounding': 'pass/fail/uncertain：是否把未提供的经历、条件或推测当事实；需引用证据。',
                  'intent_fit': 'pass/fail/uncertain：回应是否符合最新请求；是否擅自建议或科普。',
                  'continuity': 'pass/fail/uncertain：对象、历史事实与纠正是否一致。',
                  'naturalness': '1–5 或 uncertain：贴合具体对话且不机械套话；不以越短越好或隐藏自动身份为标准。',
              },
              'limitations': ['上下文包含前轮真实助手输出，不能据此做单轮因果归因。',
                              '匿名化只隐藏标签，无法保证评审者从文风猜不出版本。',
                              '质量得分不能抵消事实或明确指令违规。'],
              'tasks': tasks}
    return packet, key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('reports', nargs='+', type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    packet, key = build_packet(args.reports, seed=42)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / 'review.json').write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding='utf-8')
    key_path = args.output_dir / 'private-mapping.json'
    with key_path.open('x', encoding='utf-8') as handle:
        key_path.chmod(0o600)
        json.dump(key, handle, ensure_ascii=False, indent=2)
    assert len(key) == len(packet['tasks'])
    assert set(key) == {row['id'] for row in packet['tasks']}
    print(json.dumps({'tasks': len(key), 'packet': str(args.output_dir / 'review.json'),
                      'status': 'unreviewed'}, ensure_ascii=False))


if __name__ == '__main__':
    main()

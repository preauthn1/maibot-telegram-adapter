"""GEPA 原生适配：合成精确约束优化，候选仅落盘，不自动发布。"""
import json
import tomllib
from pathlib import Path
from datetime import datetime, timezone
import requests
import gepa
from evaluate_dialogue_smoke import build_identity_prompt_block
from dialogue_evolution_errors import TrackedCompletion


class Adapter:
    propose_new_texts = None

    def __init__(self, complete, journal):
        self.complete = complete
        self.journal = journal

    def evaluate(self, batch, candidate, capture_traces=False):
        outputs, scores, traces = [], [], []
        for example in batch:
            policy = candidate['dialogue_policy']
            if not policy.strip() or len(policy.encode()) > 15000:
                raise ValueError('invalid candidate size')
            output = self.complete([
                {'role': 'system', 'content': build_identity_prompt_block('测试助手') + '\n' + policy},
                {'role': 'user', 'content': example['input']},
            ])
            score = float(output.strip() == example['expected'])
            trace = {'Inputs': example['input'], 'Generated Outputs': output,
                     'Feedback': 'Exact required output: ' + example['expected'], 'score': score}
            outputs.append(output)
            scores.append(score)
            traces.append(trace)
            with self.journal.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps({'candidate': candidate, **trace}, ensure_ascii=False) + '\n')
        return gepa.EvaluationBatch(outputs, scores, traces if capture_traces else None)

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        return {name: eval_batch.trajectories for name in components_to_update}


def main():
    config = tomllib.loads(Path('config/model_config.toml').read_text())
    task = config['model_task_config']['replyer']
    model = next(m for m in config['models'] if m['name'] == task['model_list'][0])
    provider = next(p for p in config['api_providers'] if p['name'] == model['api_provider'])
    def complete(messages):
        # GEPA 反思接口传入纯文本；任务评测接口传入消息列表。
        if isinstance(messages, str):
            messages = [{'role': 'user', 'content': messages}]
        response = requests.post(provider['base_url'].rstrip('/') + '/chat/completions',
            headers={'Authorization': 'Bearer ' + provider['api_key']},
            json={'model': model['model_identifier'], 'messages': messages,
                  'temperature': 0.5, 'max_tokens': 1200, 'stream': False}, timeout=120)
        response.raise_for_status()
        choice = response.json()['choices'][0]
        text = choice['message'].get('content')
        if choice.get('finish_reason') != 'stop' or not isinstance(text, str) or not text.strip():
            raise RuntimeError('incomplete generation; abort experiment')
        return text
    run = Path('data/dialogue-evolution') / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run.mkdir(parents=True, exist_ok=False)
    train = [
        {'input': '只回复“收到”，不要添加标点。', 'expected': '收到'},
        {'input': '之前说 Ubuntu，纠正为 Alpine。只输出当前系统名称，不要标点。', 'expected': 'Alpine'},
    ]
    val = [{'input': '甲养猫，我养狗。只输出我养的动物，不要标点。', 'expected': '狗'}]
    holdout = [
        {'input': '先别建议。只回复“好”，不要标点。', 'expected': '好'},
        {'input': '我养的是狗，甲养猫。只输出我养的动物，不要标点。', 'expected': '狗'},
        {'input': '把 Ubuntu 纠正为 Alpine，只输出当前系统名称。', 'expected': 'Alpine'},
    ]
    (run / 'dataset.json').write_text(json.dumps({'train': train, 'val': val, 'holdout': holdout}, ensure_ascii=False))
    complete = TrackedCompletion(complete, run / 'model-errors.jsonl')
    adapter = Adapter(complete, run / 'traces.jsonl')
    seed = {'dialogue_policy': '自然回应，尊重当前请求，不添加没有依据的信息。'}
    result = gepa.optimize(seed_candidate=seed, trainset=train, valset=val, adapter=adapter,
        reflection_lm=complete, max_metric_calls=8, reflection_minibatch_size=2,
        skip_perfect_score=False, run_dir=str(run / 'engine'), seed=0)
    if complete.failures:
        (run / 'result.json').write_text(json.dumps({
            'status': 'failed', 'deployment': 'not_applied',
            'errors': complete.failures}, ensure_ascii=False, indent=2))
    complete.require_clean()
    candidate = result.best_candidate
    baseline = adapter.evaluate(holdout, seed)
    evolved = adapter.evaluate(holdout, candidate)
    complete.require_clean()
    no_regression = (len(baseline.scores) == len(evolved.scores) == len(holdout)
                     and all(new >= old for old, new in zip(baseline.scores, evolved.scores)))
    strict_gain = no_regression and sum(evolved.scores) > sum(baseline.scores)
    report = {'no_regression': no_regression, 'strict_gain': strict_gain,
        'selection': 'review_required' if strict_gain and candidate != seed else 'retain_baseline',
        'engine': 'gepa', 'upstream_commit': '0a929e3aa20e15cf04dc7c28492a7d41a5139125',
        'scope': 'synthetic exact-output spike; not naturalness or MaiBot full pipeline',
        'candidate': candidate, 'changed': candidate != seed,
        'baseline_holdout': baseline.scores, 'candidate_holdout': evolved.scores,
        'deployment': 'not_applied'}
    (run / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print('REPORT', run / 'result.json')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()

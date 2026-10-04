"""原始 HTTP SSE 字段诊断；不保存推理正文或凭据。"""
import json
from pathlib import Path
import tomllib
from uuid import uuid4
import requests


def main():
    root = Path('data/dialogue-evaluations/isolated-regression-20260920T080740Z-90973480')
    records = [json.loads(p.read_text()) for p in root.glob('assembled-*.json')]
    record = next(r for r in records if r['expected'] == 'Alpine')
    cfg = tomllib.loads(Path('config/model_config.toml').read_text())
    task = cfg['model_task_config']['replyer']
    model = next(m for m in cfg['models'] if m['name'] == task['model_list'][0])
    provider = next(p for p in cfg['api_providers'] if p['name'] == model['api_provider'])
    out = root / ('raw-sse-' + uuid4().hex[:8])
    out.mkdir(mode=0o700)
    result = {'scope':'raw HTTP SSE, exported synthetic prompt, no SDK parser', 'events':[], 'output':'', 'done':False}
    body = dict(model.get('extra_params', {}))
    body.update(model=model['model_identifier'], messages=record['messages'], temperature=task['temperature'], max_tokens=task['max_tokens'], stream=True)
    try:
        with requests.post(provider['base_url'].rstrip('/')+'/chat/completions',
                           headers={'Authorization':'Bearer '+provider['api_key']}, json=body, stream=True, timeout=120) as response:
            result['http_status'] = response.status_code
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith(b'data:'):
                    continue
                data = line[5:].strip()
                if data == b'[DONE]':
                    result['done'] = True
                    break
                event = json.loads(data)
                shapes = []
                for choice in event.get('choices', []):
                    delta = choice.get('delta') or {}
                    shapes.append({'index':choice.get('index'), 'finish_reason':choice.get('finish_reason'),
                        'fields':{k:{'type':type(v).__name__, 'length':len(v) if isinstance(v,(str,list,dict)) else None} for k,v in delta.items()}})
                    if choice.get('index') == 0 and isinstance(delta.get('content'), str):
                        result['output'] += delta['content']
                result['events'].append(shapes)
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    path = out/'result.json'
    path.touch(mode=0o600)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({'path':str(path),**result},ensure_ascii=False))

if __name__ == '__main__':
    main()

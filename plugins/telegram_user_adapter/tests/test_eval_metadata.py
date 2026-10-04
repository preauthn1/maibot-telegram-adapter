"""记录合成提示和白名单参数，不记录鉴权字段。"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from dialogue_eval_metadata import request_metadata


def test_metadata_is_stable_and_excludes_auth():
    body = {'model': 'test', 'temperature': 1, 'messages': [{'role': 'user', 'content': '合成问题'}],
            'api_key': 'secret-marker', 'headers': {'Authorization': 'secret-marker'},
            'thinking': {'type': 'enabled', 'api_key': 'secret-marker'}}
    first = request_metadata(body)
    assert 'secret-marker' not in json.dumps(first)
    assert request_metadata(dict(reversed(list(body.items())))) == first
    body['temperature'] = 0
    assert request_metadata(body)['request_sha256'] != first['request_sha256']

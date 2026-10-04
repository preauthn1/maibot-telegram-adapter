"""离线合成评测的请求记录；只采纳白名单字段，不记录鉴权信息。"""
import hashlib
import json


def completion_status(content: object, finish_reason: object) -> str:
    """接口返回不等于可用于完整回答评测；未知结束原因也不猜成成功。"""
    if not isinstance(content, str) or not content.strip():
        return 'empty'
    if finish_reason == 'length':
        return 'truncated'
    if finish_reason == 'stop':
        return 'complete'
    return 'unverified_finish'


def request_metadata(body: dict) -> dict:
    allowed = ('model', 'temperature', 'max_tokens', 'stream', 'reasoning_effort')
    parameters = {key: body[key] for key in allowed if key in body}
    thinking = body.get('thinking')
    if isinstance(thinking, dict):
        parameters['thinking'] = {key: thinking[key] for key in ('type', 'budget_tokens') if key in thinking}
    messages = [{'role': item['role'], 'content': item['content']} for item in body['messages']]
    record = {'parameters': parameters, 'messages': messages}
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return {**record, 'request_sha256': hashlib.sha256(canonical.encode()).hexdigest()}

"""真实缓存统计优先使用供应商 wire 请求，并保持原对象不变。"""
import copy
import json
from unittest.mock import Mock
from src.services import llm_service as module
from src.services.llm_service import LLMServiceClient
from src.llm_models.model_client.base_client import APIResponse


def test_cache_uses_wire_request_without_mutation(monkeypatch):
    client = LLMServiceClient('replyer', request_type='synthetic', session_id='synthetic')
    result = client._orchestrator._build_generation_result(APIResponse(), 'synthetic-model')
    wire = {'model': 'synthetic-wire-model', 'messages': [
        {'role': 'user', 'content': '保留否定：不要重试\n"原文"'}],
        'temperature': 0.3, 'tools': [{'type': 'function', 'function': {'name': 'synthetic_tool'}}]}
    original = copy.deepcopy(wire)
    result.request_wire_payload = wire
    result.wire_protocol = 'synthetic-wire'
    recorder = Mock()
    monkeypatch.setattr(module, 'record_llm_cache_usage', recorder)
    client._record_cache_stats(result, prompt_text='STALE_CONTEXT_MARKER')
    recorder.assert_called_once()
    fields = recorder.call_args.kwargs
    payload = json.loads(fields['prompt_text'])
    assert payload == {'wire_protocol': 'synthetic-wire', 'request': original}
    assert 'STALE_CONTEXT_MARKER' not in fields['prompt_text']
    assert fields['session_id'] == 'synthetic'
    assert fields['model_name'] == 'synthetic-model'
    assert wire == original
    assert result.request_wire_payload is wire

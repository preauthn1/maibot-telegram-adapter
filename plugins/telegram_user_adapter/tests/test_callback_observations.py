"""执行真实发送后回调，验证多段落盘不读取共享候选。"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call
import asyncio
import json
import logging
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.plugin import TelegramUserAdapterPlugin
from telegram_user_adapter.transcript import ChatTranscriptLogger


def test_callback_logs_each_successful_text_segment(tmp_path):
    plugin = object.__new__(TelegramUserAdapterPlugin)
    plugin._extract_text_from_message = Mock(return_value='未发送的批次候选')
    plugin._last_outbound_text = {}
    plugin._self_improvement = None
    plugin._small_chat = Mock()
    plugin._share_guard_for = Mock(return_value=Mock())
    plugin._trigger = Mock()
    plugin._record_usage_estimate = Mock()
    plugin._usage = SimpleNamespace(totals=lambda: SimpleNamespace(calls=1))
    plugin._usage_log_interval = 100
    plugin._last_inbound_at = {}
    plugin._recent_mentions = {}
    plugin._remember_sent_message = Mock()
    plugin._schedule_outcome_check = Mock()
    plugin._transcript = ChatTranscriptLogger(tmp_path, logging.getLogger(__name__))
    observations = [dict(message_id='1', original_text='候选一', text='结果一', reply_is_quote=False),
                    dict(message_id='2', original_text='候选二', text='结果二', reply_is_quote=True)]
    codec = SimpleNamespace(last_typing_seconds=0, last_original_text='错误的并发候选')
    asyncio.run(plugin._after_successful_send(
        chat_id='test', message={}, result={'external_message_id': '2', 'text_observations': observations},
        enqueued_at=0, priority=0, outbound_codec=codec,
    ))
    rows = [json.loads(line) for line in (tmp_path / 'chat_test.jsonl').read_text().splitlines()]
    assert [(r['message_id'], r['original_text'], r['text']) for r in rows] == [
        ('1', '候选一', '结果一'), ('2', '候选二', '结果二')]
    assert plugin._last_outbound_text['test'] == '结果一\n结果二'
    plugin._schedule_outcome_check.assert_called_once_with('test', '结果一\n结果二')
    assert plugin._remember_sent_message.call_args_list == [
        call('test', '1', '结果一'), call('test', '2', '结果二')]
    assert all(r['original_captured'] for r in rows)
    assert all(r['timing_source'] == 'batch_callback_shared_typing_estimate' for r in rows)
    assert all(r['latency_anchor'] == 'latest_inbound_to_batch_callback_not_reply_target' for r in rows)
    assert '错误的并发候选' not in json.dumps(rows, ensure_ascii=False)

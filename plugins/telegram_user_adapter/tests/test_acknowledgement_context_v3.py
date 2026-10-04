"""短确认契约的公共 codec 回归；由断网只读沙箱运行。"""
from types import SimpleNamespace
import asyncio
import logging
import time

import pytest

from telegram_user_adapter.acknowledgement_context import acknowledgement_word
from telegram_user_adapter.codecs.outbound import TelegramUserOutboundCodec
from telegram_user_adapter.send_queue import candidate_enqueued_at


@pytest.mark.parametrize('value', [True, False, 42.0, 42.9, '0', '-42', '+42', '4.2', None])
def test_strict_source_id(value):
    msg = message()
    msg['raw_message'][0]['data']['target_message_id'] = value
    assert acknowledgement_word(msg['raw_message'], 42) is None


@pytest.mark.parametrize('source', ['不要只回复好。', '他说只回复好。', '只回复好，然后解释', '如果通过，只回复好。'])
def test_reject_ambiguous_contract(source):
    assert acknowledgement_word(message(source=source)['raw_message'], 42) is None


def test_missing_sender_and_invalid_configured_id():
    msg = message()
    assert acknowledgement_word(msg['raw_message'], 42, 42.5) is None
    msg['raw_message'][0]['data'].pop('target_message_sender_id')
    assert acknowledgement_word(msg['raw_message'], 42) is None


def test_acknowledgements_do_not_flush_family_window():
    async def scenario():
        codec, sender = codec_pair()
        for i, word in enumerate(['确实', '正常']):
            assert (await codec.send_outbound_message(message(word, i+100, source='随便聊聊'), {}))['success']
        before = list(codec._low_information_guard._successes)
        for i in range(3):
            assert (await codec.send_outbound_message(message('好', i+200), {}))['success']
        assert list(codec._low_information_guard._successes) == before
        assert not (await codec.send_outbound_message(message('行', 300, source='随便聊聊'), {}))['success']
        assert sender.sent == ['确实', '正常', '好', '好', '好']
    asyncio.run(scenario())


class Sender:
    def __init__(self):
        self.sent = []
        self.fail = False
        self.empty = False

    async def get_entity(self, target):
        return target

    async def send_text(self, entity, text, **kwargs):
        if self.fail:
            raise RuntimeError('合成发送失败')
        if self.empty:
            return None
        self.sent.append(text)
        return SimpleNamespace(id=len(self.sent))


def codec_pair(humanize=False):
    sender = Sender()
    codec = TelegramUserOutboundCodec(sender, logging.getLogger(__name__))
    codec.set_behavior(simulate_typing=False, typing_cps=6, min_think_delay=0,
                       max_typing_delay=0, enable_humanize=humanize, quote_probability=0)
    return codec, sender


def message(word='好', target=42, chat='123', source=None):
    return {'message_info': {'group_info': {'group_id': chat},
            'additional_config': {'reply_message_id': str(target)}},
            'raw_message': [{'type': 'reply', 'data': {'target_message_id': str(target),
                'target_message_content': source if source is not None else f'请确认方案A，只回复“{word}”。',
                'target_message_sender_id': 'peer'}}, {'type': 'text', 'data': word}]}


@pytest.mark.parametrize('word', ['好', '收到', '行', '可以'])
@pytest.mark.parametrize('humanize', [False, True])
@pytest.mark.parametrize('cross', [False, True])
def test_distinct_targets(word, humanize, cross):
    async def scenario():
        codec, sender = codec_pair(humanize)
        for i in range(3):
            result = await codec.send_outbound_message(message(word, 42+i, '456' if cross and i == 1 else '123'), {})
            assert result['success']
        assert sender.sent == [word]*3
        assert list(codec._low_information_guard._successes) == []
        # 契约成功不能污染普通短回复的复用记录。
        assert (await codec.send_outbound_message(message(word, 99, source='随便聊聊'), {}))['success']
    asyncio.run(scenario())


@pytest.mark.parametrize('mutation', ['missing', 'mismatch', 'negated', 'quote', 'extra', 'media', 'wrong_output', 'two_reply', 'topic'])
def test_no_blanket_bypass(mutation):
    async def scenario():
        codec, sender = codec_pair()
        codec._reply_reuse_guard.record('123', '好', now=time.monotonic())
        msg = message()
        if mutation == 'missing':
            msg['raw_message'][0]['data'].pop('target_message_content')
        elif mutation == 'mismatch':
            msg['message_info']['additional_config']['reply_message_id'] = '99'
        elif mutation == 'negated':
            msg['raw_message'][0]['data']['target_message_content'] = '不要只回复“好”。'
        elif mutation == 'quote':
            msg['raw_message'][0]['data']['target_message_content'] = '他说“只回复好”，这是反例。'
        elif mutation == 'extra':
            msg['raw_message'].append({'type': 'text', 'data': '附带长文解释'})
        elif mutation == 'media':
            msg['raw_message'].append({'type': 'image', 'data': 'not-a-url'})
        elif mutation == 'wrong_output':
            msg['raw_message'][0]['data']['target_message_content'] = '只回复收到。'
        elif mutation == 'two_reply':
            msg['raw_message'].insert(0, msg['raw_message'][0])
        elif mutation == 'topic':
            msg['message_info']['group_info']['group_id'] = '123::tg-topic::mt=42'
            msg['message_info']['additional_config'] = {}
            msg['raw_message'] = [{'type': 'text', 'data': '好'}]
        await codec.send_outbound_message(msg, {})
        assert '好' not in sender.sent
    asyncio.run(scenario())


@pytest.mark.parametrize('word', ['好', '收到'])
def test_same_target_failure_empty_cancel_and_concurrency(word):
    async def scenario():
        codec, sender = codec_pair()
        for attr in ['fail', 'empty']:
            setattr(sender, attr, True)
            assert not (await asyncio.wait_for(codec.send_outbound_message(message(word), {}), timeout=1))['success']
            setattr(sender, attr, False)
        entered, release = asyncio.Event(), asyncio.Event()
        async def wait(*args):
            entered.set()
            await release.wait()
        codec._humanize_before_send = wait
        task = asyncio.create_task(codec.send_outbound_message(message(word), {}))
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert not (await asyncio.wait_for(codec.send_outbound_message(message(word), {}), timeout=1))['success']
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        assert (await codec.send_outbound_message(message(word), {}))['success']
        assert not (await asyncio.wait_for(codec.send_outbound_message(message(word), {}), timeout=1))['success']
        assert sender.sent == [word]
    asyncio.run(scenario())


@pytest.mark.parametrize('word', ['好', '收到'])
def test_expiry_and_budget_remain(word):
    async def scenario():
        codec, sender = codec_pair()
        token = candidate_enqueued_at.set(time.monotonic()-16)
        try:
            assert not (await asyncio.wait_for(codec.send_outbound_message(message(word), {}), timeout=1))['success']
        finally:
            candidate_enqueued_at.reset(token)
        codec._send_budget.minute_limit = 1
        assert (await codec.send_outbound_message(message(word), {}))['success']
        result = await codec.send_outbound_message(message(word, 43), {})
        assert not result['success'] and '预算' in result['error']
        assert sender.sent == [word]
    asyncio.run(scenario())

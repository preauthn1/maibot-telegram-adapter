"""仅使用真实 codec/队列与本地假发送器，不连接 Telegram。"""
from pathlib import Path
from types import SimpleNamespace
import asyncio
import logging
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.codecs.outbound import TelegramUserOutboundCodec
from telegram_user_adapter.send_queue import SendQueue


class Sender:
    def __init__(self):
        self.sent = []
        self.fail = False
        self.empty = False

    async def get_entity(self, target):
        return target

    async def send_text(self, entity, text, **kwargs):
        if self.fail:
            raise RuntimeError('模拟发送失败')
        if self.empty:
            return None
        self.sent.append(text)
        return SimpleNamespace(id=len(self.sent))

    async def send_file(self, entity, data, **kwargs):
        return await self.send_text(entity, '<file>')


def make_codec(**kwargs):
    sender = Sender()
    codec = TelegramUserOutboundCodec(sender, logging.getLogger(__name__), **kwargs)
    codec._enable_humanize = False
    async def no_delay(*args):
        pass
    codec._humanize_before_send = no_delay
    codec._send_budget.hourly_limit = 1000
    codec._send_budget.minute_limit = 1000
    return codec, sender


async def send(codec, text):
    return await codec._send_segment(123, '123', {'type': 'text', 'data': text}, None)


def test_family_limit_is_not_exact_text_limit():
    async def scenario():
        codec, sender = make_codec()
        assert await send(codec, '那确实贵') is not None
        assert await send(codec, '正常') is not None
        assert await send(codec, '对') is None
        assert sender.sent == ['那确实贵', '正常']
    asyncio.run(scenario())


@pytest.mark.parametrize("text,expected", [("正常", None), ("端口443", "端口443"), ("用IPv6", "用IPv6"), ("对，改端口", "对，改端口")])
def test_queue_age_includes_wait_and_typing(text, expected):
    async def scenario():
        clock = [100.0]
        codec, sender = make_codec()
        queue = SendQueue(logging.getLogger(__name__), enable_quiet_hours=False, min_gap_seconds=0, max_gap_seconds=0)
        started, release = asyncio.Event(), asyncio.Event()
        async def blocking():
            started.set()
            await release.wait()
        async def delayed():
            clock[0] += 8
        codec._humanize_before_send = lambda *args: delayed()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("time.monotonic", lambda: clock[0])
            queue.start()
            try:
                first = asyncio.create_task(queue.submit(blocking))
                await started.wait()
                candidate = asyncio.create_task(queue.submit(lambda: send(codec, text)))
                await asyncio.sleep(0)
                clock[0] += 8
                release.set()
                await first
                result = await candidate
                assert (result is None) == (expected is None)
                assert sender.sent == ([] if expected is None else [expected])
            finally:
                await queue.stop()
    asyncio.run(scenario())


def test_only_successes_consume_family_slots():
    async def scenario():
        codec, sender = make_codec()
        sender.fail = True
        with pytest.raises(RuntimeError):
            await send(codec, '那确实贵')
        sender.fail = False
        sender.empty = True
        assert await send(codec, '那确实贵') is None
        sender.empty = False
        assert await send(codec, '那确实贵') is not None
        assert await send(codec, '正常') is not None
        assert await send(codec, '对') is None
    asyncio.run(scenario())


def test_successful_media_advance_window_and_failures_do_not():
    async def scenario():
        codec, sender = make_codec()
        async def outbound(seg):
            return await codec.send_outbound_message({'message_info': {'group_info': {'group_id': '123'}}, 'raw_message': [seg]}, {})
        for text in ['那确实贵', '正常']:
            assert (await outbound({'type': 'text', 'data': text}))['success']
        for _ in range(8):
            assert (await outbound({'type': 'image', 'binary_data_base64': 'eA=='}))['success']
        assert (await outbound({'type': 'text', 'data': '对'}))['success']
        assert len(sender.sent) == 11
    asyncio.run(scenario())


@pytest.mark.parametrize('budget,delay,allowed', [(15, 14.99, True), (15, 15, False), (3, 4, False)])
def test_constructor_budget_at_actual_send_boundary(budget, delay, allowed):
    async def scenario():
        codec, sender = make_codec(low_information_budget_seconds=budget)
        clock = [0.0]
        async def waiting(*args):
            clock[0] += delay
        codec._humanize_before_send = waiting
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr('time.monotonic', lambda: clock[0])
            assert (await send(codec, '正常') is not None) == allowed
        assert bool(sender.sent) == allowed
    asyncio.run(scenario())


@pytest.mark.parametrize('text', ['443', 'IPv6', '用TCP', '正常返回200', '那确实贵，换2核', 'systemctl status nginx', '对，改端口'])
def test_concrete_short_answers_not_classified(text):
    from telegram_user_adapter.low_information import is_low_information
    assert not is_low_information(text)


def test_safety_filters_remain_active():
    async def scenario():
        codec, sender = make_codec()
        assert await send(codec, 'assistant: 好的') is None
        assert await send(codec, '<tool_call></tool_call>') is None
        assert sender.sent == []
    asyncio.run(scenario())


"""显式回复目标的低信息批次去重；不连接 Telegram。"""
import asyncio

from test_low_information_outbound import make_codec


def message(text, *, chat='123', target=42, segment_target=False):
    config = {} if segment_target or target is None else {'reply_message_id': str(target)}
    segments = [{'type': 'text', 'data': text}]
    if segment_target:
        segments.insert(0, {'type': 'reply', 'data': {'target_message_id': str(target)}})
    return {'message_info': {'group_info': {'group_id': chat}, 'additional_config': config}, 'raw_message': segments}


def test_same_target_generic_batches_reserved_before_await():
    async def scenario():
        codec, sender = make_codec(low_information_limit=10)
        codec._quote_probability = 0
        started, release = asyncio.Event(), asyncio.Event()
        async def wait(*args):
            started.set()
            await release.wait()
        codec._humanize_before_send = wait
        first = asyncio.create_task(codec.send_outbound_message(message('也行'), {}))
        await started.wait()
        # 两批文本不同，不能依靠原有精确文本去重；第二批必须立即失败而非排队。
        second = asyncio.create_task(codec.send_outbound_message(message('这速度舒服', segment_target=True), {}))
        await asyncio.sleep(0)
        completed = second.done()
        release.set()
        one, two = await asyncio.gather(first, second)
        assert completed, 'reservation must precede awaited send'
        assert one['success']
        assert two['success'] is False
        assert two['error_code'] == 'low_information_target_repeat'
        assert sender.sent == ['也行']
    asyncio.run(scenario())


def test_failed_send_releases_target_reservation():
    async def scenario():
        codec, sender = make_codec(low_information_limit=10)
        sender.fail = True
        failed = await codec.send_outbound_message(message('也行'), {})
        assert failed['success'] is False
        sender.fail = False
        retried = await codec.send_outbound_message(message('这速度舒服'), {})
        assert retried['success'] is True
        assert sender.sent == ['这速度舒服']
    asyncio.run(scenario())

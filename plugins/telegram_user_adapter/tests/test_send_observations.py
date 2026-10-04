"""成功段的候选与结果保持调用局部归属。"""
import asyncio

from test_low_information_outbound import make_codec


def test_concurrent_segment_observations_are_isolated():
    async def scenario():
        codec, sender = make_codec()
        left, right = [], []
        both_waiting = asyncio.Event()
        release = asyncio.Event()
        pending = []
        original_send = sender.send_text

        async def interleaved_send(entity, text, **kwargs):
            pending.append(text)
            if len(pending) == 2:
                both_waiting.set()
            await release.wait()
            return await original_send(entity, text, **kwargs)

        sender.send_text = interleaved_send

        async def run(text, records):
            return await codec._send_segment(123, '123', {'type': 'text', 'data': text},
                                             None, observations=records)
        tasks = [asyncio.create_task(run('端口443', left)),
                 asyncio.create_task(run('使用IPv6', right))]
        try:
            await asyncio.wait_for(both_waiting.wait(), timeout=2)
            assert len(pending) == 2
            assert left == right == []
            # 强制污染共享旧字段，正确实现必须使用各调用局部变量。
            codec._last_original_text = '其他调用的候选'
            release.set()
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=2)
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert len(left) == len(right) == 1
        assert left[0]['original_text'] == '端口443'
        assert right[0]['original_text'] == '使用IPv6'
        assert left[0]['text'] == '端口443'
        assert right[0]['text'] == '使用IPv6'
        assert left[0]['message_id'] != right[0]['message_id']
    asyncio.run(scenario())


def test_failed_send_has_no_success_observation():
    async def scenario():
        codec, sender = make_codec()
        sender.empty = True
        records = []
        result = await codec._send_segment(123, '123', {'type': 'text', 'data': '端口443'},
                                           None, observations=records)
        assert result is None
        assert records == []
    asyncio.run(scenario())

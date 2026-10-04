"""仅由数据库副本沙箱调用；不启动运行时或连接平台。"""
import asyncio
import json
from collections import Counter
from src.llm_models.model_client.openai_client import _convert_messages
from src.maisaka.reasoning_engine import MaisakaReasoningEngine
from src.maisaka.runtime import MaisakaHeartFlowChatting
from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator


async def check(rows):
    engine = object.__new__(MaisakaReasoningEngine)
    runtime = object.__new__(MaisakaHeartFlowChatting)
    runtime._is_focus_mode_active_for_current_chat = lambda: False
    engine._runtime = runtime
    counts = Counter()
    generator = object.__new__(BaseMaisakaReplyGenerator)
    for batch in rows:
        history = []
        for message in batch:
            counts['input'] += 1
            if message.is_notify:
                counts['notify_skipped'] += 1
                continue
            source = MaisakaHeartFlowChatting._resolve_restored_message_source_kind(message)
            result = await engine._build_history_message(message, source_kind=source)
            if result is None:
                counts['empty'] += 1
            else:
                history.append(result)
                counts['built'] += 1
                counts[source] += 1
                counts[type(result).__name__] += 1
                item = result.to_context_item(enable_visual_message=False)
                if item is None:
                    raise RuntimeError('Built history produced no context item')
                wire = _convert_messages([item])
                if not wire:
                    raise RuntimeError('Native conversion dropped history item')
                # 只验证可序列化与实际角色分布，不把对象数量等同语义保真。
                json.dumps(wire, ensure_ascii=False)
                counts['serialized_source_items'] += 1
                counts['wire_messages'] += len(wire)
                for entry in wire:
                    counts['wire_role_' + entry['role']] += 1
        reply_items = generator._build_history_messages(history, enable_visual_message=False)
        reply_wire = _convert_messages(reply_items)
        json.dumps(reply_wire, ensure_ascii=False)
        counts['reply_batches'] += 1
        counts['reply_wire_messages'] += len(reply_wire)
        for entry in reply_wire:
            counts['reply_role_' + entry['role']] += 1
        expected_self = sum(bool(generator._extract_guided_bot_reply(h)) for h in history)
        from src.llm_models.payload_content.context_item import AssistantMessageItem
        assistant_items = [item for item in reply_items if isinstance(item, AssistantMessageItem)]
        counts['reply_assistant_items'] += len(assistant_items)
        # 原生适配器合并连续 assistant 项，wire 消息数不等于原始发言数。
        if len(assistant_items) != expected_self:
            raise RuntimeError('Replyer self-role mapping mismatch')
        # 子串存在不能证明顺序、重复次数或用户正文保真。
        # 逐项建立预期序列，仅按已确认的适配器规则合并相邻 assistant。
        expected_wire = []
        for item in reply_items:
            single = _convert_messages([item])
            if len(single) != 1:
                raise RuntimeError('Unexpected per-item history conversion')
            entry = single[0]
            if (entry['role'] == 'assistant' and expected_wire
                    and expected_wire[-1]['role'] == 'assistant'):
                content = entry.get('content')
                if not isinstance(content, str):
                    raise RuntimeError('Expected text-only assistant history')
                expected_wire[-1]['content'] += content

            else:
                expected_wire.append(dict(entry))
        if reply_wire != expected_wire:
            raise RuntimeError('Batch history order or content mismatch')
        if json.loads(json.dumps(reply_wire, ensure_ascii=False)) != expected_wire:
            raise RuntimeError('History JSON roundtrip mismatch')
        counts['exact_wire_batches'] += 1
        counts['exact_wire_items'] += len(reply_items)
    if counts['input'] != counts['built'] + counts['empty'] + counts['notify_skipped']:
        raise RuntimeError('Incomplete accounting')
    print('HISTORY_BUILD_RESULT='+json.dumps(dict(counts)))

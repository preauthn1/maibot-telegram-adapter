"""Telegram 真人账号适配器插件。

与官方 Bot API 适配器的区别在于：本插件使用 MTProto（Telethon）以**真人账号**
身份登录，因此在对方看来就是一个普通用户，而不是带 BOT 标记的机器人。

职责：
1. 用真人账号登录 Telegram 并监听新消息，转换为 Host 侧结构。
2. 把 Host 出站消息经**全局串行队列**发出，附带拟人化改写、打字模拟、
   按需上线等行为。
3. 记录结构化聊天日志，并根据反馈累积自我改进经验。
4. 通过 MessageGateway 装饰器注册为双工消息网关。
"""

from __future__ import annotations

from collections import deque, OrderedDict
from typing import Any, ClassVar, Dict, List, Optional, cast

import asyncio
import contextlib
import json
import random
import time

from maibot_sdk import MaiBotPlugin, MessageGateway, PluginConfigBase

from .codecs import TelegramUserInboundCodec
from .codecs.outbound import TelegramUserOutboundCodec
from .codecs.reactions import ReactionInfo, parse_reaction_update
from .config import TelegramUserPluginSettings
from .content_safety import detect_nsfw
from .constants import PLATFORM_NAME, SESSION_FILE_NAME, TELEGRAM_USER_GATEWAY_NAME
from .channel_publisher import ChannelPost, ChannelPublisher, select_valuable_messages
from .edit_tracker import EditTracker
from .engagement import ChatEngagementTracker
from .filters import TelegramUserChatFilter
from .high_risk_chats import (
    bind_store as bind_chat_profiles,
    blocks_tech,
    get_min_gap,
    get_reply_ratio,
    is_tech_topic,
)
from .human_rhythm import get_activity_multiplier
from .presence import PresenceManager
from .provocation import ProvocationResponder, detect_provocation
from .reaction_policy import ReactionPolicy, resolve_allowed_reactions
from .self_improvement import ChatOutcome, SelfImprovementStore, detect_suspicion, inspect_own_message
from .send_queue import PRIORITY_MENTION, PRIORITY_NORMAL, QuietHoursError, SendQueue, is_quiet_hours
from .small_chat import SmallChatModerator, estimate_read_delay
from .spam_filter import detect_spam
from .telegram_user_client import TelegramUserClient, is_available as telethon_is_available
from .transcript import ChatTranscriptLogger
from .utils import parse_topic_group_id


class TelegramUserAdapterPlugin(MaiBotPlugin):
    """Telegram 真人账号消息网关插件。"""

    config_model: ClassVar[type[PluginConfigBase] | None] = TelegramUserPluginSettings

    def __init__(self) -> None:
        """初始化插件运行时状态。"""

        super().__init__()
        self._tg_client: Optional[TelegramUserClient] = None
        self._inbound_codec: Optional[TelegramUserInboundCodec] = None
        self._outbound_codec: Optional[TelegramUserOutboundCodec] = None
        self._chat_filter: Optional[TelegramUserChatFilter] = None
        self._presence: Optional[PresenceManager] = None
        self._send_queue: Optional[SendQueue] = None
        self._transcript: Optional[ChatTranscriptLogger] = None
        self._self_improvement: Optional[SelfImprovementStore] = None
        self._run_task: Optional[asyncio.Task[None]] = None
        self._stop_requested: bool = False
        self._self_account_id: str = ""

        # chat_id -> 最近一次被 @ / 回复的时间戳，用于发送优先级。
        self._recent_mentions: Dict[str, float] = {}
        # chat_id -> 最近一条入站消息时间戳，用于统计端到端回复延迟。
        self._last_inbound_at: Dict[str, float] = {}
        # chat_id -> 我们最近发出的内容，用于自我改进反馈判定。
        self._last_outbound_text: Dict[str, str] = {}
        # chat_id -> 我们最近发言后是否已有人接话。
        self._pending_outcome: Dict[str, asyncio.Task[None]] = {}
        # (原始chat_id:int, 消息id:int) -> (会话键, 消息摘要)，用于把\"别人给我发的
        # 消息点了表情\"匹配回具体会话与内容。用有界 OrderedDict 防止长期泄漏。
        self._sent_messages: "OrderedDict[tuple[int, int], tuple[str, str]]" = OrderedDict()
        # 主动点表情的节流策略，未启用时为 None。
        self._reaction_policy: Optional[ReactionPolicy] = None
        # 正在执行的点表情任务，持引用防止被 GC 回收。
        self._reaction_tasks: set[asyncio.Task[None]] = set()
        # chat_id -> 该会话允许的表情集合（None 表示不限制），避免重复查询。
        self._allowed_reactions_cache: Dict[str, Optional[set[str]]] = {}
        # 每个会话连续发言（中间没有别人说话）的条数，用于抑制刷屏式接话。
        self._consecutive_replies: Dict[str, int] = {}
        # 触发连发上限的时刻，用于冷却计时。
        self._consecutive_blocked_at: Dict[str, float] = {}
        # (会话键, 发送者ID) -> 最近消息时间戳，用于识别单人刷屏。
        self._user_message_times: Dict[tuple[str, str], List[float]] = {}
        # 各群互动质量追踪，用于动态调整发言意愿。
        self._engagement = ChatEngagementTracker()
        # 针对性挑衅的回应节奏控制（每人只回一次）。
        self._provocation = ProvocationResponder()
        # 频率能力是否已失败过，避免逐条刷同样的错误日志。
        self._frequency_cap_failed = False
        # 小群参与率约束：某休闲小群实测 63.6%，远高于技术群的 12%。
        self._small_chat = SmallChatModerator()
        self._edit_tracker = EditTracker()
        # 各会话近期发言者，用于估算群规模（小群 vs 大群）。
        self._recent_speakers: Dict[str, deque[str]] = {}
        # 频道发布器与目标；未配置时保持 None，表示功能关闭。
        self._channel_publisher: Optional[ChannelPublisher] = None
        self._channel_target: Optional[str] = None
        # 持有延迟发布任务的强引用，避免被 GC 提前回收。
        self._channel_tasks: set[asyncio.Task[None]] = set()

    async def on_load(self) -> None:
        """插件加载时根据配置决定是否登录。"""

        # 绑定每群画像卡（data/plugins/<id>/chats/<chat_id>/SKILL.md）。
        # 卡片支持热加载，改完保存即生效，不用重启。
        bind_chat_profiles(self.ctx.paths.data_dir / "chats")

        await self._verify_capabilities()
        await self._restart_if_needed()

    async def _verify_capabilities(self) -> None:
        """启动时实探一次所需能力，权限缺失立刻报错。

        动机：``frequency.set_adjust`` 曾因未在 _manifest.json 声明而被
        E_CAPABILITY_DENIED 拒绝，但异常在调用处被 except 成 warning，
        群权重调度整整一轮提交都处于静默失效状态而没人发现。

        与其依赖每个调用点都正确记日志，不如在启动时集中探一次——
        权限这类问题在启动时就是确定的，没必要等到运行时逐条试错。
        """

        # 用无害的探测值调用一次：只为触发权限校验，不改变实际行为。
        # chat_id 传空串时 Host 不会命中任何会话。
        try:
            await self.ctx.call_capability(
                "frequency.set_adjust", chat_id="", value=1.0
            )
        except Exception as exc:  # noqa: BLE001 - 探测失败本身就是要报的结果
            message = str(exc)
            if "E_CAPABILITY_DENIED" in message:
                self.ctx.logger.error(
                    "能力自检失败：frequency.set_adjust 未获授权，"
                    "群权重调度将不生效。请在 _manifest.json 的 capabilities "
                    f"中声明该能力。原始错误: {message}"
                )
                return
            # 其他错误（如空 chat_id 被拒）说明权限是通的，只是参数无效。
            self.ctx.logger.debug(f"能力自检：frequency.set_adjust 权限正常 ({message})")
            return

        self.ctx.logger.debug("能力自检：frequency.set_adjust 权限正常")

    async def on_unload(self) -> None:
        """插件卸载时断开连接。"""

        await self._stop_client()

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str) -> None:
        """配置更新后重建连接。

        Args:
            scope: 配置作用域。
            config_data: 新的配置数据。
            version: 配置版本。
        """

        del version
        if scope != "self":
            return
        self.set_plugin_config(config_data)
        await self._restart_if_needed()

    @MessageGateway(
        name=TELEGRAM_USER_GATEWAY_NAME,
        route_type="duplex",
        platform=PLATFORM_NAME,
        protocol="telegram_mtproto_user",
        description="Telegram 真人账号双工消息网关（MTProto / Telethon）",
    )
    async def handle_telegram_user_gateway(
        self,
        message: Dict[str, Any],
        route: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """处理 Host 出站消息，经全局串行队列以真人账号身份发送。

        Args:
            message: 出站标准消息字典。
            route: Platform IO 路由信息。
            metadata: 附加元数据。
            **kwargs: 兼容占位参数。

        Returns:
            Dict[str, Any]: 标准化发送结果。
        """

        del metadata, kwargs

        outbound_codec = self._outbound_codec
        send_queue = self._send_queue
        if outbound_codec is None or send_queue is None:
            return {"success": False, "error": "Telegram 真人账号适配器未初始化"}

        chat_id = self._resolve_outbound_chat_id(message)

        # 连发抑制：真人不会在群里贴着一个人连续接话。线上真实翻车样本是
        # 22 条消息里我们插了 7 句，对方随即质问\"ai？\"。超过上限就闭嘴，
        # 直到别人说话把计数重置。
        if chat_id and self._is_consecutive_limited(chat_id):
            if self._transcript is not None:
                await self._transcript.log_event(
                    chat_id,
                    "consecutive_limit_drop",
                    {"consecutive": self._consecutive_replies.get(chat_id, 0)},
                )
            return {"success": False, "error": "连续发言已达上限，本条不发送"}

        priority = self._resolve_priority(chat_id)
        enqueued_at = time.monotonic()

        async def _do_send() -> Dict[str, Any]:
            return await outbound_codec.send_outbound_message(message, route or {})

        try:
            result = await send_queue.submit(
                _do_send,
                priority=priority,
                label=chat_id or "unknown",
            )
        except QuietHoursError:
            # 静默时段：安静丢弃，绝不向聊天回显任何内容（需求 4 + 9）。
            if self._transcript is not None and chat_id:
                await self._transcript.log_event(
                    chat_id,
                    "quiet_hours_drop",
                    {"reason": "UTC+8 静默时段内不发送"},
                )
            return {"success": False, "error": "quiet_hours", "silent": True}
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 出站异常统一转成静默失败
            self.ctx.logger.error(f"Telegram 发送失败: {exc}")
            if self._transcript is not None and chat_id:
                await self._transcript.log_event(
                    chat_id,
                    "send_error",
                    {"error": str(exc)},
                )
            # 需求 9：出错绝不向聊天回显，只返回失败让上游静默处理。
            return {"success": False, "error": str(exc), "silent": True}

        if result.get("success") and chat_id:
            await self._after_successful_send(
                chat_id=chat_id,
                message=message,
                result=result,
                enqueued_at=enqueued_at,
                priority=priority,
                outbound_codec=outbound_codec,
            )

        return result

    async def _after_successful_send(
        self,
        *,
        chat_id: str,
        message: Dict[str, Any],
        result: Dict[str, Any],
        enqueued_at: float,
        priority: int,
        outbound_codec: TelegramUserOutboundCodec,
    ) -> None:
        """发送成功后记录日志并安排效果反馈。

        Args:
            chat_id: 目标聊天 ID。
            message: 出站消息字典。
            result: 发送结果。
            enqueued_at: 入队时间戳。
            priority: 队列优先级。
            outbound_codec: 出站编解码器，用于取观测指标。
        """

        sent_text = self._extract_text_from_message(message)
        self._last_outbound_text[chat_id] = sent_text

        # 连发计数 +1。别人插话时会在入站侧清零。
        self._consecutive_replies[chat_id] = self._consecutive_replies.get(chat_id, 0) + 1

        # 出站自省：检查\"我刚才说的话\"本身有没有越界（怼人、顺着下流话题接话）。
        # 人设约束只是概率性的，模型仍可能翻车；把翻车样本记下来回灌 prompt，
        # 才能让同类错误越来越少，而不是每次都靠人工发现再改词库。
        violation_kind, violation_hits = inspect_own_message(sent_text)
        if violation_kind and self._self_improvement is not None:
            await self._self_improvement.record_outcome(
                ChatOutcome(
                    chat_id=chat_id,
                    text=sent_text,
                    violation_kind=violation_kind,
                    violation_hits=violation_hits,
                )
            )
            if self._transcript is not None:
                await self._transcript.log_event(
                    chat_id=chat_id,
                    event="self_violation",
                    detail={"kind": violation_kind, "hits": violation_hits},
                )

        # 记入小群参与率统计，并处理道别后的静默期。
        self._small_chat.record_outbound(chat_id, sent_text)

        inbound_at = self._last_inbound_at.get(chat_id)
        reply_latency = (time.monotonic() - inbound_at) if inbound_at else None
        typing_seconds = outbound_codec.last_typing_seconds
        queue_wait = max(0.0, time.monotonic() - enqueued_at - typing_seconds)

        if self._transcript is not None:
            await self._transcript.log_outbound(
                chat_id=chat_id,
                message_id=result.get("external_message_id"),
                text=sent_text,
                original_text=outbound_codec.last_original_text or sent_text,
                queue_wait_seconds=queue_wait,
                typing_seconds=typing_seconds,
                reply_latency_seconds=reply_latency,
                priority=priority,
                humanize_rules=outbound_codec.last_humanize_rules,
                reply_is_quote=outbound_codec.last_reply_is_quote,
            )

        # 发言后清除该群的提及标记，避免长期占用高优先级。
        self._recent_mentions.pop(chat_id, None)

        # 记录本账号发出的消息，供表情回应匹配回具体会话与内容。
        self._remember_sent_message(chat_id, result.get("external_message_id"), sent_text)

        self._schedule_outcome_check(chat_id, sent_text)

    def _remember_sent_message(
        self, session_key: str, external_message_id: Any, sent_text: str
    ) -> None:
        """记录一条本账号发出的消息，用于后续表情回应匹配。

        表情回应更新只带原始 chat_id（不含 topic 后缀）与消息 ID，因此这里
        把会话键还原成原始 chat_id 再入表，键为 ``(原始chat_id, 消息id)``。

        Args:
            session_key: 出站会话键（群聊为含 topic 的虚拟 group_id）。
            external_message_id: Telethon 返回的消息 ID。
            sent_text: 消息摘要文本。
        """

        settings = self._load_settings()
        if not settings.behavior.receive_reactions:
            return

        message_id = self._safe_int(external_message_id)
        if message_id is None:
            return

        raw_chat_id_str, _ = parse_topic_group_id(session_key)
        raw_chat_id = self._safe_int(raw_chat_id_str)
        if raw_chat_id is None:
            return

        key = (raw_chat_id, message_id)
        # 更新已有键要移到末尾，保证 LRU 语义。
        self._sent_messages.pop(key, None)
        self._sent_messages[key] = (session_key, sent_text)

        # 有界保存：只留最近 500 条自发消息的表情匹配窗口，防止内存无限增长。
        while len(self._sent_messages) > 500:
            self._sent_messages.popitem(last=False)

    def _schedule_outcome_check(self, chat_id: str, sent_text: str) -> None:
        """安排一次"有没有人接话"的判定。

        Args:
            chat_id: 聊天 ID。
            sent_text: 我们发出的内容。
        """

        store = self._self_improvement
        if store is None or not store.enabled:
            return

        settings = self._load_settings()
        wait_seconds = settings.observability.reply_wait_seconds
        if wait_seconds <= 0:
            return

        existing = self._pending_outcome.pop(chat_id, None)
        if existing is not None and not existing.done():
            existing.cancel()

        async def _check() -> None:
            try:
                await asyncio.sleep(wait_seconds)
            except asyncio.CancelledError:
                return
            # 走到这里说明窗口内没有被入站消息取消，即无人接话。
            with contextlib.suppress(Exception):
                await store.record_outcome(
                    ChatOutcome(chat_id=chat_id, text=sent_text, got_reply=False)
                )
            self._pending_outcome.pop(chat_id, None)

        self._pending_outcome[chat_id] = asyncio.create_task(
            _check(), name=f"telegram_user_adapter.outcome.{chat_id}"
        )

    def _resolve_outbound_chat_id(self, message: Dict[str, Any]) -> str:
        """从出站消息中解析目标 chat_id（含 topic 后缀）。

        Args:
            message: 出站消息字典。

        Returns:
            str: chat_id 字符串；无法解析时返回空串。
        """

        message_info = message.get("message_info", {}) or {}
        additional = message_info.get("additional_config", {}) or {}
        group_info = message_info.get("group_info") or {}
        user_info = message_info.get("user_info") or {}

        for candidate in (
            additional.get("platform_io_target_group_id"),
            group_info.get("group_id"),
            additional.get("platform_io_target_user_id"),
            user_info.get("user_id"),
        ):
            if candidate:
                return str(candidate)
        return ""

    def _recent_speaker_count(self, session_key: str) -> int:
        """估算会话近期的活跃发言人数。

        用于区分"小群"与"大群"：同样的发言量在 4 人小群里很扎眼，
        在几百人的群里则会被稀释。

        Args:
            session_key: 会话 ID。

        Returns:
            int: 近期不同发言者的数量。
        """

        speakers = self._recent_speakers.get(session_key)
        return len(speakers) if speakers else 1

    def _note_speaker(self, session_key: str, sender_id: str) -> None:
        """记录一个发言者，用于估算会话规模。

        只保留最近的若干人：群成员会变化，太久以前的发言者不能
        代表当前的活跃规模。

        Args:
            session_key: 会话 ID。
            sender_id: 发言者 ID。
        """

        speakers = self._recent_speakers.setdefault(session_key, deque(maxlen=40))
        if sender_id not in speakers:
            speakers.append(sender_id)

    async def _maybe_publish_to_channel(
        self, session_key: str, text: str, message_dict: Dict[str, Any]
    ) -> None:
        """把有价值的群消息按节奏转发到自己的频道。

        节奏控制全部交给 ChannelPublisher：随机延迟、每日配额、
        最小间隔、静默时段、来源去重。这里只负责筛内容和实际发送。

        Args:
            session_key: 来源会话。
            text: 消息正文。
            message_dict: 入站消息字典。
        """

        publisher = self._channel_publisher
        if publisher is None or self._channel_target is None:
            return

        # 内容筛选保守：宁可少发，不可发垃圾。
        # 频道内容质量差本身也是一种暴露。
        picked = select_valuable_messages([{"text": text}], limit=1)
        if not picked:
            return

        raw_id = message_dict.get("message_id")
        post = ChannelPost(
            text=text,
            source_chat_id=session_key,
            source_message_id=int(raw_id) if raw_id else None,
        )
        if publisher.is_duplicate(post):
            return

        decision = publisher.can_publish(monotonic_now=time.monotonic())
        if not decision.allowed:
            self.ctx.logger.debug(f"频道发布跳过: {decision.reason}")
            return

        # 先占位再延迟：并发入站时避免多条同时通过配额检查。
        publisher.mark_published(post, monotonic_now=time.monotonic())
        self.ctx.logger.info(
            f"频道发布已排程: 来源={session_key} 延迟={decision.delay_seconds:.0f}秒"
        )
        self._channel_tasks.add(
            asyncio.create_task(self._deliver_channel_post(post, decision.delay_seconds))
        )

    async def _deliver_channel_post(self, post: ChannelPost, delay: float) -> None:
        """延迟后真正发出频道消息。

        延迟是防暴露的关键：消息一出现就立刻转发，时间相关性太强，
        一看就是自动化。

        Args:
            post: 待发布内容。
            delay: 随机延迟秒数。
        """

        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

        client = self._tg_client
        publisher = self._channel_publisher
        if client is None or publisher is None or self._channel_target is None:
            return

        try:
            entity = await client.get_entity(self._channel_target)
            if publisher.should_forward(post):
                await client.forward_to_channel(
                    entity, post.source_chat_id, post.source_message_id
                )
            else:
                await client.publish_to_channel(entity, post.text)
        except Exception as exc:  # noqa: BLE001 - 发布失败不影响聊天主流程
            # 明确报错而非静默：整个功能没生效必须能被发现。
            self.ctx.logger.error(f"频道发布失败: target={self._channel_target} {exc}")
            return

        self.ctx.logger.info(f"频道发布成功: {post.text[:30]!r}")

    async def _send_provocation_reply(
        self, session_key: str, text: str, message_dict: Dict[str, Any]
    ) -> None:
        """发送一条挑衅回应。

        绕过 LLM 直接发固定话术：被骂时不需要推理，而且固定话术
        可控——不会因为模型被激怒而说出更难听的话。

        引用对方那条消息，让回应指向明确，避免群里其他人误会。

        Args:
            session_key: 会话键。
            text: 要发送的话。
            message_dict: 触发本次回应的入站消息。
        """

        client = self._tg_client
        if client is None:
            return

        reply_to = message_dict.get("message_id")
        try:
            entity = await client.get_entity(session_key)
            await client.client.send_message(
                entity,
                text,
                reply_to=int(reply_to) if reply_to else None,
            )
        except Exception as exc:  # noqa: BLE001 - 回应失败不影响主流程
            self.ctx.logger.warning(f"挑衅回应发送失败: chat={session_key} {exc}")
            return

        if self._transcript is not None:
            await self._transcript.log_event(
                chat_id=session_key,
                event="provocation_reply",
                detail={"text": text},
            )

    async def _sync_engagement_multiplier(self, chat_id: str) -> None:
        """把该会话的互动权重写回 Host 的发言频率调节槽。

        Host 侧 ``_talk_frequency_adjust`` 会被 ``_get_effective_reply_frequency()``
        直接乘进去，因此改这一个值即可影响所有下游阈值。

        Args:
            chat_id: 会话 ID。
        """

        multiplier = self._engagement.compute_multiplier(chat_id)

        # 叠加真人作息曲线：深夜压到极低、傍晚抬高。
        # 实测账号 95% 发言挤在 07-09 点，而真人这三小时只占 20%，
        # 这种\"每天固定时段集中说话\"的模式比说错话更容易暴露。
        multiplier *= get_activity_multiplier()

        if not self._engagement.should_apply(chat_id, multiplier):
            return

        try:
            await self.ctx.call_capability(
                "frequency.set_adjust", chat_id=chat_id, value=multiplier
            )
        except Exception as exc:  # noqa: BLE001 - 能力调用失败不应影响消息处理
            # 只在首次失败时告警。权限缺失这类问题会每条消息复现一次，
            # 逐条打日志会淹没真正有用的信息；但也不能静默——
            # 否则功能整个没生效都发现不了。
            if not self._frequency_cap_failed:
                self._frequency_cap_failed = True
                self.ctx.logger.error(
                    f"发言频率倍率写回失败，群权重调度将不生效: {exc}"
                )
            return

        self._engagement.mark_applied(chat_id, multiplier)
        self.ctx.logger.info(f"群权重已更新: chat={chat_id} 倍率={multiplier:.2f}")

    def _is_user_flooding(self, session_key: str, sender_id: str) -> bool:
        """判断某个用户是否在刷屏消耗 token。

        只统计\"引发我们回复\"的消息，正常你来我往的聊天远达不到上限；
        真被刷屏时只对该用户静音，群里其他人不受影响。

        Args:
            session_key: 会话键。
            sender_id: 发送者 ID。

        Returns:
            bool: 该用户已超限时返回 ``True``。
        """

        if not sender_id:
            return False

        settings = self._load_settings()
        limit = settings.behavior.per_user_reply_limit
        window = settings.behavior.per_user_window

        key = (session_key, sender_id)
        now = time.monotonic()
        stamps = self._user_message_times.setdefault(key, [])

        # 丢弃窗口外的记录，保持列表有界。
        cutoff = now - window
        stamps[:] = [t for t in stamps if t >= cutoff]
        stamps.append(now)

        if len(stamps) > limit:
            self.ctx.logger.info(
                f"用户消息过于频繁，暂时不回复: chat={session_key} "
                f"sender={sender_id} 窗口内={len(stamps)}条 上限={limit}"
            )
            return True
        return False

    def _is_consecutive_limited(self, chat_id: str) -> bool:
        """判断某会话是否已达连续发言上限。

        Args:
            chat_id: 会话键。

        Returns:
            bool: 达到上限且仍在冷却期内时返回 ``True``。
        """

        settings = self._load_settings()
        limit = settings.behavior.max_consecutive_replies
        count = self._consecutive_replies.get(chat_id, 0)
        if count < limit:
            return False

        # 达到上限后进入冷却；冷却结束自动放行并清零，
        # 避免\"一旦触发就永久闭嘴\"。
        blocked_at = self._consecutive_blocked_at.get(chat_id)
        now = time.monotonic()
        if blocked_at is None:
            self._consecutive_blocked_at[chat_id] = now
            self.ctx.logger.info(
                f"连续发言达到上限({limit})，进入冷却: chat={chat_id}"
            )
            return True

        if (now - blocked_at) >= settings.behavior.consecutive_cooldown:
            self._consecutive_replies[chat_id] = 0
            self._consecutive_blocked_at.pop(chat_id, None)
            return False
        return True

    def _resolve_priority(self, chat_id: str) -> int:
        """按是否被 @ / 回复决定发送优先级。

        Args:
            chat_id: 目标聊天 ID。

        Returns:
            int: 优先级数值，越小越优先。
        """

        if chat_id and chat_id in self._recent_mentions:
            return PRIORITY_MENTION
        return PRIORITY_NORMAL

    @staticmethod
    def _extract_text_from_message(message: Dict[str, Any]) -> str:
        """把出站消息段中的文本拼起来。

        Args:
            message: 出站消息字典。

        Returns:
            str: 文本内容。
        """

        raw_message = message.get("raw_message")
        if not isinstance(raw_message, list):
            return ""
        parts = [
            seg.get("data", "")
            for seg in raw_message
            if isinstance(seg, dict) and seg.get("type") == "text" and isinstance(seg.get("data"), str)
        ]
        return "".join(parts)

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        """把值安全转换为整数。

        Args:
            value: 待转换的值。

        Returns:
            Optional[int]: 转换成功返回整数；无法转换时返回 ``None``。
        """

        if value is None:
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _load_settings(self) -> TelegramUserPluginSettings:
        """读取当前插件配置。

        Returns:
            TelegramUserPluginSettings: 强类型配置对象。
        """

        return cast(TelegramUserPluginSettings, self.config)

    async def _restart_if_needed(self) -> None:
        """按当前配置重建 Telegram 连接。"""

        settings = self._load_settings()
        await self._stop_client()

        if not settings.should_connect():
            self.ctx.logger.info("Telegram 真人账号适配器保持空闲状态，因为插件未启用")
            return
        if not settings.validate_runtime_config(self.ctx.logger):
            return
        if not telethon_is_available():
            self.ctx.logger.error(
                "Telegram 真人账号适配器依赖 telethon，请先安装：uv pip install telethon cryptg"
            )
            return

        account = settings.telegram_account
        behavior = settings.behavior
        quiet = settings.quiet_hours
        observability = settings.observability

        # 按配置构建频道发布器。未启用或没填目标时保持 None，
        # 让 _maybe_publish_to_channel 直接短路。
        channel = settings.channel_publish
        if channel.enabled and channel.target.strip():
            self._channel_target = channel.target.strip()
            self._channel_publisher = ChannelPublisher(
                daily_quota=channel.daily_quota,
                min_interval=channel.min_interval_seconds,
                delay_min=channel.delay_min_seconds,
                delay_max=channel.delay_max_seconds,
                forwardable_chats=set(channel.forwardable_chats),
            )
            self.ctx.logger.info(
                f"频道发布已启用: target={self._channel_target} "
                f"每日上限={channel.daily_quota} "
                f"随机延迟={channel.delay_min_seconds:.0f}-{channel.delay_max_seconds:.0f}秒"
            )
        else:
            self._channel_target = None
            self._channel_publisher = None

        self._tg_client = TelegramUserClient(
            api_id=account.api_id,
            api_hash=account.api_hash,
            session_string=account.session_string,
            session_path=self.ctx.paths.data_dir / SESSION_FILE_NAME,
            proxy_url=account.proxy_url,
            device_model=account.device_model,
            system_version=account.system_version,
            app_version=account.app_version,
            logger=self.ctx.logger,
        )

        try:
            connected = await self._tg_client.connect()
        except Exception as exc:  # noqa: BLE001 - 登录失败必须完整暴露原因
            self.ctx.logger.error(f"Telegram 真人账号登录失败: {exc}")
            await self._stop_client()
            return

        if not connected:
            await self._stop_client()
            return

        me = self._tg_client.me
        self_id = int(getattr(me, "id", 0) or 0)
        self_username = getattr(me, "username", None)
        if self_id <= 0:
            self.ctx.logger.error("无法获取 Telegram 账号身份，适配器不会启动监听")
            await self._stop_client()
            return

        self._self_account_id = str(self_id)
        self.ctx.logger.info(
            f"Telegram 真人账号已登录: id={self_id}, username={self_username}, "
            f"phone={getattr(me, 'phone', None)}"
        )

        # 把账号资料写给主程序：prompt 需要知道"别人看到的我是谁"，
        # 否则模型只能靠猜，实测出现过私聊里自称"群里的人"的破绽。
        self._write_account_profile(me, self_username)

        # 登录后立刻置为离线，避免 Telethon 连接本身让账号显示在线（需求 10）。
        if behavior.online_only_when_chatting:
            self._presence = PresenceManager(
                self._tg_client,
                self.ctx.logger,
                linger_min=behavior.online_linger_min,
                linger_max=behavior.online_linger_max,
            )
            await self._presence.force_offline()

        self._transcript = ChatTranscriptLogger(
            self.ctx.paths.data_dir / "transcripts",
            self.ctx.logger,
            enabled=observability.enable_transcript_log,
        )
        self._self_improvement = SelfImprovementStore(
            self.ctx.paths.data_dir,
            self.ctx.logger,
            enabled=observability.enable_self_improvement,
        )
        if self._self_improvement.enabled:
            self.ctx.logger.info(
                f"自我改进文件: {self._self_improvement.soul_path} / {self._self_improvement.skill_path}"
            )

        self._inbound_codec = TelegramUserInboundCodec(self._tg_client, self.ctx.logger)
        self._inbound_codec.set_self(self_id, self_username)
        self._inbound_codec.set_media_policy(
            download_media=behavior.download_media,
            max_media_bytes=int(behavior.max_media_size_mb * 1024 * 1024),
        )

        self._outbound_codec = TelegramUserOutboundCodec(self._tg_client, self.ctx.logger)
        self._outbound_codec.set_behavior(
            simulate_typing=behavior.simulate_typing,
            typing_cps=behavior.typing_chars_per_second,
            min_think_delay=behavior.min_think_delay,
            max_typing_delay=behavior.max_typing_delay,
            enable_humanize=behavior.enable_humanize,
            max_emoji=behavior.max_emoji_per_message,
            quote_probability=behavior.quote_probability,
        )
        self._outbound_codec.set_presence_manager(self._presence)

        self._send_queue = SendQueue(
            self.ctx.logger,
            quiet_start_hour=quiet.start_hour,
            quiet_end_hour=quiet.end_hour,
            enable_quiet_hours=quiet.enable,
            min_gap_seconds=behavior.min_send_gap,
            max_gap_seconds=behavior.max_send_gap,
        )
        self._send_queue.start()

        self._chat_filter = TelegramUserChatFilter(self.ctx.logger)

        # 主动点表情：默认关闭，开启后按概率/冷却/每小时上限三重节流。
        if behavior.send_reactions:
            self._reaction_policy = ReactionPolicy(
                probability=behavior.reaction_probability,
                chat_cooldown=behavior.reaction_chat_cooldown,
                hourly_limit=behavior.reaction_hourly_limit,
            )
            self.ctx.logger.info(
                f"主动表情回应已启用: 概率={behavior.reaction_probability} "
                f"冷却={behavior.reaction_chat_cooldown}s 每小时上限={behavior.reaction_hourly_limit}"
            )

        self._tg_client.add_message_handler(
            self._on_new_message,
            incoming_only=behavior.ignore_outgoing_from_other_devices,
        )

        # 编辑事件：真人常改口，且改写身份质问是探测手法，必须感知。
        self._tg_client.add_edit_handler(
            self._on_message_edited,
            incoming_only=behavior.ignore_outgoing_from_other_devices,
        )

        # 表情回应走 raw MTProto 更新，NewMessage 事件覆盖不到。
        if behavior.receive_reactions:
            from telethon.tl import types as _tl_types

            self._tg_client.add_raw_update_handler(
                self._on_reaction_update,
                _tl_types.UpdateMessageReactions,
            )

        await self.ctx.gateway.update_state(
            gateway_name=TELEGRAM_USER_GATEWAY_NAME,
            ready=True,
            platform=PLATFORM_NAME,
            account_id=self._self_account_id,
        )

        self._stop_requested = False
        self._run_task = asyncio.create_task(self._run_loop(), name="telegram_user_adapter.run")

    def _write_account_profile(self, me: Any, username: Optional[str]) -> None:
        """把当前账号资料写给主程序，供 prompt 场景说明使用。

        主程序运行在另一个进程，无法直接访问 Telethon 的 me 对象，
        因此通过插件数据目录下的约定文件传递。

        Args:
            me: Telethon 返回的当前账号对象。
            username: 账号用户名，可能为 ``None``。
        """

        first_name = getattr(me, "first_name", None) or ""
        last_name = getattr(me, "last_name", None) or ""
        display_name = f"{first_name} {last_name}".strip() or username or ""

        profile = {
            "platform": PLATFORM_NAME,
            "user_id": str(getattr(me, "id", "")),
            "username": username or "",
            "display_name": display_name,
        }

        try:
            path = self.ctx.paths.data_dir / "account_profile.json"
            path.write_text(
                json.dumps(profile, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            # 写不成只是少一段场景说明，不该影响登录与监听。
            self.ctx.logger.warning(f"写入账号资料失败: {exc}")

    async def _stop_client(self) -> None:
        """停止监听并释放 Telegram 连接。"""

        self._stop_requested = True

        for task in list(self._pending_outcome.values()):
            if not task.done():
                task.cancel()
        self._pending_outcome.clear()

        with contextlib.suppress(Exception):
            await self.ctx.gateway.update_state(
                gateway_name=TELEGRAM_USER_GATEWAY_NAME,
                ready=False,
                platform=PLATFORM_NAME,
            )

        if self._send_queue is not None:
            with contextlib.suppress(Exception):
                await self._send_queue.stop()
            self._send_queue = None

        if self._presence is not None:
            with contextlib.suppress(Exception):
                await self._presence.force_offline()
            self._presence = None

        run_task = self._run_task
        self._run_task = None
        if run_task is not None:
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await run_task

        if self._tg_client is not None:
            with contextlib.suppress(Exception):
                await self._tg_client.close()
            self._tg_client = None

        self._inbound_codec = None
        self._outbound_codec = None
        self._chat_filter = None
        self._transcript = None
        self._self_improvement = None
        self._recent_mentions.clear()
        self._last_inbound_at.clear()
        self._last_outbound_text.clear()
        self._sent_messages.clear()

        # 取消未完成的点表情任务，避免连接已断还在尝试发请求。
        for task in list(self._reaction_tasks):
            if not task.done():
                task.cancel()
        self._reaction_tasks.clear()
        self._reaction_policy = None
        self._allowed_reactions_cache.clear()

    async def _run_loop(self) -> None:
        """保持 Telethon 事件循环运行直到断开。"""

        tg_client = self._tg_client
        if tg_client is None:
            return

        self.ctx.logger.info("Telegram 真人账号适配器开始监听消息...")
        try:
            await tg_client.run_until_disconnected()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 事件循环异常需要完整记录
            self.ctx.logger.error(f"Telegram 监听循环异常退出: {exc}")

    async def _on_new_message(self, event: Any) -> None:
        """处理一条 Telethon 新消息事件。

        Args:
            event: Telethon ``NewMessage.Event``。
        """

        settings = self._load_settings()
        behavior = settings.behavior

        inbound_codec = self._inbound_codec
        chat_filter = self._chat_filter
        tg_client = self._tg_client
        if inbound_codec is None or chat_filter is None or tg_client is None:
            return

        sender_id = getattr(event, "sender_id", None)
        chat_id = getattr(event, "chat_id", None)
        if sender_id is None or chat_id is None:
            return

        if behavior.ignore_self_messages and str(sender_id) == self._self_account_id:
            return

        sender = None
        with contextlib.suppress(Exception):
            sender = await event.get_sender()

        allowed = chat_filter.check_allow(
            settings.chat,
            user_id=str(sender_id),
            chat_id=str(chat_id),
            is_private=bool(getattr(event, "is_private", False)),
            is_channel=bool(getattr(event, "is_channel", False)) and not bool(getattr(event, "is_group", False)),
            sender_is_bot=bool(getattr(sender, "bot", False)),
        )
        if not allowed:
            return

        if behavior.mark_read:
            if behavior.read_delay > 0:
                await asyncio.sleep(behavior.read_delay)
            await tg_client.mark_read(await self._resolve_read_entity(event), getattr(event.message, "id", None))

        try:
            message_dict = await inbound_codec.build_message_dict(event)
        except Exception as exc:  # noqa: BLE001 - 转换失败需要暴露具体消息
            self.ctx.logger.error(f"Telegram 消息转换失败: {exc}")
            return

        if message_dict is None:
            return

        # 用虚拟 group_id（含 topic）作为会话键，保证各群/各话题上下文隔离（需求 6）。
        session_key = self._resolve_inbound_session_key(message_dict, chat_id)
        incoming_text = message_dict.get("processed_plain_text", "") or ""
        is_mention = bool(message_dict.get("is_at"))

        # 静默时段直接在入站侧丢弃，不喂给 Host。
        #
        # 静默检查原本只在出站闸门，导致消息照常触发完整 LLM 推理，
        # 生成完回复才被丢掉（实测日志：SendService 发送失败 error=quiet_hours）。
        # 白烧一次推理，还会把静默期的消息混进上下文，
        # 让醒来后的第一句话像在回应几小时前的对话。
        quiet = settings.quiet_hours
        if quiet.enable and is_quiet_hours(
            start_hour=quiet.start_hour, end_hour=quiet.end_hour
        ):
            self.ctx.logger.debug(f"静默时段内丢弃入站消息: session={session_key}")
            if self._transcript is not None:
                await self._transcript.log_event(
                    chat_id=session_key,
                    event="quiet_hours_inbound_drop",
                    detail={"reason": "UTC+8 静默时段内不处理入站消息"},
                )
            return

        # 广告直接丢弃：跟广告搭话纯烧 token，而且真人看到广告是划过去的，
        # 逐条认真回复本身就是机器人特征。必须在进上下文之前拦掉。
        is_spam, spam_signals = detect_spam(incoming_text)
        if is_spam:
            self.ctx.logger.info(
                f"检测到广告，已丢弃: session={session_key} 信号={spam_signals}"
            )
            if self._transcript is not None:
                await self._transcript.log_event(
                    chat_id=session_key,
                    event="spam_dropped",
                    detail={"signals": spam_signals, "sender_id": str(sender_id)},
                )
            return

        # NSFW 内容直接丢弃整条消息，不进上下文、不进 Host、不触发回复。
        # 必须在入站侧拦：一旦进了上下文，即使这轮不复述，也会带偏后续几轮的
        # 语气和话题走向，出站过滤堵不住这个口子。
        is_nsfw, nsfw_hits = detect_nsfw(incoming_text)
        if is_nsfw:
            # 只记命中词到本地日志用于排查，绝不回显到聊天里。
            self.ctx.logger.info(
                f"检测到 NSFW 内容，已丢弃该条上下文: session={session_key} 命中={nsfw_hits}"
            )
            if self._transcript is not None:
                await self._transcript.log_event(
                    chat_id=session_key,
                    event="nsfw_dropped",
                    detail={"hits": nsfw_hits, "sender_id": str(sender_id)},
                )
            return

        self._last_inbound_at[session_key] = time.monotonic()

        # 别人说话了，连发链条断开，重新计数。
        self._consecutive_replies.pop(session_key, None)
        self._consecutive_blocked_at.pop(session_key, None)

        # 防刷 token：同一个人在窗口内引发过多回复时暂时不再理他，
        # 但不影响群里其他人正常对话。
        # 只统计有实际文本的消息——贴纸、图片、空消息本来就不会触发
        # LLM 推理，把它们计入配额会让正常用户被误限流。
        if incoming_text.strip() and self._is_user_flooding(session_key, str(sender_id)):
            if self._transcript is not None:
                await self._transcript.log_event(
                    chat_id=session_key,
                    event="user_flood_ignored",
                    detail={"sender_id": str(sender_id)},
                )
            return

        # 主动点表情：放在 NSFW 拦截之后，避免给不良内容点赞。
        # 用独立任务跑，点表情要等待随机停顿，绝不能阻塞入站路由。
        self._maybe_schedule_reaction(event, chat_id, incoming_text)

        if is_mention:
            # 需求 5：被 @ 或被回复时，该群下次发送享有最高优先级。
            self._recent_mentions[session_key] = time.monotonic()

            # 被点名辱骂时硬气回一句。只在\"直接针对我们\"时触发——
            # 群里骂别人不关我们的事，泛化判断会误伤无辜的人。
            # 回应不带脏字，且同一个人只回一次：对方要的就是反应，
            # 给一次就够，继续纠缠不再理会。
            is_provoked, provoke_hits = detect_provocation(
                incoming_text, is_directed=True
            )
            if is_provoked:
                comeback = self._provocation.build_response(
                    session_key, str(sender_id)
                )
                if comeback is not None:
                    self.ctx.logger.info(
                        f"检测到针对性挑衅，回应一次: chat={session_key} "
                        f"sender={sender_id} 命中={provoke_hits}"
                    )
                    await self._send_provocation_reply(
                        session_key, comeback, message_dict
                    )
                else:
                    self.ctx.logger.info(
                        f"挑衅冷却中，不再回应: chat={session_key} sender={sender_id}"
                    )
                return

            # 被 @ 或被回复是最可靠的\"真实互动\"信号：记入群权重。
            # 注意按人去重（tracker 内部对单用户设了计数上限），
            # 一个人反复 @ 我们顶不高这个群的权重，防的就是刷 token。
            self._engagement.record_engagement(session_key, str(sender_id))
            await self._sync_engagement_multiplier(session_key)

        # 每条入站都同步一次作息倍率——只在被 @ 时更新的话，
        # 深夜没人 @ 我们时作息压制就不会生效。
        #
        # 同时把这条消息记为「普通群聊活动」：只记被 @ 的话，
        # compute_multiplier 会因 events 为空而恒返回最低倍率，
        # 表现就是群里聊得火热而账号一直潜水（实测 8 个群全是 0.77）。
        self._engagement.record_activity(session_key, str(sender_id))
        await self._sync_engagement_multiplier(session_key)

        # 模拟真人的「读完再回」延迟。
        #
        # 8-30 在某休闲小群 50 秒内以 4/4/1/2 秒的间隔连续接话 4 次，
        # 对方立刻发出 "ai？"。人在手机上光是读完一句就不止 1 秒。
        #
        # 必须放在入站侧而不是发送队列内：队列是全局串行的，
        # 在 action 里 sleep 会让每条消息独占队列十几秒，直接堵死出站。
        read_delay = estimate_read_delay(incoming_text)
        self.ctx.logger.info(f"阅读延迟 {read_delay:.1f} 秒后处理")
        await asyncio.sleep(read_delay)

        await self._maybe_publish_to_channel(session_key, incoming_text, message_dict)

        await self._record_inbound_feedback(session_key, incoming_text)

        if self._transcript is not None:
            chat = await self._safe_get_chat(event)
            await self._transcript.log_inbound(
                chat_id=session_key,
                chat_title=str(getattr(chat, "title", "") or "私聊"),
                is_private=bool(getattr(event, "is_private", False)),
                sender_id=str(sender_id),
                sender_name=str(
                    getattr(sender, "username", None) or getattr(sender, "first_name", None) or sender_id
                ),
                message_id=getattr(event.message, "id", None),
                text=incoming_text,
                is_mention=is_mention,
                has_media=getattr(event.message, "media", None) is not None,
            )

        # 小群参与率约束：不路由给 Host 就不会产生回复。
        #
        # 某休闲小群实测参与率 63.6%（技术群只有 12-13%），别人说 3 句
        # 我们接 2 句。小群人少、消息密，话多会被迅速聚焦——该群
        # 正是第一个有人当面问 "ai？" 的地方。
        self._note_speaker(session_key, str(sender_id))
        self._small_chat.record_inbound(session_key)
        # 技术话题一概不接。
        #
        # 某高风险小群全是资深从业者，讨论的是 MTE 内存标记、
        # GPL 许可证豁免、JLS 握手伪装这种深度内容。技术回答说浅了
        # 露怯、说深了更可疑，闭嘴才是最优解——只在纯闲聊时露面。
        if blocks_tech(session_key) and is_tech_topic(incoming_text, session_key):
            self.ctx.logger.info(
                f"技术话题回避: {session_key} text={incoming_text[:30]!r}"
            )
            return

        # 高风险群用更严格的参与率与间隔覆盖默认值。
        risk_ratio = get_reply_ratio(session_key)
        risk_gap = get_min_gap(session_key)
        suppressed, suppress_reason = self._small_chat.should_suppress(
            session_key,
            member_count=self._recent_speaker_count(session_key),
            is_directed=is_mention,
            ratio_override=risk_ratio,
            min_gap_override=risk_gap,
        )
        if suppressed:
            self.ctx.logger.info(f"小群约束跳过本条: {session_key} {suppress_reason}")
            return

        external_message_id = f"{chat_id}:{getattr(event.message, 'id', '')}"
        # 记录"我方将对这条消息作答"，供编辑追踪判定探测模式：
        # 我方回复过的消息事后被改写，是身份探测的典型手法。
        inbound_message_id = getattr(event.message, "id", None)
        if inbound_message_id is not None:
            self._edit_tracker.note_reply(
                chat_id=str(chat_id),
                message_id=int(inbound_message_id),
            )
        try:
            await self.ctx.gateway.route_message(
                gateway_name=TELEGRAM_USER_GATEWAY_NAME,
                message=message_dict,
                route_metadata=self._build_route_metadata(),
                external_message_id=external_message_id,
                dedupe_key=external_message_id,
            )
        except Exception as exc:  # noqa: BLE001 - 路由失败需要暴露具体消息
            self.ctx.logger.error(f"Telegram 消息路由到 Host 失败: {exc}")

    def _maybe_schedule_reaction(self, event: Any, chat_id: str, text: str) -> None:
        """按策略决定是否给这条消息点表情，并异步执行。

        Args:
            event: Telethon 入站事件。
            chat_id: 原始会话 ID（不含 topic 后缀）。
            text: 消息文本，用于挑选贴合语境的表情。
        """

        policy = self._reaction_policy
        if policy is None:
            return

        message_id = self._safe_int(getattr(event.message, "id", None))
        if message_id is None:
            return
        if not policy.should_react(chat_id, message_id):
            return

        task = asyncio.create_task(
            self._do_send_reaction(event, chat_id, message_id, text),
            name=f"telegram_user_adapter.reaction.{chat_id}.{message_id}",
        )
        # 保留引用避免任务被 GC，完成后自动移除。
        self._reaction_tasks.add(task)
        task.add_done_callback(self._reaction_tasks.discard)

    async def _do_send_reaction(
        self, event: Any, chat_id: str, message_id: int, text: str
    ) -> None:
        """真正执行一次表情回应。

        Args:
            event: Telethon 入站事件。
            chat_id: 原始会话 ID。
            message_id: 目标消息 ID。
            text: 消息文本。
        """

        from telethon import errors

        policy = self._reaction_policy
        tg_client = self._tg_client
        if policy is None or tg_client is None:
            return

        settings = self._load_settings()
        behavior = settings.behavior

        # 先停顿再点：秒点表情是最明显的脚本特征。
        delay = random.uniform(behavior.reaction_min_delay, behavior.reaction_max_delay)
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

        try:
            entity = await self._safe_get_chat(event)
            if entity is None:
                return

            allowed = await self._resolve_chat_allowed_reactions(chat_id, entity)
            if allowed is not None and not allowed:
                # 空集合意味着该会话明确禁用了表情回应。
                policy.mark_chat_disabled(chat_id)
                return

            emoji = policy.pick_emoji(chat_id, text, allowed)
            if emoji is None:
                return

            await tg_client.send_reaction(entity, message_id, emoji)
            policy.mark_reacted(chat_id, message_id)

            if self._transcript is not None:
                await self._transcript.log_event(
                    chat_id=chat_id,
                    event="reaction_sent",
                    detail={"message_id": message_id, "emoji": emoji, "delay": round(delay, 2)},
                )
        except errors.ReactionInvalidError:
            # 该表情在这个会话不被允许：拉黑，不再重试同一个表情。
            self.ctx.logger.debug(f"表情不被允许，已拉黑: chat={chat_id}")
        except errors.ReactionsTooManyError:
            # 这条消息上的表情种类已达上限，跳过即可。
            self.ctx.logger.debug(f"消息表情种类已满: chat={chat_id} msg={message_id}")
        except (
            errors.ChatWriteForbiddenError,
            errors.UserBannedInChannelError,
            errors.ChannelPrivateError,
        ):
            # 没有权限就别再在这个会话点表情了。
            policy.mark_chat_disabled(chat_id)
            self.ctx.logger.info(f"无权在该会话点表情，已停用: chat={chat_id}")
        except (errors.MessageIdInvalidError, errors.MsgIdInvalidError):
            # 消息已被删除，忽略。
            self.ctx.logger.debug(f"目标消息不存在: chat={chat_id} msg={message_id}")
        except errors.FloodWaitError as exc:
            # 触发限流说明动作太频繁，直接停用该会话的表情回应等下次重启。
            policy.mark_chat_disabled(chat_id)
            self.ctx.logger.warning(f"点表情触发限流 {exc.seconds}s，已停用该会话表情: chat={chat_id}")
        except asyncio.CancelledError:
            raise

    async def _resolve_chat_allowed_reactions(
        self, chat_id: str, entity: Any
    ) -> Optional[set[str]]:
        """解析并缓存某会话允许的表情集合。

        每次点表情都查一次 GetFullChannel 太浪费，这里做进程内缓存。

        Args:
            chat_id: 会话 ID。
            entity: 会话实体。

        Returns:
            Optional[set[str]]: 允许的表情集合；``None`` 表示不限制。
        """

        if chat_id in self._allowed_reactions_cache:
            return self._allowed_reactions_cache[chat_id]

        tg_client = self._tg_client
        if tg_client is None:
            return None

        available = await tg_client.get_available_reactions(entity)
        allowed = resolve_allowed_reactions(available)
        self._allowed_reactions_cache[chat_id] = allowed
        return allowed

    async def _on_message_edited(self, event: Any) -> None:
        """处理一条消息编辑事件。

        真人频繁改口（白名单群实测平均 10.9%，某高风险群 27%），而该高风险群
        两次身份质问（"你是大语言模型吗？"、"你是一个猫娘"）都被编辑过，
        属于"发问→看反应→改内容→再看反应"的探测手法。

        **不走 route_message**：编辑不是一条新的待回复消息。真人不会因为对方
        改了个字就再答一遍，那反而是紧盯消息流的机器特征。这里只做两件事：
        更新本地上下文中的原文，以及在命中探测模式时留下告警日志。

        Args:
            event: Telethon ``MessageEdited.Event`` 对象。
        """

        raw_chat_id = getattr(event, "chat_id", None)
        if raw_chat_id is None:
            return
        chat_id = str(raw_chat_id)

        message_id = getattr(event.message, "id", None)
        if message_id is None:
            return

        new_text = str(getattr(event.message, "text", "") or "")
        record = self._edit_tracker.note_edit(
            chat_id=chat_id,
            message_id=int(message_id),
            new_text=new_text,
        )
        if record is None:
            return

        if record.we_replied:
            self.ctx.logger.warning(
                f"我方已回复的消息被编辑: chat={chat_id} mid={message_id} "
                f"新文本={new_text[:60]!r}"
            )
        else:
            self.ctx.logger.info(f"消息被编辑: chat={chat_id} mid={message_id}")

        if self._edit_tracker.is_probe_pattern(chat_id=chat_id):
            self.ctx.logger.warning(
                f"检测到身份探测式编辑: chat={chat_id} —— 对方改写了我方回复过的质问"
            )

    async def _on_reaction_update(self, update: Any) -> None:
        """处理一条表情回应更新。

        只把「别人给我发的消息点了表情」写进上下文，让麦麦知道自己刚才那句话
        收到了什么反馈。**不走 route_message**：表情不是一条待回复的消息，
        走入站路由会触发一次完整 LLM 推理并可能主动接话，真人不会因为别人点了
        个赞就再冒一句。

        Args:
            update: Telethon 原始 MTProto Update 对象。
        """

        settings = self._load_settings()
        if not settings.behavior.receive_reactions:
            return

        info = parse_reaction_update(update)
        if info is None:
            return

        # 只认自己发出去的消息；别人之间互相点表情与我无关。
        remembered = self._sent_messages.get((info.chat_id, info.message_id))
        if remembered is None:
            return

        session_key, sent_text = remembered

        # 自己给自己点的表情不算反馈，否则会把自己的动作当成别人的回应。
        reactor_ids = [rid for rid in info.reactor_ids if rid != self._self_account_id]
        if info.reactor_ids and not reactor_ids:
            return

        visible_text = self._build_reaction_text(info, sent_text, reactor_ids)

        if self._transcript is not None:
            await self._transcript.log_event(
                chat_id=session_key,
                event="reaction_received",
                detail={
                    "message_id": info.message_id,
                    "emojis": info.emojis,
                    "reactor_ids": reactor_ids,
                },
            )

        try:
            await self.ctx.maisaka.context.append(
                stream_id=session_key,
                segments=[{"type": "text", "data": visible_text}],
                visible_text=visible_text,
                source_kind="telegram_reaction",
            )
        except Exception as exc:  # noqa: BLE001 - 上下文注入失败需要暴露具体原因
            self.ctx.logger.error(f"表情回应写入上下文失败: {exc}")

    @staticmethod
    def _build_reaction_text(
        info: ReactionInfo, sent_text: str, reactor_ids: list[str]
    ) -> str:
        """把表情回应渲染成一句上下文可读的中文描述。

        Args:
            info: 表情回应解析结果。
            sent_text: 被点表情的那条自发消息内容。
            reactor_ids: 点表情的用户 ID（已剔除自己）。

        Returns:
            str: 供上下文阅读的描述文本。
        """

        # 消息太长会淹没上下文，这里只保留开头一小段用于定位是哪句话。
        quoted = sent_text.strip().replace("\n", " ")
        if len(quoted) > 30:
            quoted = f"{quoted[:30]}…"

        emojis = " ".join(info.emojis)
        who = f"<{reactor_ids[0]}>" if len(reactor_ids) == 1 else "有人"
        if quoted:
            return f"[{who} 给你刚才说的「{quoted}」点了 {emojis}]"
        return f"[{who} 给你刚才发的消息点了 {emojis}]"

    async def _record_inbound_feedback(self, session_key: str, incoming_text: str) -> None:
        """把入站消息作为上一次发言的效果反馈。

        Args:
            session_key: 会话键。
            incoming_text: 对方消息文本。
        """

        store = self._self_improvement
        if store is None or not store.enabled:
            return

        our_last_text = self._last_outbound_text.get(session_key)
        if not our_last_text:
            return

        suspected = detect_suspicion(incoming_text)

        # 有人接话了，取消"冷场"判定任务。
        pending = self._pending_outcome.pop(session_key, None)
        if pending is not None and not pending.done():
            pending.cancel()

        with contextlib.suppress(Exception):
            await store.record_outcome(
                ChatOutcome(
                    chat_id=session_key,
                    text=our_last_text,
                    got_reply=True,
                    suspected=suspected,
                    suspicion_text=incoming_text if suspected else "",
                )
            )

        # 反馈只消费一次，避免同一条发言被反复计分。
        self._last_outbound_text.pop(session_key, None)

    @staticmethod
    def _resolve_inbound_session_key(message_dict: Dict[str, Any], chat_id: Any) -> str:
        """解析入站消息对应的会话键。

        Args:
            message_dict: 标准消息字典。
            chat_id: Telegram 原始 chat_id。

        Returns:
            str: 会话键（群聊为含 topic 的虚拟 group_id，私聊为对方 ID）。
        """

        message_info = message_dict.get("message_info", {}) or {}
        group_info = message_info.get("group_info") or {}
        if group_info.get("group_id"):
            return str(group_info["group_id"])

        additional = message_info.get("additional_config", {}) or {}
        if additional.get("platform_io_target_user_id"):
            return str(additional["platform_io_target_user_id"])
        return str(chat_id)

    async def _resolve_read_entity(self, event: Any) -> Any:
        """解析用于标记已读的会话实体。

        Args:
            event: Telethon 事件。

        Returns:
            Any: 会话实体；解析失败时回退为 chat_id。
        """

        try:
            return await event.get_chat()
        except Exception:  # noqa: BLE001 - 解析失败回退裸 ID
            return event.chat_id

    async def _safe_get_chat(self, event: Any) -> Any:
        """安全获取会话实体。

        Args:
            event: Telethon 事件。

        Returns:
            Any: 会话实体；失败时返回 ``None``。
        """

        try:
            return await event.get_chat()
        except Exception:  # noqa: BLE001 - 群名解析失败不影响主流程
            return None

    def _build_route_metadata(self) -> Dict[str, Any]:
        """构造注入 Host 时的路由辅助信息。

        Returns:
            Dict[str, Any]: 路由元数据。
        """

        if not self._self_account_id:
            return {}
        return {
            "self_id": self._self_account_id,
            "platform_io_account_id": self._self_account_id,
        }


def create_plugin() -> TelegramUserAdapterPlugin:
    """创建插件实例。

    Returns:
        TelegramUserAdapterPlugin: 插件实例。
    """

    return TelegramUserAdapterPlugin()

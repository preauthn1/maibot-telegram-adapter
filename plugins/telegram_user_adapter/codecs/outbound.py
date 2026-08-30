"""Telegram 真人账号出站消息编解码。

把主程序的出站 MessageDict 转换为 Telethon 发送动作，并在发送前插入
拟人化的已读/正在输入行为。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import asyncio
import base64
import random

from ..humanize import humanize_chat_text
from ..telegram_user_client import TelegramUserClient
from ..utils import estimate_typing_seconds, parse_topic_group_id


class TelegramUserOutboundCodec:
    """将 Host 出站消息转换为 Telethon 调用。"""

    def __init__(self, tg_client: TelegramUserClient, logger: Any) -> None:
        """初始化出站编解码器。

        Args:
            tg_client: 已连接的真人账号客户端。
            logger: 插件日志器。
        """

        self._tg = tg_client
        self._logger = logger
        self._simulate_typing = True
        self._typing_cps = 6.0
        self._min_think_delay = 0.8
        self._max_typing_delay = 12.0
        self._enable_humanize = True
        self._max_emoji = 1
        self._presence: Any = None
        self._last_typing_seconds = 0.0
        self._last_humanize_rules: list[str] = []
        self._last_original_text = ""

    def set_presence_manager(self, presence: Any) -> None:
        """注入在线状态管理器。

        Args:
            presence: :class:`PresenceManager` 实例；``None`` 表示不管理在线状态。
        """

        self._presence = presence

    def set_behavior(
        self,
        *,
        simulate_typing: bool,
        typing_cps: float,
        min_think_delay: float,
        max_typing_delay: float,
        enable_humanize: bool = True,
        max_emoji: int = 1,
    ) -> None:
        """配置拟人化发送行为。

        Args:
            simulate_typing: 是否模拟正在输入。
            typing_cps: 每秒键入字符数。
            min_think_delay: 最小思考停顿。
            max_typing_delay: 最长打字时间。
            enable_humanize: 是否启用中文拟人化改写。
            max_emoji: 单条消息 emoji 上限。
        """

        self._simulate_typing = simulate_typing
        self._typing_cps = typing_cps
        self._min_think_delay = min_think_delay
        self._max_typing_delay = max_typing_delay
        self._enable_humanize = enable_humanize
        self._max_emoji = max_emoji

    @property
    def last_typing_seconds(self) -> float:
        """最近一次发送的模拟打字总时长。

        Returns:
            float: 秒数。
        """

        return self._last_typing_seconds

    @property
    def last_humanize_rules(self) -> list[str]:
        """最近一次发送命中的拟人化规则。

        Returns:
            list[str]: 规则名列表。
        """

        return list(self._last_humanize_rules)

    @property
    def last_original_text(self) -> str:
        """最近一次发送在拟人化处理前的文本。

        Returns:
            str: 原始文本。
        """

        return self._last_original_text

    async def send_outbound_message(self, message: Dict[str, Any], route: Dict[str, Any]) -> Dict[str, Any]:
        """发送一条出站消息。

        Args:
            message: 主程序给出的标准消息字典。
            route: Platform IO 路由信息。

        Returns:
            Dict[str, Any]: 标准化的发送结果。
        """

        del route

        message_info = message.get("message_info", {})
        raw_message = message.get("raw_message", [])
        group_info = message_info.get("group_info")
        user_info = message_info.get("user_info")
        additional_config = message_info.get("additional_config", {}) or {}

        chat_id: Optional[str] = None
        parsed_thread_id: Optional[int] = None

        target_group_id = self._clean_optional_str(additional_config.get("platform_io_target_group_id"))
        target_user_id = self._clean_optional_str(additional_config.get("platform_io_target_user_id"))

        if target_group_id:
            chat_id, parsed_thread_id = parse_topic_group_id(target_group_id)
        elif group_info and group_info.get("group_id"):
            chat_id, parsed_thread_id = parse_topic_group_id(group_info["group_id"])
        elif target_user_id:
            chat_id = target_user_id
        elif user_info and user_info.get("user_id"):
            chat_id = str(user_info["user_id"])

        if not chat_id:
            return {"success": False, "error": "无法确定目标 chat_id"}

        entity = await self._resolve_entity(chat_id)
        if entity is None:
            return {"success": False, "error": f"无法解析目标会话: {chat_id}"}

        reply_to = self._safe_int(additional_config.get("reply_message_id"))
        if reply_to is None:
            reply_to = self._extract_reply_to_from_segments(raw_message)
        if reply_to is None and parsed_thread_id is not None:
            # 话题群必须带上 topic 根消息 ID，否则消息会落到 General。
            reply_to = parsed_thread_id

        payloads = raw_message if isinstance(raw_message, list) else []
        if not payloads:
            return {"success": False, "error": "消息段为空"}

        # 重置本次发送的观测指标。
        self._last_typing_seconds = 0.0
        self._last_humanize_rules = []
        self._last_original_text = ""

        # 只在真正要发言时上线（需求 10）。
        if self._presence is not None:
            await self._presence.go_online()

        last_sent: Any = None
        errors: List[str] = []
        sent_any = False

        try:
            for seg in payloads:
                if self._is_local_only_segment(seg):
                    continue
                current_reply = reply_to if not sent_any else None
                try:
                    sent = await self._send_segment(entity, seg, current_reply)
                except Exception as exc:  # noqa: BLE001 - 单段失败不阻断其他段
                    errors.append(f"{seg.get('type', 'unknown')}: {exc}")
                    continue
                if sent is None:
                    continue
                sent_any = True
                last_sent = sent
        finally:
            # 无论成功与否都安排下线，避免异常路径把账号永久挂在线上。
            if self._presence is not None:
                await self._presence.schedule_offline()

        if not sent_any:
            return {"success": False, "error": "; ".join(errors) or "所有消息段发送失败"}

        external_id = str(getattr(last_sent, "id", "") or "")
        return {"success": True, "external_message_id": external_id or None}

    async def _send_segment(self, entity: Any, seg: Dict[str, Any], reply_to: Optional[int]) -> Any:
        """发送单个消息段。

        Args:
            entity: 目标会话实体。
            seg: 消息段字典。
            reply_to: 要回复的消息 ID。

        Returns:
            Any: Telethon 返回的消息对象；本段无需发送时返回 ``None``。
        """

        seg_type = str(seg.get("type") or "").strip()
        seg_data = seg.get("data", "")
        binary_b64 = seg.get("binary_data_base64", "")

        if seg_type == "text":
            text = seg_data if isinstance(seg_data, str) else str(seg_data)
            if not text.strip():
                return None

            self._last_original_text = text
            if self._enable_humanize:
                humanized = humanize_chat_text(text, max_emoji=self._max_emoji)
                if humanized.became_empty:
                    # 整条都是助手腔，跳过发送。真人不会为了说话而说话。
                    self._logger.info(f"跳过纯助手腔消息，不发送: {text!r}")
                    return None
                if humanized.changed:
                    self._last_humanize_rules.extend(humanized.applied_rules)
                    self._logger.debug(
                        f"拟人化改写: {text!r} -> {humanized.text!r} 规则={humanized.applied_rules}"
                    )
                text = humanized.text

            await self._humanize_before_send(entity, len(text))
            return await self._tg.send_text(entity, text, reply_to=reply_to)

        if seg_type == "image":
            if binary_b64:
                await self._humanize_before_send(entity, 0)
                return await self._tg.send_file(
                    entity,
                    base64.b64decode(binary_b64),
                    file_name="image.png",
                    reply_to=reply_to,
                )
            if isinstance(seg_data, str) and seg_data.startswith("http"):
                await self._humanize_before_send(entity, 0)
                return await self._tg.send_text(entity, seg_data, reply_to=reply_to)
            return None

        if seg_type in ("emoji", "sticker"):
            if not binary_b64:
                return None
            await self._humanize_before_send(entity, 0)
            return await self._tg.send_file(
                entity,
                base64.b64decode(binary_b64),
                file_name="sticker.webp",
                reply_to=reply_to,
            )

        if seg_type == "voice":
            if not binary_b64:
                return None
            await self._humanize_before_send(entity, 0)
            return await self._tg.send_file(
                entity,
                base64.b64decode(binary_b64),
                file_name="voice.ogg",
                reply_to=reply_to,
                voice_note=True,
            )

        if self._is_local_only_segment(seg):
            return None

        if seg_type:
            self._logger.debug(f"跳过不支持的发送类型: {seg_type}")
        return None

    async def _humanize_before_send(self, entity: Any, text_length: int) -> None:
        """在发送前插入拟人化停顿与输入状态。

        Args:
            entity: 目标会话实体。
            text_length: 待发送文本长度；非文本传 0。
        """

        delay = estimate_typing_seconds(
            text_length,
            self._typing_cps,
            self._min_think_delay,
            self._max_typing_delay,
        )
        # 加入 ±20% 抖动，避免固定节奏被识别为脚本。
        delay *= random.uniform(0.8, 1.2)
        self._last_typing_seconds += delay

        if self._simulate_typing:
            await self._tg.simulate_typing(entity, delay)
        else:
            await asyncio.sleep(delay)

    async def _resolve_entity(self, chat_id: str) -> Any:
        """解析目标会话实体。

        Args:
            chat_id: 目标 chat_id 字符串。

        Returns:
            Any: Telethon 实体；解析失败时返回 ``None``。
        """

        try:
            numeric_id = int(chat_id)
        except (TypeError, ValueError):
            numeric_id = None

        try:
            return await self._tg.get_entity(numeric_id if numeric_id is not None else chat_id)
        except Exception as exc:  # noqa: BLE001 - 解析失败回退到裸 ID
            self._logger.debug(f"get_entity({chat_id}) 失败，回退裸 ID: {exc}")
            return numeric_id if numeric_id is not None else chat_id

    @staticmethod
    def _is_local_only_segment(seg: Dict[str, Any]) -> bool:
        """判断消息段是否只参与本地语义。

        Args:
            seg: 消息段字典。

        Returns:
            bool: 属于本地语义段时返回 ``True``。
        """

        seg_type = str(seg.get("type") or "").strip()
        return seg_type in {"reply", "at", "forward", "dict"}

    def _extract_reply_to_from_segments(self, raw_message: Any) -> Optional[int]:
        """从消息段中提取回复目标。

        Args:
            raw_message: 出站消息段列表。

        Returns:
            Optional[int]: 回复目标消息 ID。
        """

        if not isinstance(raw_message, list):
            return None
        for seg in raw_message:
            if not isinstance(seg, dict) or seg.get("type") != "reply":
                continue
            data = seg.get("data")
            if isinstance(data, dict):
                return self._safe_int(data.get("target_message_id"))
            return self._safe_int(data)
        return None

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        """安全地把任意值转换为整数。

        Args:
            value: 原始值。

        Returns:
            Optional[int]: 转换结果；失败时返回 ``None``。
        """

        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clean_optional_str(value: Any) -> Optional[str]:
        """把值规范化为去空白字符串。

        Args:
            value: 原始值。

        Returns:
            Optional[str]: 非空字符串；否则返回 ``None``。
        """

        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

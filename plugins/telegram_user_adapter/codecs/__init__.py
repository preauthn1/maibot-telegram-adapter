"""Telegram 真人账号入站消息编解码。

把 Telethon 的 ``NewMessage.Event`` 转换为主程序可消费的标准 MessageDict。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import base64
import hashlib
import re
import time

from ..constants import PLATFORM_NAME
from ..telegram_user_client import TelegramUserClient
from ..utils import build_topic_group_id, pick_username


class TelegramUserInboundCodec:
    """将 Telethon 消息转换为 Host 侧标准 MessageDict。"""

    def __init__(self, tg_client: TelegramUserClient, logger: Any) -> None:
        """初始化入站编解码器。

        Args:
            tg_client: 已连接的真人账号客户端。
            logger: 插件日志器。
        """

        self._tg = tg_client
        self._logger = logger
        self._self_id: Optional[int] = None
        self._self_username: Optional[str] = None
        self._download_media: bool = True
        self._max_media_bytes: int = 8 * 1024 * 1024

    def set_self(self, self_id: int, username: Optional[str]) -> None:
        """记录当前登录账号的身份。

        Args:
            self_id: 账号数字 ID。
            username: 账号 @用户名。
        """

        self._self_id = self_id
        self._self_username = username

    def set_media_policy(self, *, download_media: bool, max_media_bytes: int) -> None:
        """配置媒体下载策略。

        Args:
            download_media: 是否下载媒体。
            max_media_bytes: 单个媒体大小上限（字节）。
        """

        self._download_media = download_media
        self._max_media_bytes = max_media_bytes

    async def build_message_dict(self, event: Any) -> Optional[Dict[str, Any]]:
        """把 Telethon 事件转换为标准 MessageDict。

        Args:
            event: Telethon ``NewMessage.Event``。

        Returns:
            Optional[Dict[str, Any]]: 标准消息字典；无可用内容时返回 ``None``。
        """

        message = event.message
        chat_id = event.chat_id
        sender_id = self._resolve_sender_id(event)
        if chat_id is None or sender_id is None:
            return None

        sender = await self._safe_get_sender(event)
        user_nickname = pick_username(
            getattr(sender, "first_name", None),
            getattr(sender, "last_name", None),
            getattr(sender, "username", None),
        )

        segments, additional_config, is_at = await self._extract_segments(event, message)
        if not segments:
            return None

        message_info: Dict[str, Any] = {
            "user_info": {
                "platform": PLATFORM_NAME,
                "user_id": str(sender_id),
                "user_nickname": user_nickname,
                "user_cardname": None,
            },
            "additional_config": additional_config,
        }

        if event.is_private:
            additional_config["platform_io_target_user_id"] = str(chat_id)
        else:
            thread_id = self._resolve_topic_thread_id(message)
            virtual_group_id = build_topic_group_id(chat_id, thread_id)
            additional_config["platform_io_target_group_id"] = virtual_group_id
            chat = await self._safe_get_chat(event)
            group_name = getattr(chat, "title", None) or f"group_{chat_id}"
            message_info["group_info"] = {
                "group_id": virtual_group_id,
                "group_name": group_name,
            }

        plain_text = "".join(seg.get("data", "") for seg in segments if seg.get("type") == "text")
        has_image = any(seg.get("type") == "image" for seg in segments)
        has_emoji = any(seg.get("type") in ("emoji", "sticker") for seg in segments)

        message_id = str(getattr(message, "id", None) or f"tg-{int(time.time() * 1000)}")

        return {
            "message_id": message_id,
            "timestamp": str(self._resolve_timestamp(message)),
            "platform": PLATFORM_NAME,
            "message_info": message_info,
            "raw_message": segments,
            "is_mentioned": is_at,
            "is_at": is_at,
            "is_emoji": has_emoji,
            "is_picture": has_image,
            "is_command": plain_text.startswith("/"),
            "is_notify": False,
            "processed_plain_text": plain_text,
        }

    async def _extract_segments(
        self, event: Any, message: Any
    ) -> Tuple[Optional[List[Dict[str, Any]]], Dict[str, Any], bool]:
        """提取消息段列表与附加配置。

        Args:
            event: Telethon 事件。
            message: Telethon 消息对象。

        Returns:
            Tuple: ``(segments, additional_config, is_at)``。
        """

        segments: List[Dict[str, Any]] = []
        additional: Dict[str, Any] = {}
        is_at = False

        thread_id = self._resolve_topic_thread_id(message)
        if thread_id is not None:
            additional["message_thread_id"] = thread_id

        reply_to_msg_id = self._resolve_real_reply_id(message)
        replied_message = None
        if reply_to_msg_id:
            additional["reply_message_id"] = reply_to_msg_id
            replied_message = await self._safe_get_reply_message(event)
            reply_sender = getattr(replied_message, "sender", None)
            reply_name = pick_username(
                getattr(reply_sender, "first_name", None),
                getattr(reply_sender, "last_name", None),
                getattr(reply_sender, "username", None),
            )
            reply_uid = getattr(replied_message, "sender_id", None)
            segments.append({"type": "text", "data": f"[回复<{reply_name}:{reply_uid}>："})
            reply_text = getattr(replied_message, "message", "") or ""
            if reply_text:
                segments.append({"type": "text", "data": reply_text})
            segments.append({"type": "text", "data": "]，说："})

        text = getattr(message, "message", "") or ""
        if text:
            segments.append({"type": "text", "data": text})

        media_segment = await self._build_media_segment(message)
        if media_segment is not None:
            segments.append(media_segment)

        if self._is_mentioning_self(message, replied_message):
            self_id = str(self._self_id) if self._self_id is not None else ""
            segments = self._strip_leading_self_mention_text(segments)
            segments.insert(0, {"type": "at", "data": {"target_user_id": self_id}})
            additional["at_bot"] = True
            is_at = True

        return segments or None, additional, is_at

    async def _build_media_segment(self, message: Any) -> Optional[Dict[str, Any]]:
        """根据消息媒体类型构造消息段。

        Args:
            message: Telethon 消息对象。

        Returns:
            Optional[Dict[str, Any]]: 媒体消息段；没有媒体时返回 ``None``。
        """

        if getattr(message, "media", None) is None:
            return None

        # 贴纸一概不读：贴纸的"语义"高度依赖图案本身，模型只能拿到
        # 一个占位符，据此回复往往驴唇不对马嘴，反而暴露自己看不懂。
        # 真人看不懂梗图时也常常直接不接话。
        if getattr(message, "sticker", None) is not None:
            return None
        if getattr(message, "photo", None) is not None:
            return await self._build_downloaded_segment(message, "image", "[图片]")
        if getattr(message, "gif", None) is not None:
            return await self._build_downloaded_segment(message, "emoji", "[动图]")
        if getattr(message, "voice", None) is not None:
            return await self._build_downloaded_segment(message, "voice", "[语音]")
        if getattr(message, "video", None) is not None:
            return {"type": "text", "data": "[视频]"}
        if getattr(message, "document", None) is not None:
            file_name = getattr(getattr(message, "file", None), "name", None) or "文件"
            return {"type": "text", "data": f"[文件:{file_name}]"}
        return {"type": "text", "data": "[媒体]"}

    async def _build_downloaded_segment(
        self, message: Any, seg_type: str, fallback_text: str
    ) -> Dict[str, Any]:
        """下载媒体并构造二进制消息段。

        Args:
            message: Telethon 消息对象。
            seg_type: 消息段类型。
            fallback_text: 下载失败时的文本占位。

        Returns:
            Dict[str, Any]: 消息段字典。
        """

        if not self._download_media:
            return {"type": "text", "data": fallback_text}

        raw_bytes = await self._tg.download_media_bytes(message, self._max_media_bytes)
        if not raw_bytes:
            return {"type": "text", "data": fallback_text}

        return {
            "type": seg_type,
            "data": "",
            "hash": hashlib.sha256(raw_bytes).hexdigest(),
            "binary_data_base64": base64.b64encode(raw_bytes).decode("utf-8"),
        }

    def _strip_leading_self_mention_text(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """移除文本开头重复的 @自身用户名。

        Args:
            segments: 原始消息段列表。

        Returns:
            List[Dict[str, Any]]: 处理后的消息段列表。
        """

        if not segments or not self._self_username:
            return segments
        first = segments[0]
        if first.get("type") != "text" or not isinstance(first.get("data"), str):
            return segments

        pattern = re.compile(rf"^\s*@{re.escape(self._self_username)}\b\s*", re.IGNORECASE)
        stripped_text = pattern.sub("", first["data"], count=1)
        if stripped_text == first["data"]:
            return segments
        if stripped_text:
            return [{**first, "data": stripped_text}, *segments[1:]]
        return segments[1:]

    def _is_mentioning_self(self, message: Any, replied_message: Any) -> bool:
        """判断消息是否 @了本账号或回复了本账号。

        Args:
            message: Telethon 消息对象。
            replied_message: 被回复的消息对象；可为 ``None``。

        Returns:
            bool: 命中提及时返回 ``True``。
        """

        if self._self_id is None:
            return False

        if replied_message is not None and getattr(replied_message, "sender_id", None) == self._self_id:
            return True

        # Telethon 会在群聊中直接给出 mentioned 标记
        if bool(getattr(message, "mentioned", False)):
            return True

        text = getattr(message, "message", "") or ""
        if self._self_username and text:
            pattern = re.compile(rf"@{re.escape(self._self_username)}\b", re.IGNORECASE)
            if pattern.search(text):
                return True

        for entity in getattr(message, "entities", None) or []:
            if getattr(entity, "user_id", None) == self._self_id:
                return True

        return False

    @staticmethod
    def _resolve_real_reply_id(message: Any) -> Optional[int]:
        """解析真正的“回复目标”消息 ID。

        话题群（forum）中，普通消息的 ``reply_to_msg_id`` 会被 Telegram 填成
        话题根消息 ID，此时并不是用户主动回复。只有 ``reply_to_top_id`` 存在时，
        ``reply_to_msg_id`` 才代表用户真正回复的那条消息。

        Args:
            message: Telethon 消息对象。

        Returns:
            Optional[int]: 真实回复目标；非回复消息返回 ``None``。
        """

        reply_to = getattr(message, "reply_to", None)
        if reply_to is None:
            return None

        reply_to_msg_id = getattr(reply_to, "reply_to_msg_id", None)
        if reply_to_msg_id is None:
            return None

        if bool(getattr(reply_to, "forum_topic", False)):
            # 话题内的普通消息：reply_to_msg_id 只是话题根，不是真实回复。
            if getattr(reply_to, "reply_to_top_id", None) is None:
                return None

        return int(reply_to_msg_id)

    @staticmethod
    def _resolve_topic_thread_id(message: Any) -> Optional[int]:
        """解析话题群的 topic 线程 ID。

        Args:
            message: Telethon 消息对象。

        Returns:
            Optional[int]: topic 线程 ID；非话题消息返回 ``None``。
        """

        reply_to = getattr(message, "reply_to", None)
        if reply_to is None:
            return None
        if not bool(getattr(reply_to, "forum_topic", False)):
            return None
        top_id = getattr(reply_to, "reply_to_top_id", None)
        if top_id is not None:
            return int(top_id)
        msg_id = getattr(reply_to, "reply_to_msg_id", None)
        return int(msg_id) if msg_id is not None else None

    @staticmethod
    def _resolve_sender_id(event: Any) -> Optional[int]:
        """解析发送者 ID。

        Args:
            event: Telethon 事件。

        Returns:
            Optional[int]: 发送者数字 ID。
        """

        sender_id = getattr(event, "sender_id", None)
        if sender_id is not None:
            return int(sender_id)
        message_sender_id = getattr(event.message, "sender_id", None)
        return int(message_sender_id) if message_sender_id is not None else None

    @staticmethod
    def _resolve_timestamp(message: Any) -> float:
        """解析消息时间戳。

        Args:
            message: Telethon 消息对象。

        Returns:
            float: Unix 时间戳。
        """

        date = getattr(message, "date", None)
        if date is None:
            return time.time()
        try:
            return date.timestamp()
        except (AttributeError, ValueError, OSError):
            return time.time()

    async def _safe_get_sender(self, event: Any) -> Any:
        """安全获取发送者实体。

        Args:
            event: Telethon 事件。

        Returns:
            Any: 发送者实体；失败时返回 ``None``。
        """

        try:
            return await event.get_sender()
        except Exception as exc:  # noqa: BLE001 - 实体解析失败仅降级为占位名
            self._logger.debug(f"解析发送者失败: {exc}")
            return None

    async def _safe_get_chat(self, event: Any) -> Any:
        """安全获取会话实体。

        Args:
            event: Telethon 事件。

        Returns:
            Any: 会话实体；失败时返回 ``None``。
        """

        try:
            return await event.get_chat()
        except Exception as exc:  # noqa: BLE001 - 群名解析失败仅降级为占位名
            self._logger.debug(f"解析会话失败: {exc}")
            return None

    async def _safe_get_reply_message(self, event: Any) -> Any:
        """安全获取被回复的消息。

        Args:
            event: Telethon 事件。

        Returns:
            Any: 被回复消息；失败时返回 ``None``。
        """

        try:
            return await event.get_reply_message()
        except Exception as exc:  # noqa: BLE001 - 回复内容缺失不影响主流程
            self._logger.debug(f"解析被回复消息失败: {exc}")
            return None

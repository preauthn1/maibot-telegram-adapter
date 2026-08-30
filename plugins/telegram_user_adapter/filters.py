"""Telegram 真人账号聊天过滤器。"""

from __future__ import annotations

from typing import Any, List, Optional

from .config import TelegramUserChatConfig
from .utils import chat_id_aliases


class TelegramUserChatFilter:
    """根据配置过滤入站消息。"""

    def __init__(self, logger: Any) -> None:
        """初始化过滤器。

        Args:
            logger: 插件日志器。
        """

        self._logger = logger

    def check_allow(
        self,
        chat_config: TelegramUserChatConfig,
        *,
        user_id: str,
        chat_id: Optional[str],
        is_private: bool,
        is_channel: bool,
        sender_is_bot: bool,
    ) -> bool:
        """检查消息是否通过名单过滤。

        Args:
            chat_config: 聊天名单配置。
            user_id: 发送者 ID。
            chat_id: 会话 ID。
            is_private: 是否为私聊。
            is_channel: 是否为频道广播。
            sender_is_bot: 发送者是否为机器人。

        Returns:
            bool: 通过过滤时返回 ``True``。
        """

        if chat_config.ignore_channels and is_channel:
            self._logger.debug(f"频道消息被忽略: chat_id={chat_id}")
            return False

        if chat_config.ignore_bots and sender_is_bot:
            self._logger.debug(f"机器人消息被忽略: user_id={user_id}")
            return False

        if user_id in chat_config.ban_user_id:
            self._logger.debug(f"用户在全局黑名单中，消息被丢弃: user_id={user_id}")
            return False

        if is_private:
            if chat_config.private_list_type == "whitelist" and user_id not in chat_config.private_list:
                self._logger.debug(
                    f"私聊不在白名单中，消息被丢弃: user_id={user_id}, private_list={chat_config.private_list}"
                )
                return False
            if chat_config.private_list_type == "blacklist" and user_id in chat_config.private_list:
                self._logger.debug(
                    f"私聊在黑名单中，消息被丢弃: user_id={user_id}, private_list={chat_config.private_list}"
                )
                return False
            return True

        if not chat_id:
            return True

        # 需求：对所有群组都执行聊天行为。
        # 空白名单表示"不限制"，而不是"全部拒绝"——否则默认配置下一个群都不会聊。
        # 想只聊特定群时，把群号填进 group_list 即可。
        if (
            chat_config.group_list_type == "whitelist"
            and chat_config.group_list
            and not self._id_matches(chat_id, chat_config.group_list)
        ):
            self._logger.debug(
                f"群聊不在白名单中，消息被丢弃: chat_id={chat_id}, group_list={chat_config.group_list}"
            )
            return False
        if chat_config.group_list_type == "blacklist" and self._id_matches(chat_id, chat_config.group_list):
            self._logger.debug(
                f"群聊在黑名单中，消息被丢弃: chat_id={chat_id}, group_list={chat_config.group_list}"
            )
            return False
        return True

    @staticmethod
    def _id_matches(chat_id: str, configured_ids: List[str]) -> bool:
        """判断 chat_id 是否命中配置名单。

        Args:
            chat_id: 待匹配的 chat_id。
            configured_ids: 配置中的 ID 列表。

        Returns:
            bool: 命中任一等价写法时返回 ``True``。
        """

        aliases = chat_id_aliases(chat_id)
        return any(chat_id_aliases(configured_id) & aliases for configured_id in configured_ids)

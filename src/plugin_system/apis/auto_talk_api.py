from src.common.logger import get_logger
from src.chat.heart_flow.heartFC_chat import HeartFChatting
from src.chat.heart_flow.heartflow import heartflow

logger = get_logger("auto_talk_api")


def set_question_probability_multiplier(chat_id: str, multiplier: float) -> bool:
    """
    设置指定 chat_id 的主动发言概率乘数。

    返回:
        bool: 设置是否成功。仅当目标聊天为群聊(HeartFChatting)且存在时为 True。
    """
    try:
        if not isinstance(chat_id, str):
            raise TypeError("chat_id 必须是 str")
        if not isinstance(multiplier, (int, float)):
            raise TypeError("multiplier 必须是数值类型")

        chat = heartflow.heartflow_chat_list.get(chat_id)
        if chat is None:
            logger.warning(f"未找到 chat_id={chat_id} 的心流实例，无法设置乘数")
            return False

        if not isinstance(chat, HeartFChatting):
            logger.warning(f"chat_id={chat_id} 非群聊(HeartFChatting)，不支持设置主动发言乘数")
            return False

        # 约束：不允许负值
        value = float(multiplier)
        if value < 0:
            value = 0.0

        chat.question_probability_multiplier = value
        logger.info(f"[auto_talk_api] chat_id={chat_id} 主动发言乘数已设为 {value}")
        return True
    except Exception as e:
        logger.error(f"设置主动发言乘数失败: {e}")
        return False


def get_question_probability_multiplier(chat_id: str) -> float:
    """获取指定 chat_id 的主动发言概率乘数，未找到则返回 0。"""
    try:
        chat = heartflow.heartflow_chat_list.get(chat_id)
        if isinstance(chat, HeartFChatting):
            return float(getattr(chat, "question_probability_multiplier", 0.0))
        return 0.0
    except Exception:
        return 0.0

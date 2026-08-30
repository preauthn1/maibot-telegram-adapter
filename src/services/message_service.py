"""消息服务模块。"""

import re
from datetime import datetime
from typing import List, Optional, Tuple

from sqlmodel import col, select

from src.chat.message_receive.message import SessionMessage
from src.common.data_models.tool_record_data_model import MaiToolRecord
from src.common.database.database import get_db_session
from src.common.database.database_model import Images, ImageType, ToolRecord
from src.common.message_repository import count_messages, find_messages
from src.common.utils.math_utils import translate_timestamp_to_human_readable
from src.common.utils.utils_action import ActionUtils
from src.config.config import global_config
from src.services.context_merge import merge_consecutive_messages


def _build_readable_line(
    message: SessionMessage,
    *,
    replace_bot_name: bool,
    timestamp_mode: Optional[str],
    show_message_id_prefix: bool,
) -> str:
    plain_text = (message.processed_plain_text or "").strip()
    if replace_bot_name and global_config.bot.nickname:
        plain_text = plain_text.replace(global_config.bot.nickname, "你")
    user_name = (
        message.message_info.user_info.user_cardname
        or message.message_info.user_info.user_nickname
        or message.message_info.user_info.user_id
    )
    prefix: List[str] = []
    if timestamp_mode:
        prefix.append(f"[{translate_timestamp_to_human_readable(message.timestamp.timestamp(), mode=timestamp_mode)}]")
    if show_message_id_prefix:
        prefix.append(f"[消息ID: {message.message_id}]")
    prefix.append(f"{user_name}说：")
    return " ".join(prefix) + plain_text


# 机器人消息的正文特征。入群验证、封禁通知这类消息对对话毫无价值，
# 反而会把"点击下方按钮完成验证"这种指令性文本喂给模型。
_BOT_TEXT_PATTERNS: Tuple[str, ...] = (
    r"点击.{0,6}(?:按钮|下方|这里).{0,6}(?:验证|解封)",
    r"入群验证",
    r"验证(?:成功|失败|超时|通过)",
    r"请在\s*\d+\s*(?:秒|分钟)内完成",
    r"您已被(?:禁言|封禁|移出)",
    r"已被管理员(?:禁言|封禁|移除)",
    r"欢迎.{0,12}加入本群",
    r"新成员.{0,8}(?:加入|入群)",
    r"^/\w+@\w+bot",
    r"广告.{0,4}(?:已删除|已拦截)",
    r"该消息(?:已被删除|含违规内容)",
)

_BOT_TEXT_RE = re.compile("|".join(_BOT_TEXT_PATTERNS), re.IGNORECASE)

# 昵称尾部的装饰字符（emoji、符号、空白）。判断"是不是以 bot 结尾"前先剥掉，
# 否则 "自助解封机器人🚑" 这类昵称会漏判。
_TRAILING_DECORATION_RE = re.compile(r"[^\w\u4e00-\u9fff]+$")


def _is_bot_message(message: SessionMessage) -> bool:
    """判断消息是否来自机器人或属于系统通知。

    需求：上下文中不能包含机器人的消息（入群验证等）。

    判断依据有两层：
    1. 发送者本身被标记为 bot（适配器上报的权威信息，优先采信）；
    2. 正文命中系统通知特征（兜底：部分适配器不上报 bot 标记）。

    Args:
        message: 待判断消息。

    Returns:
        bool: 判定为机器人消息时返回 ``True``。
    """

    info = getattr(message, "message_info", None)
    user_info = getattr(info, "user_info", None) if info is not None else None
    if user_info is not None and getattr(user_info, "is_bot", False):
        return True

    # 机器人昵称特征。Telegram 的 bot username 必须以 bot 结尾，
    # 但**显示名**不受此约束（实测该群里有 "nmBot"、"自助解封机器人🚑"），
    # 因此剥掉尾部的 emoji / 符号后再判断结尾。
    #
    # 用"结尾"而不是"包含"：昵称叫"机器人爱好者""botanist"的是真人，
    # 误删真人消息会让上下文出现空洞，比漏掉个别机器人更糟。
    nickname = (getattr(user_info, "user_nickname", None) or "") if user_info is not None else ""
    trimmed = _TRAILING_DECORATION_RE.sub("", nickname).strip().lower()
    if trimmed.endswith(("bot", "robot", "机器人")):
        return True

    text = (getattr(message, "processed_plain_text", "") or "").strip()
    if not text:
        return False

    return bool(_BOT_TEXT_RE.search(text))


def _normalize_messages(messages: List[SessionMessage]) -> List[SessionMessage]:
    """整理上下文消息：剔除机器人消息，合并被打断的连续发言。

    高频群里（实测 5 万人群 3.7 条/分钟）同一个人连发的几条会被别人
    插在中间拆散，模型会把每条当成对不同人的回应，理解必然错乱。
    详见 ``src.services.context_merge``。

    Args:
        messages: 原始消息列表。

    Returns:
        List[SessionMessage]: 整理后的消息列表。
    """

    if not messages:
        return []

    filtered = [message for message in messages if not _is_bot_message(message)]
    return merge_consecutive_messages(filtered)


def get_messages_by_time(
    start_time: float, end_time: float, limit: int = 0, limit_mode: str = "latest", filter_mai: bool = False
) -> List[SessionMessage]:
    if not isinstance(start_time, (int, float)) or not isinstance(end_time, (int, float)):
        raise ValueError("start_time 和 end_time 必须是数字类型")
    if limit < 0:
        raise ValueError("limit 不能为负数")
    messages = find_messages(
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        limit_mode=limit_mode,
        filter_bot=filter_mai,
    )
    return _normalize_messages(messages)


def get_messages_by_time_in_chat(
    chat_id: str,
    start_time: float,
    end_time: float,
    limit: int = 0,
    limit_mode: str = "latest",
    filter_mai: bool = False,
    filter_command: bool = False,
    filter_intercept_message_level: Optional[int] = None,
) -> List[SessionMessage]:
    if not isinstance(start_time, (int, float)) or not isinstance(end_time, (int, float)):
        raise ValueError("start_time 和 end_time 必须是数字类型")
    if limit < 0:
        raise ValueError("limit 不能为负数")
    if not chat_id:
        raise ValueError("chat_id 不能为空")
    if not isinstance(chat_id, str):
        raise ValueError("chat_id 必须是字符串类型")
    messages = find_messages(
        session_id=chat_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        limit_mode=limit_mode,
        filter_bot=filter_mai,
        filter_command=filter_command,
        filter_intercept_message_level=filter_intercept_message_level,
    )
    return _normalize_messages(messages)


def get_message_by_id(message_id: str, chat_id: Optional[str] = None) -> Optional[SessionMessage]:
    """按消息 ID 查询单条消息，可选限定会话。"""

    normalized_message_id = str(message_id or "").strip()
    if not normalized_message_id:
        raise ValueError("message_id 不能为空")

    normalized_chat_id = str(chat_id or "").strip()
    messages = find_messages(
        session_id=normalized_chat_id or None,
        message_id=normalized_message_id,
        limit=1,
        limit_mode="latest",
    )
    normalized_messages = _normalize_messages(messages)
    return normalized_messages[0] if normalized_messages else None


def get_messages_before_time(timestamp: float, limit: int = 0, filter_mai: bool = False) -> List[SessionMessage]:
    if not isinstance(timestamp, (int, float)):
        raise ValueError("timestamp 必须是数字类型")
    if limit < 0:
        raise ValueError("limit 不能为负数")
    messages = find_messages(
        before_time=timestamp,
        limit=limit,
        limit_mode="latest",
        filter_bot=filter_mai,
    )
    return _normalize_messages(messages)


def get_messages_before_time_in_chat(
    chat_id: str,
    timestamp: float,
    limit: int = 0,
    filter_mai: bool = False,
    filter_intercept_message_level: Optional[int] = None,
) -> List[SessionMessage]:
    if not isinstance(timestamp, (int, float)):
        raise ValueError("timestamp 必须是数字类型")
    if limit < 0:
        raise ValueError("limit 不能为负数")
    if not chat_id:
        raise ValueError("chat_id 不能为空")
    if not isinstance(chat_id, str):
        raise ValueError("chat_id 必须是字符串类型")
    messages = find_messages(
        session_id=chat_id,
        before_time=timestamp,
        limit=limit,
        limit_mode="latest",
        filter_bot=filter_mai,
        filter_intercept_message_level=filter_intercept_message_level,
    )
    return _normalize_messages(messages)


# =============================================================================
# 消息计数函数
# =============================================================================


def count_new_messages(chat_id: str, start_time: float = 0.0, end_time: Optional[float] = None) -> int:
    if not isinstance(start_time, (int, float)):
        raise ValueError("start_time 必须是数字类型")
    if not chat_id:
        raise ValueError("chat_id 不能为空")
    if not isinstance(chat_id, str):
        raise ValueError("chat_id 必须是字符串类型")
    return count_messages(session_id=chat_id, after_time=start_time, end_time=end_time)


# =============================================================================
# 消息格式化函数
# =============================================================================


def build_readable_messages(
    messages: List[SessionMessage],
    replace_bot_name: bool = True,
    timestamp_mode: str = "relative",
    read_mark: float = 0.0,
    truncate: bool = False,
    show_actions: bool = False,
) -> str:
    normalized_messages = _normalize_messages(messages)
    lines: List[str] = []
    unread_mark_added = False
    for message in normalized_messages:
        if read_mark and not unread_mark_added and message.timestamp.timestamp() > read_mark:
            lines.append("--- 以上消息是你已经看过，请关注以下未读的新消息 ---")
            unread_mark_added = True
        line = _build_readable_line(
            message,
            replace_bot_name=replace_bot_name,
            timestamp_mode=timestamp_mode,
            show_message_id_prefix=False,
        )
        if truncate and len(line) > 200:
            line = f"{line[:200]}......（内容太长了）"
        lines.append(line)
    if show_actions and normalized_messages:
        if action_lines := ActionUtils.build_readable_action_records(
            get_actions_by_timestamp_with_chat(
                normalized_messages[0].session_id,
                normalized_messages[0].timestamp.timestamp(),
                normalized_messages[-1].timestamp.timestamp(),
            ),
            "relative",
        ):
            lines.append(action_lines)
    return "\n".join(lines)


def build_readable_messages_with_id(
    messages: List[SessionMessage],
    replace_bot_name: bool = True,
    timestamp_mode: str = "relative",
    read_mark: float = 0.0,
    truncate: bool = False,
    show_actions: bool = False,
) -> Tuple[str, List[Tuple[str, SessionMessage]]]:
    normalized_messages = _normalize_messages(messages)
    lines: List[str] = []
    message_id_list: List[Tuple[str, SessionMessage]] = []
    unread_mark_added = False
    for message in normalized_messages:
        if read_mark and not unread_mark_added and message.timestamp.timestamp() > read_mark:
            lines.append("--- 以上消息是你已经看过，请关注以下未读的新消息 ---")
            unread_mark_added = True
        line = _build_readable_line(
            message,
            replace_bot_name=replace_bot_name,
            timestamp_mode=timestamp_mode,
            show_message_id_prefix=True,
        )
        if truncate and len(line) > 200:
            line = f"{line[:200]}......（内容太长了）"
        lines.append(line)
        message_id_list.append((message.message_id, message))
    if show_actions and normalized_messages:
        if action_lines := ActionUtils.build_readable_action_records(
            get_actions_by_timestamp_with_chat(
                normalized_messages[0].session_id,
                normalized_messages[0].timestamp.timestamp(),
                normalized_messages[-1].timestamp.timestamp(),
            ),
            "relative",
        ):
            lines.append(action_lines)
    return "\n".join(lines), message_id_list


def get_actions_by_timestamp_with_chat(
    chat_id: str,
    timestamp_start: float,
    timestamp_end: float,
    limit: Optional[int] = None,
) -> List[MaiToolRecord]:
    with get_db_session() as session:
        statement = (
            select(ToolRecord)
            .where(col(ToolRecord.session_id) == chat_id)
            .where(col(ToolRecord.timestamp) >= datetime.fromtimestamp(timestamp_start))
            .where(col(ToolRecord.timestamp) <= datetime.fromtimestamp(timestamp_end))
            .order_by(col(ToolRecord.timestamp))
        )
        if limit is not None:
            statement = statement.limit(limit)
        return [MaiToolRecord.from_db_instance(item) for item in session.exec(statement).all()]


def replace_user_references(text: str, platform: str, replace_bot_name: bool = False) -> str:
    del platform
    if not text:
        return text

    def _replace(match: re.Match[str]) -> str:
        prefix = match.group(1) or ""
        user_name = match.group(2)
        if replace_bot_name and user_name == global_config.bot.nickname:
            user_name = "你"
        return f"{prefix}{user_name}"

    text = re.sub(r"(回复|@)?<([^:<>]+):[^<>]+>", _replace, text)
    return text


def translate_pid_to_description(pid: str) -> str:
    with get_db_session() as session:
        statement = (
            select(Images).where((col(Images.id) == int(pid)) & (col(Images.image_type) == ImageType.IMAGE))
            if pid.isdigit()
            else None
        )
        image = session.exec(statement).first() if statement is not None else None
    return image.description.strip() if image and image.description and image.description.strip() else "[图片]"

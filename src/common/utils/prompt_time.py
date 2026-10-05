"""提示词时间的统一时区换算。

服务器运行在 UTC，而 bot 面向的聊天场景使用北京时间（UTC+8）。
凡是写进模型提示词的时间（当前时间、消息时间、跨日提示、回想时间段）
都必须经过这里换算，不能直接对 datetime 调用 strftime：
裸 datetime.now()/datetime.fromtimestamp() 得到的是系统本地时间，
一旦各处混用，模型会看到“当前时间”与“消息时间”相差 8 小时、甚至不在同一天，
从而把正常的当日信息误判为“未来/可疑”。
"""

from datetime import datetime, timedelta, timezone

PROMPT_TZ = timezone(timedelta(hours=8))
"""提示词统一使用的时区：UTC+8。"""

PROMPT_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def to_prompt_tz(value: datetime) -> datetime:
    """把任意 datetime 换算到提示词时区。

    无时区信息的 datetime 视为系统本地时间（datetime.now()/fromtimestamp 的语义），
    带时区的 datetime 按其自身时区换算。
    """

    return value.astimezone(PROMPT_TZ)


def prompt_now() -> datetime:
    """返回提示词时区下的当前时间。"""

    return datetime.now(PROMPT_TZ)


def format_prompt_datetime(value: datetime) -> str:
    """格式化为带日期的提示词时间，例如 2026-10-06 02:10:07。"""

    return to_prompt_tz(value).strftime(PROMPT_DATETIME_FORMAT)


def format_prompt_timestamp(timestamp: float, fmt: str = PROMPT_DATETIME_FORMAT) -> str:
    """把 Unix 时间戳格式化为提示词时区时间。"""

    return datetime.fromtimestamp(timestamp, PROMPT_TZ).strftime(fmt)

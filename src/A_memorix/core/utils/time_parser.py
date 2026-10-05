"""
时间解析工具。

约束：
1. 查询参数（Action/Command/Tool）仅接受结构化绝对时间：
   - YYYY/MM/DD、YYYY-MM-DD
   - YYYY/MM/DD HH:mm、YYYY-MM-DD HH:mm
   - YYYY/MM/DD HH:mm:ss、YYYY-MM-DD HH:mm:ss（与提示词当前时间格式一致）
2. 入库时允许更宽松格式（含时间戳、YYYY-MM-DD 等）。
3. 时区口径：所有无时区日历字符串（查询与入库）一律按业务时区 UTC+8（北京时间，
   与提示词 ``src.common.utils.prompt_time.PROMPT_TZ`` 同一来源）解释；
   Unix 时间戳本身没有时区，原样保留，不做任何偏移。
   旧实现用 naive ``datetime.timestamp()``，在 UTC 服务器上把北京时间整体错移 8 小时（审计 F01）。
4. 区间口径：时间窗口统一为半开区间 ``[start, end)``。
   - 只写日期的结束边界取“次日 00:00（不含）”，覆盖当天完整 24 小时（审计 F06，
     旧实现取 23:59:00，漏掉最后一分钟）。
   - 带时分（秒）的结束边界即该时刻本身（不含）。
   - 入库的日期精度事件区间同样是半开 ``[当天 00:00, 次日 00:00)``。
   - 下游段落（dual_path._is_temporal_match）、段落 SQL（metadata_store.query_paragraphs_temporal）
     与 Episode SQL（metadata_episode）统一使用半开区间相交判定：
     ``effective_start < end AND (effective_end > start OR effective_start >= start)``，
     后一项保证单点事件（start == end）恰好落在窗口起点时仍命中。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple, Union

from src.common.utils.prompt_time import PROMPT_TZ

MEMORY_CALENDAR_TZ = PROMPT_TZ
"""记忆日历字符串使用的业务时区（UTC+8），与提示词时区同源。"""

MEMORY_DISPLAY_FORMAT = "%Y/%m/%d %H:%M"

_QUERY_DATE_RE = re.compile(r"^\d{4}([/-])\d{2}\1\d{2}$")
_QUERY_DATETIME_RE = re.compile(r"^\d{4}([/-])\d{2}\1\d{2} \d{2}:\d{2}(?::\d{2})?$")
_NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?$")

_INGEST_FORMATS = [
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y/%m/%d",
    "%Y-%m-%d",
]

_INGEST_DATE_FORMATS = {"%Y/%m/%d", "%Y-%m-%d"}

_REFERENCE_FORMATS = [
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d",
    "%Y-%m-%d",
]


def _calendar_to_timestamp(dt: datetime) -> float:
    """把按业务时区书写的 naive 日历时间转换为 Unix 时间戳。"""
    return dt.replace(tzinfo=MEMORY_CALENDAR_TZ).timestamp()


def _date_bound_timestamp(dt: datetime, *, is_end: bool) -> float:
    """日期精度边界：起点为当天 00:00，终点为次日 00:00（半开区间，不含）。"""
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=MEMORY_CALENDAR_TZ)
    if is_end:
        day_start = day_start + timedelta(days=1)
    return day_start.timestamp()


def parse_query_datetime_to_timestamp(value: str, is_end: bool = False) -> float:
    """解析查询时间（北京时间 UTC+8）。

    支持 YYYY/MM/DD、YYYY-MM-DD，以及追加 `` HH:mm`` 或 `` HH:mm:ss``。
    日期型结束边界返回次日 00:00 的时间戳（开区间端点）。
    """
    text = str(value).strip()
    if not text:
        raise ValueError("时间不能为空")

    normalized = text.replace("/", "-")
    if _QUERY_DATE_RE.fullmatch(text):
        dt = datetime.strptime(normalized, "%Y-%m-%d")
        return _date_bound_timestamp(dt, is_end=is_end)

    if _QUERY_DATETIME_RE.fullmatch(text):
        fmt = "%Y-%m-%d %H:%M:%S" if normalized.count(":") == 2 else "%Y-%m-%d %H:%M"
        dt = datetime.strptime(normalized, fmt)
        return _calendar_to_timestamp(dt)

    raise ValueError(
        f"时间格式错误: {text}。仅支持 YYYY-MM-DD、YYYY-MM-DD HH:mm、YYYY-MM-DD HH:mm:ss"
        "（也接受 / 分隔），按北京时间（UTC+8）解释"
    )


def _parse_query_bound(value: Union[str, float, int, None], *, is_end: bool) -> Optional[float]:
    """查询边界：数值时间戳原样保留精度，字符串按 UTC+8 日历解析。"""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"时间参数类型错误: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    return parse_query_datetime_to_timestamp(text, is_end=is_end)


def parse_query_time_range(
    time_from: Union[str, float, int, None],
    time_to: Union[str, float, int, None],
) -> Tuple[Optional[float], Optional[float]]:
    """解析查询窗口并验证区间，返回半开区间 ``[ts_from, ts_to)``。

    数值边界视为已规范化的 Unix 时间戳，直接沿用（审计 F05：不再经分钟文本往返）。
    """
    ts_from = _parse_query_bound(time_from, is_end=False)
    ts_to = _parse_query_bound(time_to, is_end=True)

    if ts_from is not None and ts_to is not None and ts_from >= ts_to:
        raise ValueError("time_from 必须早于 time_to（结束时间不含）")

    return ts_from, ts_to


def parse_ingest_datetime_to_timestamp(
    value: Any,
    is_end: bool = False,
) -> Optional[float]:
    """解析入库时间，允许 timestamp/常见字符串格式。

    无时区字符串按 UTC+8 解释；数值时间戳原样返回。
    日期型结束边界存为次日 00:00（半开区间，与查询口径一致）。
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    if _NUMERIC_RE.fullmatch(text):
        return float(text)

    for fmt in _INGEST_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt in _INGEST_DATE_FORMATS:
            return _date_bound_timestamp(dt, is_end=is_end)
        return _calendar_to_timestamp(dt)

    raise ValueError(f"无法解析时间: {text}")


def parse_reference_datetime(value: Optional[str]) -> Optional[datetime]:
    """解析导入参考时间（用于相对日期抽取），返回 UTC+8 aware datetime。

    - 未提供时返回 None：来源日期未知，调用方不得以导入当天代替（审计 F08）。
    - 无法解析时抛出 ValueError，不再静默替换为当前时间。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in _REFERENCE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=MEMORY_CALENDAR_TZ)
        except ValueError:
            continue
    raise ValueError(
        f"chat_reference_time 格式错误: {text}。仅支持 YYYY-MM-DD[ HH:mm[:ss]]（也接受 / 分隔），按北京时间（UTC+8）解释"
    )


def normalize_time_meta(time_meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """归一化 time_meta 到存储层字段。"""
    if not time_meta:
        return {}

    normalized: Dict[str, Any] = {}

    event_time = parse_ingest_datetime_to_timestamp(time_meta.get("event_time"))
    event_start = parse_ingest_datetime_to_timestamp(
        time_meta.get("event_time_start"),
        is_end=False,
    )
    event_end = parse_ingest_datetime_to_timestamp(
        time_meta.get("event_time_end"),
        is_end=True,
    )

    time_range = time_meta.get("time_range")
    if isinstance(time_range, (list, tuple)) and len(time_range) == 2:
        if event_start is None:
            event_start = parse_ingest_datetime_to_timestamp(time_range[0], is_end=False)
        if event_end is None:
            event_end = parse_ingest_datetime_to_timestamp(time_range[1], is_end=True)

    if event_start is not None and event_end is not None and event_start > event_end:
        raise ValueError("event_time_start 不能晚于 event_time_end")

    if event_time is not None:
        normalized["event_time"] = event_time
    if event_start is not None:
        normalized["event_time_start"] = event_start
    if event_end is not None:
        normalized["event_time_end"] = event_end

    granularity = time_meta.get("time_granularity")
    if granularity:
        normalized["time_granularity"] = str(granularity)
    else:
        raw_time_values = [
            time_meta.get("event_time"),
            time_meta.get("event_time_start"),
            time_meta.get("event_time_end"),
        ]
        has_minute = any(isinstance(v, str) and ":" in v for v in raw_time_values if v is not None)
        normalized["time_granularity"] = "minute" if has_minute else "day"

    confidence = time_meta.get("time_confidence")
    if confidence is not None:
        normalized["time_confidence"] = float(confidence)

    return normalized


def format_timestamp(ts: Optional[float]) -> Optional[str]:
    """将 timestamp 格式化为北京时间（UTC+8）的 YYYY/MM/DD HH:mm，仅用于展示。"""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, MEMORY_CALENDAR_TZ).strftime(MEMORY_DISPLAY_FORMAT)

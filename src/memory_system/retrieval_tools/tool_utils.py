"""
工具函数库
包含所有工具共用的工具函数
"""

from datetime import datetime
from typing import Tuple


def parse_datetime_to_timestamp(value: str) -> float:
    """
    接受多种常见格式并转换为时间戳（秒）
    支持示例：
    - 2025-09-29
    - 2025-09-29 00:00:00
    - 2025/09/29 00:00
    - 2025-09-29T00:00:00
    """
    value = value.strip()
    fmts = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
    ]
    last_err = None
    for fmt in fmts:
        try:
            dt = datetime.strptime(value, fmt)
            return dt.timestamp()
        except Exception as e:
            last_err = e
    raise ValueError(f"无法解析时间: {value} ({last_err})")


def parse_time_range(time_range: str) -> Tuple[float, float]:
    """
    解析时间范围字符串，返回开始和结束时间戳
    
    Args:
        time_range: 时间范围字符串，格式："YYYY-MM-DD HH:MM:SS - YYYY-MM-DD HH:MM:SS"
        
    Returns:
        Tuple[float, float]: (开始时间戳, 结束时间戳)
    """
    if " - " not in time_range:
        raise ValueError(f"时间范围格式错误，应为 '开始时间 - 结束时间': {time_range}")
    
    parts = time_range.split(" - ", 1)
    if len(parts) != 2:
        raise ValueError(f"时间范围格式错误: {time_range}")
    
    start_str = parts[0].strip()
    end_str = parts[1].strip()
    
    start_timestamp = parse_datetime_to_timestamp(start_str)
    end_timestamp = parse_datetime_to_timestamp(end_str)
    
    return start_timestamp, end_timestamp


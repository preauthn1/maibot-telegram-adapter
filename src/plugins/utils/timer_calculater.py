from time import perf_counter
from typing import Dict, Optional

"""
计时器：用于性能计时

感谢D指导
"""


class TimerTypeError(TypeError):
    """自定义类型错误异常"""

    def __init__(self, param_name, expected_type, actual_type):
        super().__init__(f"Invalid type for '{param_name}'. Expected {expected_type}, got {actual_type.__name__}")


class Timer:
    def __init__(self, name: Optional[str] = None, storage: Optional[Dict[str, float]] = None):
        self.name = name  # 计时器名称
        self.storage = storage  # 计时结果存储
        self.elapsed = None  # 计时结果

    def _validate_types(self, name, storage):
        """类型验证核心方法"""
        # 验证 name 类型
        if name is not None and not isinstance(name, str):
            raise TimerTypeError(param_name="name", expected_type="Optional[str]", actual_type=type(name))

        # 验证 storage 类型
        if storage is not None and not isinstance(storage, dict):
            raise TimerTypeError(
                param_name="storage", expected_type="Optional[Dict[str, float]]", actual_type=type(storage)
            )

    def __enter__(self):
        self.start = perf_counter()
        return self

    def __exit__(self, *args):
        self.end = perf_counter()
        self.elapsed = self.end - self.start
        if isinstance(self.storage, dict) and self.name:
            self.storage[self.name] = self.elapsed

    def get_result(self) -> float:
        """安全获取计时结果"""
        return self.elapsed or 0.0

    def human_readable(self) -> str:
        """返回人类可读时间格式"""
        if self.elapsed >= 1:
            return f"{self.elapsed:.2f}秒"
        return f"{self.elapsed * 1000:.2f}毫秒"

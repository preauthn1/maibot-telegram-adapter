from loguru import logger
from typing import Dict, Optional, Union, List
import sys
from types import ModuleType
from pathlib import Path

# logger.remove()

# 类型别名
LoguruLogger = logger.__class__

# 全局注册表：记录模块与处理器ID的映射
_handler_registry: Dict[str, List[int]] = {}

# 获取日志存储根地址
current_file_path = Path(__file__).resolve()
LOG_ROOT = "logs"

# 默认全局配置
DEFAULT_CONFIG = {

    # 日志级别配置
    "console_level": "DEBUG",  # 控制台默认级别（可覆盖）
    "file_level": "DEBUG",  # 文件默认级别（可覆盖）

    # 格式配置
    "console_format": (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{extra[module]: <4}</cyan> | "
        "<level>{message}</level>"
    ),
    "file_format": (
        "{time:YYYY-MM-DD HH:mm:ss} | "
        "{level: <8} | "
        "{extra[module]: <20} | "
        "{message}"
    ),
    "log_dir": LOG_ROOT,  # 默认日志目录，需保留
    "rotation": "100 MB",  # 设定轮转
    "retention": "7 days",  # 设定时长
    "compression": "zip",  # 设定压缩
}


class LogConfig:
    """日志配置类"""

    def __init__(self, **kwargs):
        self.config = DEFAULT_CONFIG.copy()
        self.config.update(kwargs)

    def to_dict(self) -> dict:
        return self.config.copy()

    def update(self, **kwargs):
        self.config.update(kwargs)


def get_module_logger(
        module: Union[str, ModuleType],
        *,
        console_level: Optional[str] = None,
        file_level: Optional[str] = None,
        extra_handlers: Optional[List[dict]] = None,
        config: Optional[LogConfig] = None
) -> LoguruLogger:
    module_name = module if isinstance(module, str) else module.__name__
    current_config = config.config if config else DEFAULT_CONFIG

    # 若模块已注册，先移除旧处理器（避免重复添加）
    if module_name in _handler_registry:
        for handler_id in _handler_registry[module_name]:
            logger.remove(handler_id)
        del _handler_registry[module_name]

    handler_ids = []

    # 控制台处理器
    console_id = logger.add(
        sink=sys.stderr,
        level=console_level or current_config["console_level"],
        format=current_config["console_format"],
        filter=lambda record: record["extra"].get("module") == module_name,
        enqueue=current_config.get("enqueue", True),
        backtrace=current_config.get("backtrace", False),
        diagnose=current_config.get("diagnose", False),
    )
    handler_ids.append(console_id)

    # 文件处理器
    log_dir = Path(current_config["log_dir"])
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{module_name}_{{time:YYYY-MM-DD}}.log"

    file_id = logger.add(
        sink=str(log_file),
        level=file_level or current_config["file_level"],
        format=current_config["file_format"],
        rotation=current_config["rotation"],
        retention=current_config["retention"],
        compression=current_config["compression"],
        encoding=current_config.get("encoding", "utf-8"),
        filter=lambda record: record["extra"].get("module") == module_name,
        enqueue=current_config.get("enqueue", True),
    )
    handler_ids.append(file_id)

    # 额外处理器
    if extra_handlers:
        for handler in extra_handlers:
            handler_id = logger.add(**handler)
            handler_ids.append(handler_id)

    # 更新注册表
    _handler_registry[module_name] = handler_ids

    return logger.bind(module=module_name)


def remove_module_logger(module_name: str) -> None:
    """清理指定模块的日志处理器"""
    if module_name in _handler_registry:
        for handler_id in _handler_registry[module_name]:
            logger.remove(handler_id)
        del _handler_registry[module_name]

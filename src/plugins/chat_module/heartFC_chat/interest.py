import time
import math
import asyncio
import threading
import json # 引入 json
import os   # 引入 os
import traceback # <--- 添加导入
from typing import Optional # <--- 添加导入
from src.common.logger import get_module_logger, LogConfig, DEFAULT_CONFIG # 引入 DEFAULT_CONFIG
from src.plugins.chat.chat_stream import chat_manager # *** Import ChatManager ***
from ...chat.message import MessageRecv # 导入 MessageRecv

# 定义日志配置 (使用 loguru 格式)
interest_log_config = LogConfig(
    console_format=DEFAULT_CONFIG["console_format"], # 使用默认控制台格式
    file_format=DEFAULT_CONFIG["file_format"]     # 使用默认文件格式
)
logger = get_module_logger("InterestManager", config=interest_log_config)


# 定义常量
DEFAULT_DECAY_RATE_PER_SECOND = 0.95  # 每秒衰减率 (兴趣保留 99%)
# DEFAULT_INCREASE_AMOUNT = 10.0      # 不再需要固定增加值
MAX_INTEREST = 10.0                # 最大兴趣值
MIN_INTEREST_THRESHOLD = 0.1      # 低于此值可能被清理 (可选)
CLEANUP_INTERVAL_SECONDS = 3600     # 清理任务运行间隔 (例如：1小时)
INACTIVE_THRESHOLD_SECONDS = 3600 * 24 # 不活跃时间阈值 (例如：1天)
LOG_INTERVAL_SECONDS = 3  # 日志记录间隔 (例如：30秒)
LOG_DIRECTORY = "logs/interest" # 日志目录
LOG_FILENAME = "interest_log.json" # 快照日志文件名 (保留，以防其他地方用到)
HISTORY_LOG_FILENAME = "interest_history.log" # 新的历史日志文件名
# 移除阈值，将移至 HeartFC_Chat
# INTEREST_INCREASE_THRESHOLD = 0.5

class InterestChatting:
    def __init__(self, decay_rate=DEFAULT_DECAY_RATE_PER_SECOND, max_interest=MAX_INTEREST):
        self.interest_level: float = 0.0
        self.last_update_time: float = time.time()
        self.decay_rate_per_second: float = decay_rate
        # self.increase_amount: float = increase_amount # 移除固定的 increase_amount
        self.max_interest: float = max_interest
        # 新增：用于追踪最后一次显著增加的信息，供外部监控任务使用
        self.last_increase_amount: float = 0.0
        self.last_triggering_message: MessageRecv | None = None

    def _calculate_decay(self, current_time: float):
        """计算从上次更新到现在的衰减"""
        time_delta = current_time - self.last_update_time
        if time_delta > 0:
            # 指数衰减: interest = interest * (decay_rate ^ time_delta)
            # 添加处理极小兴趣值避免 math domain error
            if self.interest_level < 1e-9:
                self.interest_level = 0.0
            else:
                # 检查 decay_rate_per_second 是否为非正数，避免 math domain error
                if self.decay_rate_per_second <= 0:
                     logger.warning(f"InterestChatting encountered non-positive decay rate: {self.decay_rate_per_second}. Setting interest to 0.")
                     self.interest_level = 0.0
                # 检查 interest_level 是否为负数，虽然理论上不应发生，但以防万一
                elif self.interest_level < 0:
                     logger.warning(f"InterestChatting encountered negative interest level: {self.interest_level}. Setting interest to 0.")
                     self.interest_level = 0.0
                else:
                    try:
                        decay_factor = math.pow(self.decay_rate_per_second, time_delta)
                        self.interest_level *= decay_factor
                    except ValueError as e:
                        # 捕获潜在的 math domain error，例如对负数开非整数次方（虽然已加保护）
                        logger.error(f"Math error during decay calculation: {e}. Rate: {self.decay_rate_per_second}, Delta: {time_delta}, Level: {self.interest_level}. Setting interest to 0.")
                        self.interest_level = 0.0

            # 防止低于阈值 (如果需要)
            # self.interest_level = max(self.interest_level, MIN_INTEREST_THRESHOLD)
            self.last_update_time = current_time

    def increase_interest(self, current_time: float, value: float, message: Optional[MessageRecv]):
        """根据传入的值增加兴趣值，并记录增加量和关联消息"""
        self._calculate_decay(current_time) # 先计算衰减
        # 记录这次增加的具体数值和消息，供外部判断是否触发
        self.last_increase_amount = value
        self.last_triggering_message = message
        # 应用增加
        self.interest_level += value
        self.interest_level = min(self.interest_level, self.max_interest) # 不超过最大值
        self.last_update_time = current_time # 更新时间戳

    def decrease_interest(self, current_time: float, value: float):
        """降低兴趣值并更新时间 (确保不低于0)"""
        # 注意：降低兴趣度是否需要先衰减？取决于具体逻辑，这里假设不衰减直接减
        self.interest_level -= value
        self.interest_level = max(self.interest_level, 0.0) # 确保不低于0
        self.last_update_time = current_time # 降低也更新时间戳

    def reset_trigger_info(self):
        """重置触发相关信息，在外部任务处理后调用"""
        self.last_increase_amount = 0.0
        self.last_triggering_message = None

    def get_interest(self) -> float:
        """获取当前兴趣值 (由后台任务更新)"""
        return self.interest_level

    def get_state(self) -> dict:
        """获取当前状态字典"""
        # 不再需要传入 current_time 来计算，直接获取
        interest = self.get_interest() # 使用修改后的 get_interest
        return {
            "interest_level": round(interest, 2),
            "last_update_time": self.last_update_time,
            # 可以选择性地暴露 last_increase_amount 给状态，方便调试
            # "last_increase_amount": round(self.last_increase_amount, 2)
        }


class InterestManager:
    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                # Double-check locking
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            with self._lock:
                # 确保初始化也只执行一次
                if not self._initialized:
                    logger.info("Initializing InterestManager singleton...")
                    # key: stream_id (str), value: InterestChatting instance
                    self.interest_dict: dict[str, InterestChatting] = {}
                    # 保留旧的快照文件路径变量，尽管此任务不再写入
                    self._snapshot_log_file_path = os.path.join(LOG_DIRECTORY, LOG_FILENAME)
                    # 定义新的历史日志文件路径
                    self._history_log_file_path = os.path.join(LOG_DIRECTORY, HISTORY_LOG_FILENAME)
                    self._ensure_log_directory()
                    self._cleanup_task = None
                    self._logging_task = None # 添加日志任务变量
                    self._initialized = True
                    logger.info("InterestManager initialized.") # 修改日志消息
                    self._decay_task = None # 新增：衰减任务变量

    def _ensure_log_directory(self):
        """确保日志目录存在"""
        try:
            os.makedirs(LOG_DIRECTORY, exist_ok=True)
            logger.info(f"Log directory '{LOG_DIRECTORY}' ensured.")
        except OSError as e:
            logger.error(f"Error creating log directory '{LOG_DIRECTORY}': {e}")

    async def _periodic_cleanup_task(self, interval_seconds: int, threshold: float, max_age_seconds: int):
        """后台清理任务的异步函数"""
        while True:
            await asyncio.sleep(interval_seconds)
            logger.info(f"Running periodic cleanup (interval: {interval_seconds}s)...")
            self.cleanup_inactive_chats(threshold=threshold, max_age_seconds=max_age_seconds)

    async def _periodic_log_task(self, interval_seconds: int):
        """后台日志记录任务的异步函数 (记录历史数据，包含 group_name)"""
        while True:
            await asyncio.sleep(interval_seconds)
            logger.debug(f"Running periodic history logging (interval: {interval_seconds}s)...")
            try:
                current_timestamp = time.time()
                all_states = self.get_all_interest_states() # 获取当前所有状态
                
                # 以追加模式打开历史日志文件
                with open(self._history_log_file_path, 'a', encoding='utf-8') as f:
                    count = 0
                    for stream_id, state in all_states.items():
                        # *** Get group name from ChatManager ***
                        group_name = stream_id # Default to stream_id
                        try:
                            # Use the imported chat_manager instance
                            chat_stream = chat_manager.get_stream(stream_id)
                            if chat_stream and chat_stream.group_info:
                                group_name = chat_stream.group_info.group_name
                            elif chat_stream and not chat_stream.group_info:
                                # Handle private chats - maybe use user nickname?
                                group_name = f"私聊_{chat_stream.user_info.user_nickname}" if chat_stream.user_info else stream_id
                        except Exception as e:
                            logger.warning(f"Could not get group name for stream_id {stream_id}: {e}")
                            # Fallback to stream_id is already handled by default value

                        log_entry = {
                            "timestamp": round(current_timestamp, 2),
                            "stream_id": stream_id,
                            "interest_level": state.get("interest_level", 0.0), # 确保有默认值
                            "group_name": group_name # *** Add group_name ***
                        }
                        # 将每个条目作为单独的 JSON 行写入
                        f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
                        count += 1
                logger.debug(f"Successfully appended {count} interest history entries to {self._history_log_file_path}")
                
                # 注意：不再写入快照文件 interest_log.json
                # 如果需要快照文件，可以在这里单独写入 self._snapshot_log_file_path
                # 例如：
                # with open(self._snapshot_log_file_path, 'w', encoding='utf-8') as snap_f:
                #     json.dump(all_states, snap_f, indent=4, ensure_ascii=False)
                # logger.debug(f"Successfully wrote snapshot to {self._snapshot_log_file_path}")
                
            except IOError as e:
                logger.error(f"Error writing interest history log to {self._history_log_file_path}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error during periodic history logging: {e}")

    async def _periodic_decay_task(self):
        """后台衰减任务的异步函数，每秒更新一次所有实例的衰减"""
        while True:
            await asyncio.sleep(1) # 每秒运行一次
            current_time = time.time()
            # logger.debug("Running periodic decay calculation...") # 调试日志，可能过于频繁

            # 创建字典项的快照进行迭代，避免在迭代时修改字典的问题
            items_snapshot = list(self.interest_dict.items())
            count = 0
            for stream_id, chatting in items_snapshot:
                try:
                    # 调用 InterestChatting 实例的衰减方法
                    chatting._calculate_decay(current_time)
                    count += 1
                except Exception as e:
                    logger.error(f"Error calculating decay for stream_id {stream_id}: {e}")
            # if count > 0: # 仅在实际处理了项目时记录日志，避免空闲时刷屏
            #     logger.debug(f"Applied decay to {count} streams.")

    async def start_background_tasks(self):
        """Starts the background cleanup, logging, and decay tasks."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(
                self._periodic_cleanup_task(
                    interval_seconds=CLEANUP_INTERVAL_SECONDS,
                    threshold=MIN_INTEREST_THRESHOLD,
                    max_age_seconds=INACTIVE_THRESHOLD_SECONDS
                )
            )
            logger.info(f"Periodic cleanup task created. Interval: {CLEANUP_INTERVAL_SECONDS}s, Inactive Threshold: {INACTIVE_THRESHOLD_SECONDS}s")
        else:
            logger.warning("Cleanup task creation skipped: already running or exists.")

        if self._logging_task is None or self._logging_task.done():
            self._logging_task = asyncio.create_task(
                self._periodic_log_task(interval_seconds=LOG_INTERVAL_SECONDS)
            )
            logger.info(f"Periodic logging task created. Interval: {LOG_INTERVAL_SECONDS}s")
        else:
            logger.warning("Logging task creation skipped: already running or exists.")

        # 启动新的衰减任务
        if self._decay_task is None or self._decay_task.done():
            self._decay_task = asyncio.create_task(
                self._periodic_decay_task()
            )
            logger.info("Periodic decay task created. Interval: 1s")
        else:
            logger.warning("Decay task creation skipped: already running or exists.")

    def get_all_interest_states(self) -> dict[str, dict]:
        """获取所有聊天流的当前兴趣状态"""
        # 不再需要 current_time, 因为 get_state 现在不接收它
        states = {}
        # 创建副本以避免在迭代时修改字典
        items_snapshot = list(self.interest_dict.items())
        for stream_id, chatting in items_snapshot:
            try:
                # 直接调用 get_state，它会使用内部的 get_interest 获取已更新的值
                states[stream_id] = chatting.get_state()
            except Exception as e:
                 logger.warning(f"Error getting state for stream_id {stream_id}: {e}")
        return states

    def get_interest_chatting(self, stream_id: str) -> Optional[InterestChatting]:
        """获取指定流的 InterestChatting 实例，如果不存在则返回 None"""
        return self.interest_dict.get(stream_id)

    def _get_or_create_interest_chatting(self, stream_id: str) -> InterestChatting:
        """获取或创建指定流的 InterestChatting 实例 (线程安全)"""
        # 由于字典操作本身在 CPython 中大部分是原子的，
        # 且主要写入发生在 __init__ 和 cleanup (由单任务执行)，
        # 读取和 get_or_create 主要在事件循环线程，简单场景下可能不需要锁。
        # 但为保险起见或跨线程使用考虑，可加锁。
        # with self._lock:
        if stream_id not in self.interest_dict:
            logger.debug(f"Creating new InterestChatting for stream_id: {stream_id}")
            self.interest_dict[stream_id] = InterestChatting()
            # 首次创建时兴趣为 0，由第一次消息的 activate rate 决定初始值
        return self.interest_dict[stream_id]

    def get_interest(self, stream_id: str) -> float:
        """获取指定聊天流当前的兴趣度 (值由后台任务更新)"""
        # current_time = time.time() # 不再需要获取当前时间
        interest_chatting = self._get_or_create_interest_chatting(stream_id)
        # 直接调用修改后的 get_interest，不传入时间
        return interest_chatting.get_interest()

    def increase_interest(self, stream_id: str, value: float, message: MessageRecv):
        """当收到消息时，增加指定聊天流的兴趣度，并传递关联消息"""
        current_time = time.time()
        interest_chatting = self._get_or_create_interest_chatting(stream_id)
        # 调用修改后的 increase_interest，传入 message
        interest_chatting.increase_interest(current_time, value, message)
        logger.debug(f"Increased interest for stream_id: {stream_id} by {value:.2f} to {interest_chatting.interest_level:.2f}") # 更新日志

    def decrease_interest(self, stream_id: str, value: float):
        """降低指定聊天流的兴趣度"""
        current_time = time.time()
        # 尝试获取，如果不存在则不做任何事
        interest_chatting = self.get_interest_chatting(stream_id)
        if interest_chatting:
            interest_chatting.decrease_interest(current_time, value)
            logger.debug(f"Decreased interest for stream_id: {stream_id} by {value:.2f} to {interest_chatting.interest_level:.2f}")
        else:
            logger.warning(f"Attempted to decrease interest for non-existent stream_id: {stream_id}")

    def cleanup_inactive_chats(self, threshold=MIN_INTEREST_THRESHOLD, max_age_seconds=INACTIVE_THRESHOLD_SECONDS):
        """
        清理长时间不活跃或兴趣度过低的聊天流记录
        threshold: 低于此兴趣度的将被清理
        max_age_seconds: 超过此时间未更新的将被清理
        """
        current_time = time.time()
        keys_to_remove = []
        initial_count = len(self.interest_dict)
        # with self._lock: # 如果需要锁整个迭代过程
        # 创建副本以避免在迭代时修改字典
        items_snapshot = list(self.interest_dict.items())

        for stream_id, chatting in items_snapshot:
            # 先计算当前兴趣，确保是最新的
            # 加锁保护 chatting 对象状态的读取和可能的修改
            # with self._lock: # 如果 InterestChatting 内部操作不是原子的
            interest = chatting.get_interest()
            last_update = chatting.last_update_time

            should_remove = False
            reason = ""
            if interest < threshold:
                should_remove = True
                reason = f"interest ({interest:.2f}) < threshold ({threshold})"
            # 只有设置了 max_age_seconds 才检查时间
            if max_age_seconds is not None and (current_time - last_update) > max_age_seconds:
                should_remove = True
                reason = f"inactive time ({current_time - last_update:.0f}s) > max age ({max_age_seconds}s)" + (f", {reason}" if reason else "") # 附加之前的理由

            if should_remove:
                keys_to_remove.append(stream_id)
                logger.debug(f"Marking stream_id {stream_id} for removal. Reason: {reason}")

        if keys_to_remove:
            logger.info(f"Cleanup identified {len(keys_to_remove)} inactive/low-interest streams.")
            # with self._lock: # 确保删除操作的原子性
            for key in keys_to_remove:
                 # 再次检查 key 是否存在，以防万一在迭代和删除之间状态改变
                if key in self.interest_dict:
                    del self.interest_dict[key]
                    logger.debug(f"Removed stream_id: {key}")
            final_count = initial_count - len(keys_to_remove)
            logger.info(f"Cleanup finished. Removed {len(keys_to_remove)} streams. Current count: {final_count}")
        else:
            logger.info(f"Cleanup finished. No streams met removal criteria. Current count: {initial_count}")


# 不再需要手动创建实例和任务
# manager = InterestManager()
# asyncio.create_task(periodic_cleanup(manager, 3600))
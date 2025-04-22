import traceback
from typing import Optional, Dict
import asyncio
import threading  # 导入 threading
from ..moods.moods import MoodManager
from ..chat.emoji_manager import emoji_manager
from .heartFC_generator import ResponseGenerator
from .heartflow_message_sender import MessageManager
from src.heart_flow.heartflow import heartflow, MaiState
from src.heart_flow.sub_heartflow import SubHeartflow, ChatState
from src.common.logger import get_module_logger, CHAT_STYLE_CONFIG, LogConfig
from src.plugins.person_info.relationship_manager import relationship_manager
from src.do_tool.tool_use import ToolUser
from src.plugins.chat.chat_stream import chat_manager
from .heartFC_chat import PFChatting


# 定义日志配置
chat_config = LogConfig(
    console_format=CHAT_STYLE_CONFIG["console_format"],
    file_format=CHAT_STYLE_CONFIG["file_format"],
)

logger = get_module_logger("HeartFCController", config=chat_config)

# 检测群聊兴趣的间隔时间
INTEREST_MONITOR_INTERVAL_SECONDS = 1


class HeartFCController:
    _instance: Optional['HeartFCController'] = None
    _lock = threading.Lock()  # 用于保证 get_instance 线程安全

    def __init__(self):
        # __init__ 现在只会在 get_instance 首次创建实例时调用一次
        # 因此不再需要 _initialized 标志

        # 检查是否已被初始化，防止意外重入 (虽然理论上不太可能)
        # hasattr 检查通常比标志位稍慢，但在这里作为额外的安全措施
        if hasattr(self, 'gpt'):
            logger.warning("HeartFCController __init__ 被意外再次调用。")
            return

        logger.debug("初始化 HeartFCController 单例实例...") # 更新日志信息
        self.gpt = ResponseGenerator()
        self.mood_manager = MoodManager.get_instance()
        self.tool_user = ToolUser()
        self._interest_monitor_task: Optional[asyncio.Task] = None

        self.heartflow = heartflow

        self.heartFC_chat_instances: Dict[str, PFChatting] = {}
        self._heartFC_chat_lock = asyncio.Lock()
        self.emoji_manager = emoji_manager
        self.relationship_manager = relationship_manager

        self.MessageManager = MessageManager
        logger.info("HeartFCController 单例初始化完成。")

    @classmethod
    def get_instance(cls):
        """获取 HeartFCController 的单例实例。线程安全。"""
        # Double-checked locking
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    logger.info("HeartFCController 实例不存在，正在创建...")
                    # 创建实例，这将自动调用 __init__ 一次
                    cls._instance = cls()
                    logger.info("HeartFCController 实例已创建并初始化。")
        # else: # 不需要这个 else 日志，否则每次获取都会打印
            # logger.debug("返回已存在的 HeartFCController 实例。")
        return cls._instance

    # --- 新增：检查 PFChatting 状态的方法 --- #
    def is_heartFC_chat_active(self, stream_id: str) -> bool:
        """检查指定 stream_id 的 PFChatting 循环是否处于活动状态。"""
        # 注意：这里直接访问字典，不加锁，因为读取通常是安全的，
        # 并且 PFChatting 实例的 _loop_active 状态由其自身的异步循环管理。
        # 如果需要更强的保证，可以在访问 pf_instance 前获取 _heartFC_chat_lock
        pf_instance = self.heartFC_chat_instances.get(stream_id)
        if pf_instance and pf_instance._loop_active:  # 直接检查 PFChatting 实例的 _loop_active 属性
            return True
        return False

    # --- 结束新增 --- #

    async def start(self):
        """启动异步任务,如回复启动器"""
        logger.debug("HeartFCController 正在启动异步任务...")
        self._initialize_monitor_task()
        logger.info("HeartFCController 异步任务启动完成")

    def _initialize_monitor_task(self):
        """启动后台兴趣监控任务，可以检查兴趣是否足以开启心流对话"""
        if self._interest_monitor_task is None or self._interest_monitor_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._interest_monitor_task = loop.create_task(self._response_control_loop())
            except RuntimeError:
                logger.error("创建兴趣监控任务失败：没有运行中的事件循环。")
                raise
        else:
            logger.warning("跳过兴趣监控任务创建：任务已存在或正在运行。")

    # --- Added PFChatting Instance Manager ---
    async def _get_or_create_heartFC_chat(self, stream_id: str) -> Optional[PFChatting]:
        """获取现有PFChatting实例或创建新实例。"""
        async with self._heartFC_chat_lock:
            if stream_id not in self.heartFC_chat_instances:
                logger.info(f"为流 {stream_id} 创建新的PFChatting实例")
                # 传递 self (HeartFCController 实例) 进行依赖注入
                instance = PFChatting(stream_id, self)
                # 执行异步初始化
                if not await instance._initialize():
                    logger.error(f"为流 {stream_id} 初始化PFChatting失败")
                    return None
                self.heartFC_chat_instances[stream_id] = instance
            return self.heartFC_chat_instances[stream_id]

    async def stop_heartFC_chat(self, stream_id: str):
        """尝试停止并清理指定 stream_id 的 PFChatting 实例。"""
        async with self._heartFC_chat_lock:
            pf_instance = self.heartFC_chat_instances.pop(stream_id, None) # 从字典中移除
            if pf_instance:
                stream_name = chat_manager.get_stream_name(stream_id) or stream_id
                logger.info(f"[{stream_name}] 正在停止 PFChatting 实例...")
                try:
                    await pf_instance.shutdown() # 调用实例的 shutdown 方法
                    logger.info(f"[{stream_name}] PFChatting 实例已停止。")
                except Exception as e:
                    logger.error(f"[{stream_name}] 停止 PFChatting 实例时出错: {e}")
            # else:
                # logger.debug(f"[{stream_name}] 没有找到需要停止的 PFChatting 实例。")

    async def _response_control_loop(self):
        """后台任务，定期检查兴趣度变化并触发回复"""
        logger.info("兴趣监控循环开始...")
        while True:
            await asyncio.sleep(INTEREST_MONITOR_INTERVAL_SECONDS)

            try:
                global_mai_state = self.heartflow.current_state.mai_status

                active_stream_ids = list(self.heartflow.get_all_subheartflows_streams_ids())
                for stream_id in active_stream_ids:
                    stream_name = chat_manager.get_stream_name(stream_id) or stream_id
                    sub_hf = self.heartflow.get_subheartflow(stream_id)
                    if not sub_hf:
                        continue

                    current_chat_state = sub_hf.chat_state.chat_status
                    log_prefix = f"[{stream_name}]"

                    if global_mai_state == MaiState.OFFLINE:
                        if current_chat_state == ChatState.FOCUSED:
                             logger.warning(f"{log_prefix} Global state is OFFLINE, but SubHeartflow is FOCUSED. Stopping PFChatting.")
                             await self.stop_heartFC_chat(stream_id)
                        continue

                    # --- 只有在全局状态允许时才执行以下逻辑 --- #
                    if current_chat_state == ChatState.CHAT:
                        should_evaluate = False
                        try:
                            should_evaluate = sub_hf.should_evaluate_reply()
                        except Exception as e:
                            logger.error(f"检查回复概率时出错 流 {stream_name}: {e}")
                            logger.error(traceback.format_exc())

                        if should_evaluate:
                            # --- Limit Check before entering FOCUSED state --- #
                            focused_limit = global_mai_state.get_focused_chat_max_num()
                            current_focused_count = self.heartflow.count_subflows_by_state(ChatState.FOCUSED)

                            if current_focused_count >= focused_limit:
                                logger.debug(f"{log_prefix} 拒绝从 CHAT 转换到 FOCUSED。原因：FOCUSED 状态已达上限 ({focused_limit})。当前数量: {current_focused_count}")
                                # Do not change state, continue to next stream or cycle
                            else:
                                logger.info(f"{log_prefix} 兴趣概率触发，将状态从 CHAT 提升到 FOCUSED (全局状态: {global_mai_state.value}, 上限: {focused_limit}, 当前: {current_focused_count})")
                                sub_hf.set_chat_state(ChatState.FOCUSED)
                            # --- End Limit Check --- #

                    elif current_chat_state == ChatState.FOCUSED:
                        # logger.debug(f"[{stream_name}] State FOCUSED, triggering HFC (全局状态: {global_mai_state.value})...")
                        await self._trigger_hfc(sub_hf)

            except asyncio.CancelledError:
                logger.info("兴趣监控循环已取消。")
                break
            except Exception as e:
                logger.error(f"兴趣监控循环错误: {e}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(5)

    async def _trigger_hfc(self, sub_hf: SubHeartflow):
        """仅当 SubHeartflow 状态为 FOCUSED 时，触发 PFChatting 的激活或时间增加。"""
        stream_id = sub_hf.subheartflow_id
        stream_name = chat_manager.get_stream_name(stream_id) or stream_id # 获取流名称

        # 首先检查状态
        if sub_hf.chat_state.chat_status != ChatState.FOCUSED:
            logger.warning(f"[{stream_name}] 尝试在非 FOCUSED 状态 ({sub_hf.chat_state.chat_status.value}) 下触发 HFC。已跳过。")
            return

        # 移除内部状态修改逻辑
        # chat_state = sub_hf.chat_state
        # if chat_state == ChatState.ABSENT:
        #     chat_state = ChatState.CHAT
        # elif chat_state == ChatState.CHAT:
        #     chat_state = ChatState.FOCUSED

        # 状态已经是 FOCUSED，直接获取或创建 PFChatting 并添加时间
        # logger.debug(f"[{stream_name}] Triggering PFChatting add_time in FOCUSED state.") # Debug log
        pf_instance = await self._get_or_create_heartFC_chat(stream_id)
        if pf_instance:  # 确保实例成功获取或创建
            await pf_instance.add_time() # 注意：这里不再需要 create_task，因为 add_time 内部会处理任务创建
        else:
            logger.error(f"[{stream_name}] 无法获取或创建 PFChatting 实例以触发 HFC。")

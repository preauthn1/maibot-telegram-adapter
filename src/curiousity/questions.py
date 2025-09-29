import time
import asyncio
from src.common.logger import get_logger
from src.common.database.database_model import MemoryConflict
from src.chat.utils.chat_message_builder import (
    get_raw_msg_by_timestamp_with_chat,
    build_readable_messages,
)
from src.llm_models.utils_model import LLMRequest
from src.config.config import model_config, global_config

logger = get_logger("conflict_tracker")

class QuestionTracker:
    """
    用于跟踪一个问题在后续聊天中的解答情况
    """

    def __init__(self, question: str, chat_id: str) -> None:
        self.question = question
        self.chat_id = chat_id
        now = time.time()
        self.start_time = now
        self.last_read_time = now
        self.active = True
        # 将 LLM 实例作为类属性，使用 utils 模型
        self.llm_request = LLMRequest(model_set=model_config.model_task_config.utils, request_type="conflict.judge")

    def stop(self) -> None:
        self.active = False

    async def judge_answer(self, conversation_text: str) -> tuple[bool, str]:
        """
        使用小模型判定问题是否已得到解答。
        返回 (已解答, 答案)
        """
        prompt = (
            "你是一个严谨的判定器。下面给出聊天记录以及一个问题。\n"
            "任务：判断在这段聊天中，该问题是否已经得到明确解答。\n"
            "如果已解答，请只输出：YES: <简短答案>\n"
            "如果没有，请只输出：NO\n\n"
            f"问题：{self.question}\n"
            "聊天记录如下：\n"
            f"{conversation_text}"
        )

        if global_config.debug.show_prompt:
            logger.info(f"判定提示词: {prompt}")
        else:
            logger.debug("已发送判定提示词")

        result_text, _ = await self.llm_request.generate_response_async(prompt, temperature=0.5)
        
        logger.info(f"判定结果: {prompt}\n{result_text}")
        
        if not result_text:
            return False, ""

        text = result_text.strip()
        if text.upper().startswith("YES:"):
            answer = text[4:].strip()
            return True, answer
        if text.upper().startswith("YES"):
            # 兼容仅输出 YES 或 YES <answer>
            answer = text[3:].strip().lstrip(":").strip()
            return True, answer
        return False, ""

class ConflictTracker:
    """
    记忆整合冲突追踪器

    用于记录和存储记忆整合过程中的冲突内容
    """

    async def record_conflict(self, conflict_content: str, start_following: bool = False,chat_id: str = "") -> bool:
        """
        记录冲突内容

        Args:k
            conflict_content: 冲突内容

        Returns:
            bool: 是否成功记录
        """
        try:
            if not conflict_content or conflict_content.strip() == "":
                return False

            # 若需要跟随后续消息以判断是否得到解答，则进入跟踪流程
            if start_following and chat_id:
                tracker = QuestionTracker(conflict_content.strip(), chat_id)
                # 后台启动跟踪任务，避免阻塞
                asyncio.create_task(self._follow_and_record(tracker, conflict_content.strip()))
                return True

            # 默认：直接记录，不进行跟踪
            MemoryConflict.create(
                conflict_content=conflict_content,
                create_time=time.time(),
                update_time=time.time(),
                answer="",
            )

            logger.info(f"记录冲突内容: {len(conflict_content)} 字符")
            return True

        except Exception as e:
            logger.error(f"记录冲突内容时出错: {e}")
            return False

    async def _follow_and_record(self, tracker: QuestionTracker, original_question: str) -> None:
        """
        后台任务：跟踪问题是否被解答，并写入数据库。
        """
        try:
            max_duration = 30 * 60  # 30 分钟
            max_messages = 100      # 最多 100 条消息
            poll_interval = 2.0     # 秒
            logger.info(f"开始跟踪问题: {original_question}")
            while tracker.active:
                now_ts = time.time()
                # 终止条件：时长达到上限
                if now_ts - tracker.start_time >= max_duration:
                    logger.info("问题跟踪达到30分钟上限，判定为未解答")
                    break

                # 统计最近一段是否有新消息（不过滤机器人，过滤命令）
                recent_msgs = get_raw_msg_by_timestamp_with_chat(
                    chat_id=tracker.chat_id,
                    timestamp_start=tracker.last_read_time,
                    timestamp_end=now_ts,
                    limit=30,
                    limit_mode="latest",
                    filter_bot=False,
                    filter_command=True,
                )

                if len(recent_msgs) > 0:
                    tracker.last_read_time = now_ts

                    # 统计从开始到现在的总消息数（用于触发100条上限）
                    all_msgs = get_raw_msg_by_timestamp_with_chat(
                        chat_id=tracker.chat_id,
                        timestamp_start=tracker.start_time,
                        timestamp_end=now_ts,
                        limit=0,
                        limit_mode="latest",
                        filter_bot=False,
                        filter_command=True,
                    )

                    # 构建可读聊天文本
                    chat_text = build_readable_messages(
                        all_msgs,
                        replace_bot_name=True,
                        timestamp_mode="relative",
                        read_mark=0.0,
                        truncate=False,
                        show_actions=False,
                        show_pic=False,
                        remove_emoji_stickers=True,
                    )

                    # 让小模型判断是否有答案
                    answered, answer_text = await tracker.judge_answer(chat_text)
                    if answered:
                        logger.info("问题已得到解答，结束跟踪并写入答案")
                        tracker.stop()
                        MemoryConflict.create(
                            conflict_content=tracker.question,
                            create_time=tracker.start_time,
                            update_time=time.time(),
                            answer=answer_text or "",
                        )
                        return

                    if len(all_msgs) >= max_messages:
                        logger.info("问题跟踪达到100条消息上限，判定为未解答")
                        break

                # 无新消息时稍作等待
                await asyncio.sleep(poll_interval)

            # 未获取到答案，仅存储问题
            MemoryConflict.create(
                conflict_content=original_question,
                create_time=time.time(),
                update_time=time.time(),
                answer="",
            )
            logger.info(f"记录冲突内容(未解答): {len(original_question)} 字符")
        except Exception as e:
            logger.error(f"后台问题跟踪任务异常: {e}")

    async def record_memory_merge_conflict(self, part2_content: str) -> bool:
        """
        记录记忆整合过程中的冲突内容（part2）

        Args:
            part2_content: 冲突内容（part2）

        Returns:
            bool: 是否成功记录
        """
        if not part2_content or part2_content.strip() == "":
            return False

        return await self.record_conflict(part2_content)

    async def get_all_conflicts(self) -> list:
        """
        获取所有冲突记录

        Returns:
            list: 冲突记录列表
        """
        try:
            conflicts = list(MemoryConflict.select())
            return conflicts
        except Exception as e:
            logger.error(f"获取冲突记录时出错: {e}")
            return []

    async def get_conflict_count(self) -> int:
        """
        获取冲突记录数量

        Returns:
            int: 记录数量
        """
        try:
            return MemoryConflict.select().count()
        except Exception as e:
            logger.error(f"获取冲突记录数量时出错: {e}")
            return 0

# 全局冲突追踪器实例
global_conflict_tracker = ConflictTracker()
import time
from src.common.logger import get_logger
from src.common.database.database_model import MemoryConflict
from src.llm_models.utils_model import LLMRequest
from src.config.config import model_config
from src.memory_system.memory_utils import parse_md_json

logger = get_logger("conflict_tracker")

class ConflictTracker:
    """
    记忆整合冲突追踪器

    用于记录和存储记忆整合过程中的冲突内容
    """
    def __init__(self):
        self.LLMRequest_tracker = LLMRequest(
            model_set=model_config.model_task_config.utils,
            request_type="conflict_tracker",
        )
        
    async def record_conflict(self, conflict_content: str, context: str = "", chat_id: str = "") -> bool:
        """
        记录冲突内容

        Args:
            conflict_content: 冲突内容
            context: 上下文
            chat_id: 聊天ID

        Returns:
            bool: 是否成功记录
        """
        try:
            if not conflict_content or conflict_content.strip() == "":
                return False

            # 直接记录，不进行跟踪
            MemoryConflict.create(
                conflict_content=conflict_content,
                create_time=time.time(),
                update_time=time.time(),
                answer="",
                chat_id=chat_id,
            )

            logger.info(f"记录冲突内容: {len(conflict_content)} 字符")
            return True

        except Exception as e:
            logger.error(f"记录冲突内容时出错: {e}")
            return False

    async def add_or_update_conflict(
        self,
        conflict_content: str,
        create_time: float,
        update_time: float,
        answer: str = "",
        context: str = "",
        chat_id: str = None
    ) -> bool:
        """
        根据conflict_content匹配数据库内容，如果找到相同的就更新update_time和answer，
        如果没有相同的，就新建一条保存全部内容
        """
        try:
            # 尝试根据conflict_content查找现有记录
            existing_conflict = MemoryConflict.get_or_none(
                MemoryConflict.conflict_content == conflict_content,
                MemoryConflict.chat_id == chat_id
            )
            
            if existing_conflict:
                # 如果找到相同的conflict_content，更新update_time和answer
                existing_conflict.update_time = update_time
                existing_conflict.answer = answer
                existing_conflict.save()
                return True
            else:
                # 如果没有找到相同的，创建新记录
                MemoryConflict.create(
                    conflict_content=conflict_content,
                    create_time=create_time,
                    update_time=update_time,
                    answer=answer,
                    context=context,
                    chat_id=chat_id,
                )
                return True
        except Exception as e:
            # 记录错误并返回False
            logger.error(f"添加或更新冲突记录时出错: {e}")
            return False

    async def record_memory_merge_conflict(self, part2_content: str, chat_id: str = None) -> bool:
        """
        记录记忆整合过程中的冲突内容（part2）

        Args:
            part2_content: 冲突内容（part2）

        Returns:
            bool: 是否成功记录
        """
        if not part2_content or part2_content.strip() == "":
            return False

        prompt = f"""以下是一段有冲突的信息，请你根据这些信息总结出几个具体的提问:
冲突信息：
{part2_content}

要求：
1.提问必须具体，明确
2.提问最好涉及指向明确的事物，而不是代称
3.如果缺少上下文，不要强行提问，可以忽略
4.请忽略涉及违法，暴力，色情，政治等敏感话题的内容

请用json格式输出，不要输出其他内容，仅输出提问理由和具体提的提问:
**示例**
// 理由文本
```json
{{
    "question":"提问",
}}
```
```json
{{
    "question":"提问"
}}
```
...提问数量在1-3个之间，不要重复，现在请输出："""

        question_response, (reasoning_content, model_name, tool_calls) = await self.LLMRequest_tracker.generate_response_async(prompt)
            
        # 解析JSON响应
        questions, reasoning_content = parse_md_json(question_response)   

        print(prompt)
        print(question_response)

        for question in questions:
            await self.record_conflict(
                conflict_content=question["question"], 
                context=reasoning_content, 
                chat_id=chat_id,
            )
        return True

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

    async def delete_conflict(self, conflict_content: str, chat_id: str) -> bool:
        """
        删除指定的冲突记录

        Args:
            conflict_content: 冲突内容
            chat_id: 聊天ID

        Returns:
            bool: 是否成功删除
        """
        try:
            conflict = MemoryConflict.get_or_none(
                MemoryConflict.conflict_content == conflict_content,
                MemoryConflict.chat_id == chat_id
            )
            
            if conflict:
                conflict.delete_instance()
                logger.info(f"已删除冲突记录: {conflict_content}")
                return True
            else:
                logger.warning(f"未找到要删除的冲突记录: {conflict_content}")
                return False
        except Exception as e:
            logger.error(f"删除冲突记录时出错: {e}")
            return False

# 全局冲突追踪器实例
global_conflict_tracker = ConflictTracker()
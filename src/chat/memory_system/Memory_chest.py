
from src.llm_models.utils_model import LLMRequest
from src.config.config import model_config
from src.common.database.database_model import MemoryChest as MemoryChestModel
from src.common.logger import get_logger
from src.config.config import global_config
from src.plugin_system.apis.message_api import build_readable_messages
import time
from src.plugin_system.apis.message_api import get_raw_msg_by_timestamp_with_chat

logger = get_logger("memory_chest")

class MemoryChest:
    def __init__(self):
        
        self.LLMRequest = LLMRequest(
            model_set=model_config.model_task_config.utils_small,
            request_type="memory_chest",
        )
        
        self.LLMRequest_build = LLMRequest(
            model_set=model_config.model_task_config.utils,
            request_type="memory_chest_build",
        )
        
        self.memory_build_threshold = 30
        self.memory_size_limit = 800
  
        self.running_content_list = {}  # {chat_id: {"content": running_content, "last_update_time": timestamp}}
        self.fetched_memory_list = []  # [(chat_id, (question, answer, timestamp)), ...]

    async def build_running_content(self, chat_id: str = None) -> str:
        """
        构建记忆仓库的运行内容

        Args:
            message_str: 消息内容
            chat_id: 聊天ID，用于提取对应的运行内容

        Returns:
            str: 构建后的运行内容
        """
        # 检查是否需要更新：上次更新时间和现在时间的消息数量大于30
        if chat_id not in self.running_content_list:
            self.running_content_list[chat_id] = {
                "content": "",
                "last_update_time": time.time()
            }
        
        should_update = True
        if chat_id and chat_id in self.running_content_list:
            last_update_time = self.running_content_list[chat_id]["last_update_time"]
            current_time = time.time()
            # 使用message_api获取消息数量
            message_list =  get_raw_msg_by_timestamp_with_chat(
                timestamp_start=last_update_time,
                timestamp_end=current_time,
                chat_id=chat_id,
                limit=global_config.chat.max_context_size * 2,
            )
            
            new_messages_count = len(message_list)
            should_update = new_messages_count > self.memory_build_threshold
            logger.info(f"chat_id {chat_id} 自上次更新后有 {new_messages_count} 条新消息，{'需要' if should_update else '不需要'}更新")


        if should_update:
            # 如果有chat_id，先提取对应的running_content
            message_str = build_readable_messages(
                message_list,
                replace_bot_name=True,
                timestamp_mode="relative",
                read_mark=0.0,
                show_actions=True,
            )
            
            
            current_running_content = ""
            if chat_id and chat_id in self.running_content_list:
                current_running_content = self.running_content_list[chat_id]["content"]

            prompt = f"""
以下是你的记忆内容：
{current_running_content}

请将下面的新聊天记录内的有用的信息，添加到你的记忆中
请主要关注概念和知识，而不是聊天的琐事
如果有表情包，仅在意表情包对上下文的影响，不要在意表情包本身
如果有图片，尽在意内容，不要在意图片的名称和编号
记忆为一段纯文本，逻辑清晰，指出事件，概念的含义，并说明关系
请输出添加后的记忆内容，不要输出其他内容：
{message_str}
"""

            if global_config.debug.show_prompt:
                logger.info(f"记忆仓库构建运行内容 prompt: {prompt}")
            else:
                logger.debug(f"记忆仓库构建运行内容 prompt: {prompt}")

            running_content, (reasoning_content, model_name, tool_calls) = await self.LLMRequest_build.generate_response_async(prompt)
            
            print(f"记忆仓库构建运行内容: {running_content}")

            # 如果有chat_id，更新对应的running_content
            if chat_id and running_content:
                self.running_content_list[chat_id] = {
                    "content": running_content,
                    "last_update_time": time.time()
                }

                # 检查running_content长度是否大于500
                if len(running_content) > self.memory_size_limit:
                    await self._save_to_database_and_clear(chat_id, running_content)

            
            
            return running_content
        
        
    

    def get_all_titles(self) -> list[str]:
        """
        获取记忆仓库中的所有标题

        Returns:
            list: 包含所有标题的列表
        """
        try:
            # 查询所有记忆记录的标题
            titles = []
            for memory in MemoryChestModel.select():
                if memory.title:
                    titles.append(memory.title)
            return titles
        except Exception as e:
            print(f"获取记忆标题时出错: {e}")
            return []
        
    async def get_answer_by_question(self, chat_id: str = "", question: str = "") -> str:
        """
        根据问题获取答案
        """
        title = await self.select_title_by_question(question)
        
        if not title:
            return ""
        
        for memory in MemoryChestModel.select():
            if memory.title == title:
                content =  memory.content
        
        prompt = f"""
{content}

请根据问题：{question}
在上方内容中，提取相关信息的原文并输出，请务必提取上面原文，不要输出其他内容：
"""

        if global_config.debug.show_prompt:
            logger.info(f"记忆仓库获取答案 prompt: {prompt}")
        else:
            logger.debug(f"记忆仓库获取答案 prompt: {prompt}")

        answer, (reasoning_content, model_name, tool_calls) = await self.LLMRequest.generate_response_async(prompt)
        
        
        logger.info(f"记忆仓库获取答案: {answer}")

        # 将问题和答案存到fetched_memory_list
        if chat_id and answer:
            self.fetched_memory_list.append((chat_id, (question, answer, time.time())))

            # 清理fetched_memory_list
            self._cleanup_fetched_memory_list()

        return answer

    def get_chat_memories_as_string(self, chat_id: str) -> str:
        """
        获取某个chat_id的所有记忆，并构建成字符串

        Args:
            chat_id: 聊天ID

        Returns:
            str: 格式化的记忆字符串，格式：问题：xxx,答案:xxxxx\n问题：xxx,答案:xxxxx\n...
        """
        try:
            memories = []

            # 从fetched_memory_list中获取该chat_id的所有记忆
            for cid, (question, answer, timestamp) in self.fetched_memory_list:
                if cid == chat_id:
                    memories.append(f"问题：{question},答案:{answer}")

            # 按时间戳排序（最新的在后面）
            memories.sort()

            # 用换行符连接所有记忆
            result = "\n".join(memories)

            logger.info(f"chat_id {chat_id} 共有 {len(memories)} 条记忆")
            return result

        except Exception as e:
            logger.error(f"获取chat_id {chat_id} 的记忆时出错: {e}")
            return ""


    async def select_title_by_question(self, question: str) -> str:
        """
        根据消息内容选择最匹配的标题

        Args:
            question: 问题

        Returns:
            str: 选择的标题
        """
        # 获取所有标题并构建格式化字符串
        titles = self.get_all_titles()
        formatted_titles = ""
        for title in titles:
            formatted_titles += f"{title}\n"

        prompt = f"""
所有主题：
{formatted_titles}

请根据以下问题，选择一个能够回答问题的主题：
问题：{question}
请你输出主题，不要输出其他内容，完整输出主题名：
"""

        if global_config.debug.show_prompt:
            logger.info(f"记忆仓库选择标题 prompt: {prompt}")
        else:
            logger.debug(f"记忆仓库选择标题 prompt: {prompt}")
            
            
        title, (reasoning_content, model_name, tool_calls) = await self.LLMRequest.generate_response_async(prompt)

        # 根据 title 获取 titles 里的对应项
        titles = self.get_all_titles()
        selected_title = None

        # 查找完全匹配的标题
        for t in titles:
            if t == title:
                selected_title = t
                break

                    
        logger.info(f"记忆仓库选择标题: {selected_title}")

        return selected_title

    def _cleanup_fetched_memory_list(self):
        """
        清理fetched_memory_list，移除超过10分钟的记忆和超过10条的最旧记忆
        """
        try:
            current_time = time.time()
            ten_minutes_ago = current_time - 600  # 10分钟 = 600秒

            # 移除超过10分钟的记忆
            self.fetched_memory_list = [
                (chat_id, (question, answer, timestamp))
                for chat_id, (question, answer, timestamp) in self.fetched_memory_list
                if timestamp > ten_minutes_ago
            ]

            # 如果记忆条数超过10条，移除最旧的5条
            if len(self.fetched_memory_list) > 10:
                # 按时间戳排序，移除最旧的5条
                self.fetched_memory_list.sort(key=lambda x: x[1][2])  # 按timestamp排序
                self.fetched_memory_list = self.fetched_memory_list[5:]  # 保留最新的5条

            logger.debug(f"fetched_memory_list清理后，当前有 {len(self.fetched_memory_list)} 条记忆")

        except Exception as e:
            logger.error(f"清理fetched_memory_list时出错: {e}")

    async def _save_to_database_and_clear(self, chat_id: str, content: str):
        """
        生成标题，保存到数据库，并清空对应chat_id的running_content

        Args:
            chat_id: 聊天ID
            content: 要保存的内容
        """
        try:
            # 生成标题
            title_prompt = f"""
请为以下内容生成一个描述全面的标题，要求描述内容的主要概念和事件：
{content}

请只输出标题，不要输出其他内容：
"""

            if global_config.debug.show_prompt:
                logger.info(f"记忆仓库生成标题 prompt: {title_prompt}")
            else:
                logger.debug(f"记忆仓库生成标题 prompt: {title_prompt}")

            title, (reasoning_content, model_name, tool_calls) = await self.LLMRequest_build.generate_response_async(title_prompt)

            if title:
                # 保存到数据库
                MemoryChestModel.create(
                    title=title.strip(),
                    content=content
                )
                logger.info(f"已保存记忆仓库内容，标题: {title.strip()}, chat_id: {chat_id}")

                # 清空对应chat_id的running_content
                if chat_id in self.running_content_list:
                    del self.running_content_list[chat_id]
                    logger.info(f"已清空chat_id {chat_id} 的running_content")
            else:
                logger.warning(f"生成标题失败，chat_id: {chat_id}")

        except Exception as e:
            logger.error(f"保存记忆仓库内容时出错: {e}")
    
    
global_memory_chest = MemoryChest()
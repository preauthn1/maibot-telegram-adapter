import asyncio
import json
import re
import time
import random

from src.llm_models.utils_model import LLMRequest
from src.config.config import model_config
from src.common.database.database_model import MemoryChest as MemoryChestModel
from src.common.logger import get_logger
from src.config.config import global_config
from src.plugin_system.apis.message_api import build_readable_messages
from src.plugin_system.apis.message_api import get_raw_msg_by_timestamp_with_chat
from json_repair import repair_json
from .memory_utils import (
    find_best_matching_memory,
    check_title_exists_fuzzy
)

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
        self.memory_size_limit = global_config.memory.max_memory_size
  
        self.running_content_list = {}  # {chat_id: {"content": running_content, "last_update_time": timestamp, "create_time": timestamp}}
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
                "last_update_time": time.time(),
                "create_time": time.time()
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
            time_diff_minutes = (current_time - last_update_time) / 60

            # 检查是否满足强制构建条件：超过15分钟且至少有5条新消息
            forced_update = time_diff_minutes > 15 and new_messages_count >= 5
            should_update = new_messages_count > self.memory_build_threshold or forced_update

            if forced_update:
                logger.info(f"chat_id {chat_id} 距离上次更新已 {time_diff_minutes:.1f} 分钟，有 {new_messages_count} 条新消息，强制构建")
            else:
                logger.info(f"chat_id {chat_id} 自上次更新后有 {new_messages_count} 条新消息，{'需要' if should_update else '不需要'}更新")


        if should_update:
            # 如果有chat_id，先提取对应的running_content
            message_str = build_readable_messages(
                message_list,
                replace_bot_name=True,
                timestamp_mode="relative",
                read_mark=0.0,
                show_actions=True,
                remove_emoji_stickers=True,
            )
            
            
            current_running_content = ""
            if chat_id and chat_id in self.running_content_list:
                current_running_content = self.running_content_list[chat_id]["content"]

            prompt = f"""
以下是你的记忆内容：
{current_running_content}

请将下面的新聊天记录内的有用的信息，添加到你的记忆中
请主要关注概念和知识，而不是聊天的琐事
重要！！你要关注的概念和知识必须是较为不常见的信息，或者时效性较强的信息！！
不要！！关注常见的只是，或者已经过时的信息！！
1.不要关注诸如某个用户做了什么，说了什么，不要关注某个用户的行为，而是关注其中的概念性信息
2.概念要求精确，不啰嗦，像科普读物或教育课本那样
3.如果有图片，请只关注图片和文本结合的知识和概念性内容
记忆为一段纯文本，逻辑清晰，指出概念的含义，并说明关系
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
                current_time = time.time()

                # 保留原有的create_time，如果没有则使用当前时间
                create_time = self.running_content_list[chat_id].get("create_time", current_time)

                self.running_content_list[chat_id] = {
                    "content": running_content,
                    "last_update_time": current_time,
                    "create_time": create_time
                }

                # 检查running_content长度是否大于500
                if len(running_content) > self.memory_size_limit:
                    await self._save_to_database_and_clear(chat_id, running_content)

                # 检查是否需要强制保存：create_time超过1800秒且内容大小达到max_memory_size的30%
                elif (current_time - create_time > 1800 and
                      len(running_content) >= self.memory_size_limit * 0.3):
                    logger.info(f"chat_id {chat_id} 内容创建时间已超过 {(current_time - create_time)/60:.1f} 分钟，"
                               f"内容大小 {len(running_content)} 达到限制的 {int(self.memory_size_limit * 0.3)} 字符，强制保存")
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
        logger.info(f"正在回忆问题答案: {question}")
        
        title = await self.select_title_by_question(question)
        
        if not title:
            return ""
        
        for memory in MemoryChestModel.select():
            if memory.title == title:
                content =  memory.content
                
        if random.random() < 0.5:        
            type = "要求原文能够较为全面的回答问题"
        else:
            type = "要求提取简短的内容"
            
        prompt = f"""
{content}

请根据问题：{question}
在上方内容中，提取相关信息的原文并输出，{type}
请务必提取上面原文，不要输出其他内容：
"""

        if global_config.debug.show_prompt:
            logger.info(f"记忆仓库获取答案 prompt: {prompt}")
        else:
            logger.debug(f"记忆仓库获取答案 prompt: {prompt}")

        answer, (reasoning_content, model_name, tool_calls) = await self.LLMRequest.generate_response_async(prompt)
        
        
        logger.info(f"记忆仓库对问题 “{question}” 获取答案: {answer}")

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

        # 使用模糊查找匹配标题
        best_match = find_best_matching_memory(title, similarity_threshold=0.8)
        if best_match:
            selected_title = best_match[0]  # 获取匹配的标题
            logger.info(f"记忆仓库选择标题: {selected_title} (相似度: {best_match[2]:.3f})")
        else:
            logger.warning(f"未找到相似度 >= 0.7 的标题匹配: {title}")
            selected_title = None

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
            title = ""
            title_prompt = f"""
请为以下内容生成一个描述全面的标题，要求描述内容的主要概念和事件：
{content}

标题不要分点，不要换行，不要输出其他内容
请只输出标题，不要输出其他内容：
"""

            if global_config.debug.show_prompt:
                logger.info(f"记忆仓库生成标题 prompt: {title_prompt}")
            else:
                logger.debug(f"记忆仓库生成标题 prompt: {title_prompt}")

            title, (reasoning_content, model_name, tool_calls) = await self.LLMRequest_build.generate_response_async(title_prompt)

            
            await asyncio.sleep(0.5)
            
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
    
    async def choose_merge_target(self, memory_title: str) -> list[str]:
        """
        选择与给定记忆标题相关的记忆目标
        
        Args:
            memory_title: 要匹配的记忆标题
            
        Returns:
            list[str]: 选中的记忆内容列表
        """
        try:
            all_titles = self.get_all_titles()
            content = ""
            for title in all_titles:
                content += f"{title}\n"
            
            prompt = f"""
所有记忆列表
{content}

请根据以上记忆列表，选择一个与"{memory_title}"相关的记忆，用json输出：
可以选择多个相关的记忆，但最多不超过5个
例如：
{{
    "selected_title": "选择的相关记忆标题"
}},
{{
    "selected_title": "选择的相关记忆标题"
}},
{{
    "selected_title": "选择的相关记忆标题"
}}
...
请输出JSON格式，不要输出其他内容：
"""
            if global_config.debug.show_prompt:
                logger.info(f"选择合并目标 prompt: {prompt}")
            else:
                logger.debug(f"选择合并目标 prompt: {prompt}")
                
            merge_target_response, (reasoning_content, model_name, tool_calls) = await self.LLMRequest_build.generate_response_async(prompt)
            
            # 解析JSON响应
            selected_titles = self._parse_merge_target_json(merge_target_response)
            
            # 根据标题查找对应的内容
            selected_contents = self._get_memories_by_titles(selected_titles)
            
            logger.info(f"选择合并目标结果: {len(selected_contents)} 条记忆:{selected_titles}")
            return selected_contents
            
        except Exception as e:
            logger.error(f"选择合并目标时出错: {e}")
            return []
    
    def _get_memories_by_titles(self, titles: list[str]) -> list[str]:
        """
        根据标题列表查找对应的记忆内容
        
        Args:
            titles: 记忆标题列表
            
        Returns:
            list[str]: 记忆内容列表
        """
        try:
            contents = []
            for title in titles:
                if not title or not title.strip():
                    continue
                    
                # 使用模糊查找匹配记忆
                try:
                    best_match = find_best_matching_memory(title.strip(), similarity_threshold=0.8)
                    if best_match:
                        contents.append(best_match[1])  # best_match[1] 是 content
                        logger.debug(f"找到记忆: {best_match[0]} (相似度: {best_match[2]:.3f})")
                    else:
                        logger.warning(f"未找到相似度 >= 0.8 的标题匹配: '{title}'")
                except Exception as e:
                    logger.error(f"查找标题 '{title}' 的记忆时出错: {e}")
                    continue
            
            logger.info(f"成功找到 {len(contents)} 条记忆内容")
            return contents
            
        except Exception as e:
            logger.error(f"根据标题查找记忆时出错: {e}")
            return []
    
    def _parse_merge_target_json(self, json_text: str) -> list[str]:
        """
        解析choose_merge_target生成的JSON响应
        
        Args:
            json_text: LLM返回的JSON文本
            
        Returns:
            list[str]: 解析出的记忆标题列表
        """
        try:
            # 清理JSON文本，移除可能的额外内容
            repaired_content = repair_json(json_text)
            
            # 尝试直接解析JSON
            try:
                parsed_data = json.loads(repaired_content)
                if isinstance(parsed_data, list):
                    # 如果是列表，提取selected_title字段
                    titles = []
                    for item in parsed_data:
                        if isinstance(item, dict) and "selected_title" in item:
                            titles.append(item["selected_title"])
                    return titles
                elif isinstance(parsed_data, dict) and "selected_title" in parsed_data:
                    # 如果是单个对象
                    return [parsed_data["selected_title"]]
            except json.JSONDecodeError:
                pass
            
            # 如果直接解析失败，尝试提取JSON对象
            # 查找所有包含selected_title的JSON对象
            pattern = r'\{[^}]*"selected_title"[^}]*\}'
            matches = re.findall(pattern, repaired_content)
            
            titles = []
            for match in matches:
                try:
                    obj = json.loads(match)
                    if "selected_title" in obj:
                        titles.append(obj["selected_title"])
                except json.JSONDecodeError:
                    continue
            
            if titles:
                return titles
            
            logger.warning(f"无法解析JSON响应: {json_text[:200]}...")
            return []
            
        except Exception as e:
            logger.error(f"解析合并目标JSON时出错: {e}")
            return []
            
    async def merge_memory(self,memory_list: list[str]) -> tuple[str, str]:
        """
        合并记忆
        """
        try:
            content = ""
            for memory in memory_list:
                content += f"{memory}\n"
            
            prompt = f"""
以下是多段记忆内容，请将它们合并成一段记忆：
{content}

请将下面的多段记忆内容，合并成一段记忆
请主要关注概念和知识，而不是聊天的琐事
重要！！你要关注的概念和知识必须是较为不常见的信息，或者时效性较强的信息！！
不要！！关注常见的只是，或者已经过时的信息！！
1.不要关注诸如某个用户做了什么，说了什么，不要关注某个用户的行为，而是关注其中的概念性信息
2.概念要求精确，不啰嗦，像科普读物或教育课本那样
3.如果有图片，请只关注图片和文本结合的知识和概念性内容
4.如果记忆中有冲突的地方，可以进行整合。如果无法整合，需要在此处标注存在冲突的不同信息
记忆为一段纯文本，逻辑清晰，指出概念的含义，并说明关系
请输出合并的记忆内容，不要输出其他内容：
"""

            if global_config.debug.show_prompt:
                logger.info(f"合并记忆 prompt: {prompt}")
            else:
                logger.debug(f"合并记忆 prompt: {prompt}")

            merged_memory, (reasoning_content, model_name, tool_calls) = await self.LLMRequest_build.generate_response_async(prompt)

            # 生成合并后的标题
            merged_title = await self._generate_title_for_merged_memory(merged_memory)
            
            # 保存合并后的记忆到数据库
            MemoryChestModel.create(
                title=merged_title,
                content=merged_memory
            )
            
            logger.info(f"合并记忆已保存: {merged_title}")
            
            return merged_title, merged_memory
        except Exception as e:
            logger.error(f"合并记忆时出错: {e}")
            return "", ""
    
    async def _generate_title_for_merged_memory(self, merged_content: str) -> str:
        """
        为合并后的记忆生成标题
        
        Args:
            merged_content: 合并后的记忆内容
            
        Returns:
            str: 生成的标题
        """
        try:
            prompt = f"""
请为以下内容生成一个描述全面的标题，要求描述内容的主要概念和事件：
{merged_content}

标题不要分点，不要换行，不要输出其他内容，不要浮夸，以白话简洁的风格输出标题
请只输出标题，不要输出其他内容：
"""
            
            if global_config.debug.show_prompt:
                logger.info(f"生成合并记忆标题 prompt: {prompt}")
            else:
                logger.debug(f"生成合并记忆标题 prompt: {prompt}")
            
            title_response, (reasoning_content, model_name, tool_calls) = await self.LLMRequest.generate_response_async(prompt)
            
            # 清理标题，移除可能的引号或多余字符
            title = title_response.strip().strip('"').strip("'").strip()
            
            if title:
                # 检查是否存在相似标题
                if check_title_exists_fuzzy(title, similarity_threshold=0.9):
                    logger.warning(f"生成的标题 '{title}' 与现有标题相似，使用时间戳后缀")
                    title = f"{title}_{int(time.time())}"
                
                logger.info(f"生成合并记忆标题: {title}")
                return title
            else:
                logger.warning("生成合并记忆标题失败，使用默认标题")
                return f"合并记忆_{int(time.time())}"
                
        except Exception as e:
            logger.error(f"生成合并记忆标题时出错: {e}")
            return f"合并记忆_{int(time.time())}"
    
    
global_memory_chest = MemoryChest()
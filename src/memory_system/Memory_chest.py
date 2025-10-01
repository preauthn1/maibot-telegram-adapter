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
        
        self.memory_build_threshold = 20
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
                logger.debug(f"chat_id {chat_id} 距离上次更新已 {time_diff_minutes:.1f} 分钟，有 {new_messages_count} 条新消息，强制构建")
            else:
                logger.debug(f"chat_id {chat_id} 自上次更新后有 {new_messages_count} 条新消息，{'需要' if should_update else '不需要'}更新")


        if should_update:
            # 如果有chat_id，先提取对应的running_content
            message_str = build_readable_messages(
                message_list,
                replace_bot_name=True,
                timestamp_mode="relative",
                read_mark=0.0,
                show_actions=False,
                remove_emoji_stickers=True,
            )
            
            
            current_running_content = ""
            if chat_id and chat_id in self.running_content_list:
                current_running_content = self.running_content_list[chat_id]["content"]

            # 随机从格式示例列表中选取若干行用于提示
            format_candidates = [
                "[概念] 是 [概念的含义(简短描述，不超过十个字)]",
                "[概念] 不是 [对概念的负面含义(简短描述，不超过十个字)]",
                "[概念1] 与 [概念2] 是 [概念1和概念2的关联(简短描述，不超过二十个字)]",
                "[概念1] 包含 [概念2] 和 [概念3]",
                "[概念1] 属于 [概念2]",
                "[概念1] 的例子是 [例子1] 和 [例子2]",
                "[概念] 的特征是 [特征1]、[特征2]",
                "[概念1] 导致 [概念2]",
                "[概念1] 需要 [条件1] 和 [条件2]",
                "[概念1] 的用途是 [用途1] 和 [用途2]",
                "[概念1] 与 [概念2] 的区别是 [区别点]",
                "[概念] 的别名是 [别名]",
                "[概念1] 包括但不限于 [概念2]、[概念3]",
                "[概念] 的反义是 [反义概念]",
                "[概念] 的组成有 [部分1]、[部分2]",
                "[概念] 出现于 [时间或场景]",
                "[概念] 的方法有 [方法1]、[方法2]",
            ]

            selected_count = random.randint(3, 6)
            selected_lines = random.sample(format_candidates, selected_count)
            format_section = "\n".join(selected_lines) + "\n......(不要包含中括号)"

            prompt = f"""
以下是你的记忆内容和新的聊天记录，请你将他们整合和修改：
记忆内容：
<memory_content>
{current_running_content}
</memory_content>

<聊天记录>
{message_str}
</聊天记录>
聊天记录中可能包含有效信息，也可能信息密度很低，请你根据聊天记录中的信息，修改<part1>中的内容与<part2>中的内容
--------------------------------
请将上面的新聊天记录内的有用的信息进行整合到现有的记忆中
请主要关注概念和知识或者时效性较强的信息！！，而不是聊天的琐事
1.不要关注诸如某个用户做了什么，说了什么，不要关注某个用户的行为，而是关注其中的概念性信息
2.概念要求精确，不啰嗦，像科普读物或教育课本那样
3.如果有图片，请只关注图片和文本结合的知识和概念性内容
4.记忆为一段纯文本，逻辑清晰，指出概念的含义，并说明关系

 记忆内容的格式，你必须仿照下面的格式，但不一定全部使用:
{format_section}

请仿照上述格式输出，每个知识点一句话。输出成一段平文本
现在请你输出,不要输出其他内容，注意一定要直白，白话，口语化不要浮夸，修辞。：
"""

            if global_config.debug.show_prompt:
                logger.info(f"记忆仓库构建运行内容 prompt: {prompt}")
            else:
                logger.debug(f"记忆仓库构建运行内容 prompt: {prompt}")

            running_content, (reasoning_content, model_name, tool_calls) = await self.LLMRequest_build.generate_response_async(prompt)

            print(f"prompt: {prompt}\n记忆仓库构建运行内容: {running_content}")

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

                # 检查running_content长度是否大于限制
                if len(running_content) > self.memory_size_limit:
                    await self._save_to_database_and_clear(chat_id, running_content)

                # 检查是否需要强制保存：create_time超过1800秒且内容大小达到max_memory_size的30%
                elif (current_time - create_time > 1800 and
                      len(running_content) >= self.memory_size_limit * 0.3):
                    logger.info(f"chat_id {chat_id} 内容创建时间已超过 {(current_time - create_time)/60:.1f} 分钟，"
                               f"内容大小 {len(running_content)} 达到限制的 {int(self.memory_size_limit * 0.3)} 字符，强制保存")
                    await self._save_to_database_and_clear(chat_id, running_content)


            return running_content
        
        
    

    def get_all_titles(self, exclude_locked: bool = False) -> list[str]:
        """
        获取记忆仓库中的所有标题

        Args:
            exclude_locked: 是否排除锁定的记忆，默认为 False

        Returns:
            list: 包含所有标题的列表
        """
        try:
            # 查询所有记忆记录的标题
            titles = []
            for memory in MemoryChestModel.select():
                if memory.title:
                    # 如果 exclude_locked 为 True 且记忆已锁定，则跳过
                    if exclude_locked and memory.locked:
                        continue
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
目标文段：
{content}

你现在需要从目标文段中找出合适的信息来回答问题：{question}
请务必从目标文段中提取相关信息的**原文**并输出，{type}
如果没有原文能够回答问题，输出"无有效信息"即可，不要输出其他内容：
"""

        if global_config.debug.show_prompt:
            logger.info(f"记忆仓库获取答案 prompt: {prompt}")
        else:
            logger.debug(f"记忆仓库获取答案 prompt: {prompt}")

        answer, (reasoning_content, model_name, tool_calls) = await self.LLMRequest.generate_response_async(prompt)
        
        if "无有效" in answer or "无有效信息" in answer or "无信息" in answer:
            logger.info(f"没有能够回答{question}的记忆")
            return ""
        
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

            # logger.info(f"chat_id {chat_id} 共有 {len(memories)} 条记忆")
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
        # 获取所有标题并构建格式化字符串（排除锁定的记忆）
        titles = self.get_all_titles(exclude_locked=True)
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
            all_titles = self.get_all_titles(exclude_locked=True)
            content = ""
            display_index = 1
            for title in all_titles:
                # 剔除掉输入的 memory_title 本身
                if title and title.strip() == (memory_title or "").strip():
                    continue
                content += f"{display_index}. {title}\n"
                display_index += 1
            
            prompt = f"""
所有记忆列表
{content}

请根据以上记忆列表，选择一个与"{memory_title}"相关的记忆，用json输出：
如果没有相关记忆，输出:
{{
    "selected_title": ""
}}
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
注意：请返回原始标题本身作为 selected_title，不要包含前面的序号或多余字符。
请输出JSON格式，不要输出其他内容：
"""

            logger.info(f"选择合并目标 prompt: {prompt}")

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
            return selected_titles,selected_contents
            
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
                        # 检查记忆是否被锁定
                        memory_title = best_match[0]
                        memory_content = best_match[1]

                        # 查询数据库中的锁定状态
                        for memory in MemoryChestModel.select():
                            if memory.title == memory_title and memory.locked:
                                logger.warning(f"记忆 '{memory_title}' 已锁定，跳过合并")
                                continue

                        contents.append(memory_content)
                        logger.debug(f"找到记忆: {memory_title} (相似度: {best_match[2]:.3f})")
                    else:
                        logger.warning(f"未找到相似度 >= 0.8 的标题匹配: '{title}'")
                except Exception as e:
                    logger.error(f"查找标题 '{title}' 的记忆时出错: {e}")
                    continue

            # logger.info(f"成功找到 {len(contents)} 条记忆内容")
            return contents

        except Exception as e:
            logger.error(f"根据标题查找记忆时出错: {e}")
            return []
    
    def _parse_merged_parts(self, merged_response: str) -> tuple[str, str]:
        """
        解析合并记忆的part1和part2内容

        Args:
            merged_response: LLM返回的合并记忆响应

        Returns:
            tuple[str, str]: (part1_content, part2_content)
        """
        try:
            # 使用正则表达式提取part1和part2内容
            import re

            # 提取part1内容
            part1_pattern = r'<part1>(.*?)</part1>'
            part1_match = re.search(part1_pattern, merged_response, re.DOTALL)
            part1_content = part1_match.group(1).strip() if part1_match else ""

            # 提取part2内容
            part2_pattern = r'<part2>(.*?)</part2>'
            part2_match = re.search(part2_pattern, merged_response, re.DOTALL)
            part2_content = part2_match.group(1).strip() if part2_match else ""

            # 检查是否包含none或None（不区分大小写）
            def is_none_content(content: str) -> bool:
                if not content:
                    return True
                # 检查是否只包含"none"或"None"（不区分大小写）
                return re.match(r'^\s*none\s*$', content, re.IGNORECASE) is not None

            # 如果包含none，则设置为空字符串
            if is_none_content(part1_content):
                part1_content = ""
                logger.info("part1内容为none，设置为空")

            if is_none_content(part2_content):
                part2_content = ""
                logger.info("part2内容为none，设置为空")

            return part1_content, part2_content

        except Exception as e:
            logger.error(f"解析合并记忆part1/part2时出错: {e}")
            return "", ""

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
                            value = item.get("selected_title", "")
                            if isinstance(value, str) and value.strip():
                                titles.append(value)
                    return titles
                elif isinstance(parsed_data, dict) and "selected_title" in parsed_data:
                    # 如果是单个对象
                    value = parsed_data.get("selected_title", "")
                    if isinstance(value, str) and value.strip():
                        return [value]
                    else:
                        # 空字符串表示没有相关记忆
                        return []
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
                        value = obj.get("selected_title", "")
                        if isinstance(value, str) and value.strip():
                            titles.append(value)
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
以下是多段记忆内容，请将它们进行整合和修改：
{content}
--------------------------------
请将上面的多段记忆内容，合并成两部分内容，第一部分是可以整合，不冲突的概念和知识，第二部分是相互有冲突的概念和知识
请主要关注概念和知识，而不是聊天的琐事
重要！！你要关注的概念和知识必须是较为不常见的信息，或者时效性较强的信息！！
不要！！关注常见的只是，或者已经过时的信息！！
1.不要关注诸如某个用户做了什么，说了什么，不要关注某个用户的行为，而是关注其中的概念性信息
2.概念要求精确，不啰嗦，像科普读物或教育课本那样
3.如果有图片，请只关注图片和文本结合的知识和概念性内容
4.记忆为一段纯文本，逻辑清晰，指出概念的含义，并说明关系
**第一部分**
1.如果两个概念在描述同一件事情，且相互之间逻辑不冲突（请你严格判断），且相互之间没有矛盾，请将它们整合成一个概念，并输出到第一部分
2.如果某个概念在时间上更新了另一个概念，请用新概念更新就概念来整合，并输出到第一部分
3.如果没有可整合的概念，请你输出none
**第二部分**
1.如果记忆中有无法整合的地方，例如概念不一致，有逻辑上的冲突，请你输出到第二部分
2.如果两个概念在描述同一件事情，但相互之间逻辑冲突，请将它们输出到第二部分
3.如果没有无法整合的概念，请你输出none

**输出格式要求**
请你按以下格式输出：
<part1>
第一部分内容，整合后的概念，如果第一部分为none，请输出none
</part1>
<part2>
第二部分内容，无法整合，冲突的概念，如果第二部分为none，请输出none  
</part2>
不要输出其他内容，现在请你输出,不要输出其他内容，注意一定要直白，白话，口语化不要浮夸，修辞。：
"""

            if global_config.debug.show_prompt:
                logger.info(f"合并记忆 prompt: {prompt}")
            else:
                logger.debug(f"合并记忆 prompt: {prompt}")

            merged_memory, (reasoning_content, model_name, tool_calls) = await self.LLMRequest_build.generate_response_async(prompt)

            # 解析part1和part2
            part1_content, part2_content = self._parse_merged_parts(merged_memory)

            # 处理part2：独立记录冲突内容（无论part1是否为空）
            if part2_content and part2_content.strip() != "none":
                logger.info(f"合并记忆part2记录冲突内容: {len(part2_content)} 字符")
                # 导入冲突追踪器
                from src.curiousity.questions import global_conflict_tracker
                # 记录冲突到数据库
                await global_conflict_tracker.record_memory_merge_conflict(part2_content)

            # 处理part1：生成标题并保存
            if part1_content and part1_content.strip() != "none":
                merged_title = await self._generate_title_for_merged_memory(part1_content)

                # 保存part1到数据库
                MemoryChestModel.create(
                    title=merged_title,
                    content=part1_content
                )

                logger.info(f"合并记忆part1已保存: {merged_title}")

                return merged_title, part1_content
            else:
                logger.warning("合并记忆part1为空，跳过保存")
                return "", ""
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
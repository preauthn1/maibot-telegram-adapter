from src.plugins.models.utils_model import LLM_request
from src.plugins.config.config import global_config
from src.plugins.chat.chat_stream import ChatStream
from src.plugins.memory_system.Hippocampus import HippocampusManager
from src.common.database import db
import time
import json
from src.common.logger import get_module_logger
from src.plugins.chat.utils import get_embedding
from typing import Union
logger = get_module_logger("tool_use")


class ToolUser:
    def __init__(self):
        self.llm_model_tool = LLM_request(
            model=global_config.llm_heartflow, temperature=0.2, max_tokens=1000, request_type="tool_use"
        )

    async def _build_tool_prompt(self, message_txt:str, sender_name:str, chat_stream:ChatStream):
        """构建工具使用的提示词
        
        Args:
            message_txt: 用户消息文本
            sender_name: 发送者名称
            chat_stream: 聊天流对象
            
        Returns:
            str: 构建好的提示词
        """
        from src.plugins.config.config import global_config
        
        new_messages = list(
            db.messages.find({"chat_id": chat_stream.stream_id, "time": {"$gt": time.time()}})
            .sort("time", 1)
            .limit(15)
        )
        new_messages_str = ""
        for msg in new_messages:
            if "detailed_plain_text" in msg:
                new_messages_str += f"{msg['detailed_plain_text']}"

        # 这些信息应该从调用者传入，而不是从self获取
        bot_name = global_config.BOT_NICKNAME
        prompt = ""
        prompt += "你正在思考如何回复群里的消息。\n"
        prompt += f"你注意到{sender_name}刚刚说：{message_txt}\n"
        prompt += f"注意你就是{bot_name}，{bot_name}指的就是你。"
        prompt += "你现在需要对群里的聊天内容进行回复，现在请你思考，你是否需要额外的信息，或者一些工具来帮你回复，比如回忆或者搜寻已有的知识，或者了解你现在正在做什么，请输出你需要的工具，或者你需要的额外信息。"
        
        return prompt
    
    def _define_tools(self):
        """定义可用的工具列表
        
        Returns:
            list: 工具定义列表
        """
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search_knowledge",
                    "description": "从知识库中搜索相关信息",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "搜索查询关键词"
                            },
                            "threshold": {
                                "type": "number",
                                "description": "相似度阈值，0.0到1.0之间"
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_memory",
                    "description": "从记忆系统中获取相关记忆",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "要查询的相关文本"
                            },
                            "max_memory_num": {
                                "type": "integer",
                                "description": "最大返回记忆数量"
                            }
                        },
                        "required": ["text"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_current_task",
                    "description": "获取当前正在做的事情/最近的任务",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "num": {
                                "type": "integer",
                                "description": "要获取的任务数量"
                            },
                            "time_info": {
                                "type": "boolean",
                                "description": "是否包含时间信息"
                            }
                        },
                        "required": []
                    }
                }
            }
        ]
        return tools
    
    async def _execute_tool_call(self, tool_call, message_txt:str):
        """执行特定的工具调用
        
        Args:
            tool_call: 工具调用对象
            message_txt: 原始消息文本
            
        Returns:
            dict: 工具调用结果
        """
        try:
            function_name = tool_call["function"]["name"]
            function_args = json.loads(tool_call["function"]["arguments"])
            
            if function_name == "search_knowledge":
                return await self._execute_search_knowledge(tool_call, function_args, message_txt)
            elif function_name == "get_memory":
                return await self._execute_get_memory(tool_call, function_args, message_txt)
            elif function_name == "get_current_task":
                return await self._execute_get_current_task(tool_call, function_args)
            
            logger.warning(f"未知工具名称: {function_name}")
            return None
        except Exception as e:
            logger.error(f"执行工具调用时发生错误: {str(e)}")
            return None
    
    async def _execute_search_knowledge(self, tool_call, function_args, message_txt:str):
        """执行知识库搜索工具
        
        Args:
            tool_call: 工具调用对象
            function_args: 工具参数
            message_txt: 原始消息文本
            
        Returns:
            dict: 工具调用结果
        """
        try:
            query = function_args.get("query", message_txt)
            threshold = function_args.get("threshold", 0.4)
            
            # 调用知识库搜索
            embedding = await get_embedding(query, request_type="info_retrieval")
            if embedding:
                knowledge_info = self.get_info_from_db(embedding, limit=3, threshold=threshold)
                return {
                    "tool_call_id": tool_call["id"],
                    "role": "tool",
                    "name": "search_knowledge",
                    "content": f"知识库搜索结果: {knowledge_info}"
                }
            return None
        except Exception as e:
            logger.error(f"知识库搜索工具执行失败: {str(e)}")
            return None
    
    async def _execute_get_memory(self, tool_call, function_args, message_txt:str):
        """执行记忆获取工具
        
        Args:
            tool_call: 工具调用对象
            function_args: 工具参数
            message_txt: 原始消息文本
            
        Returns:
            dict: 工具调用结果
        """
        try:
            text = function_args.get("text", message_txt)
            max_memory_num = function_args.get("max_memory_num", 2)
            
            # 调用记忆系统
            related_memory = await HippocampusManager.get_instance().get_memory_from_text(
                text=text, 
                max_memory_num=max_memory_num, 
                max_memory_length=2, 
                max_depth=3, 
                fast_retrieval=False
            )
            
            memory_info = ""
            if related_memory:
                for memory in related_memory:
                    memory_info += memory[1] + "\n"
            
            return {
                "tool_call_id": tool_call["id"],
                "role": "tool",
                "name": "get_memory",
                "content": f"记忆系统结果: {memory_info if memory_info else '没有找到相关记忆'}"
            }
        except Exception as e:
            logger.error(f"记忆获取工具执行失败: {str(e)}")
            return None
    
    async def _execute_get_current_task(self, tool_call, function_args):
        """执行获取当前任务工具
        
        Args:
            tool_call: 工具调用对象
            function_args: 工具参数
            
        Returns:
            dict: 工具调用结果
        """
        try:
            from src.plugins.schedule.schedule_generator import bot_schedule
            
            # 获取参数，如果没有提供则使用默认值
            num = function_args.get("num", 1)
            time_info = function_args.get("time_info", False)
            
            # 调用日程系统获取当前任务
            current_task = bot_schedule.get_current_num_task(num=num, time_info=time_info)
            
            # 格式化返回结果
            if current_task:
                task_info = current_task
            else:
                task_info = "当前没有正在进行的任务"
                
            return {
                "tool_call_id": tool_call["id"],
                "role": "tool",
                "name": "get_current_task",
                "content": f"当前任务信息: {task_info}"
            }
        except Exception as e:
            logger.error(f"获取当前任务工具执行失败: {str(e)}")
            return None
    
    async def use_tool(self, message_txt:str, sender_name:str, chat_stream:ChatStream):
        """使用工具辅助思考，判断是否需要额外信息
        
        Args:
            message_txt: 用户消息文本
            sender_name: 发送者名称
            chat_stream: 聊天流对象
            
        Returns:
            dict: 工具使用结果
        """
        try:
            # 构建提示词
            prompt = await self._build_tool_prompt(message_txt, sender_name, chat_stream)
            
            # 定义可用工具
            tools = self._define_tools()
            
            # 使用llm_model_tool发送带工具定义的请求
            payload = {
                "model": self.llm_model_tool.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": global_config.max_response_length,
                "tools": tools,
                "temperature": 0.2
            }
            
            logger.debug(f"发送工具调用请求，模型: {self.llm_model_tool.model_name}")
            # 发送请求获取模型是否需要调用工具
            response = await self.llm_model_tool._execute_request(
                endpoint="/chat/completions", 
                payload=payload,
                prompt=prompt
            )
            
            # 根据返回值数量判断是否有工具调用
            if len(response) == 3:
                content, reasoning_content, tool_calls = response
                logger.info(f"工具思考: {tool_calls}")
                
                # 检查响应中工具调用是否有效
                if not tool_calls:
                    logger.info("模型返回了空的tool_calls列表")
                    return {"used_tools": False, "thinking": self.current_mind}
                    
                logger.info(f"模型请求调用{len(tool_calls)}个工具")
                tool_results = []
                collected_info = ""
                
                # 执行所有工具调用
                for tool_call in tool_calls:
                    result = await self._execute_tool_call(tool_call, message_txt)
                    if result:
                        tool_results.append(result)
                        # 将工具结果添加到收集的信息中
                        collected_info += f"\n{result['name']}返回结果: {result['content']}\n"
                
                # 如果有工具结果，直接返回收集的信息
                if collected_info:
                    logger.info(f"工具调用收集到信息: {collected_info}")
                    return {
                        "used_tools": True,
                        "collected_info": collected_info,
                        "thinking": self.current_mind  # 保持原始思考不变
                    }
            else:
                # 没有工具调用
                content, reasoning_content = response
                logger.info("模型没有请求调用任何工具")
            
            # 如果没有工具调用或处理失败，直接返回原始思考
            return {
                "used_tools": False,
                "thinking": self.current_mind
            }
            
        except Exception as e:
            logger.error(f"工具调用过程中出错: {str(e)}")
            return {
                "used_tools": False,
                "error": str(e),
                "thinking": self.current_mind
            }



    async def get_prompt_info(self, message: str, threshold: float):
        start_time = time.time()
        related_info = ""
        logger.debug(f"获取知识库内容，元消息：{message[:30]}...，消息长度: {len(message)}")

        # 1. 先从LLM获取主题，类似于记忆系统的做法
        topics = []
        # try:
        #     # 先尝试使用记忆系统的方法获取主题
        #     hippocampus = HippocampusManager.get_instance()._hippocampus
        #     topic_num = min(5, max(1, int(len(message) * 0.1)))
        #     topics_response = await hippocampus.llm_topic_judge.generate_response(hippocampus.find_topic_llm(message, topic_num))

        #     # 提取关键词
        #     topics = re.findall(r"<([^>]+)>", topics_response[0])
        #     if not topics:
        #         topics = []
        #     else:
        #         topics = [
        #             topic.strip()
        #             for topic in ",".join(topics).replace("，", ",").replace("、", ",").replace(" ", ",").split(",")
        #             if topic.strip()
        #         ]

        #     logger.info(f"从LLM提取的主题: {', '.join(topics)}")
        # except Exception as e:
        #     logger.error(f"从LLM提取主题失败: {str(e)}")
        #     # 如果LLM提取失败，使用jieba分词提取关键词作为备选
        #     words = jieba.cut(message)
        #     topics = [word for word in words if len(word) > 1][:5]
        #     logger.info(f"使用jieba提取的主题: {', '.join(topics)}")

        # 如果无法提取到主题，直接使用整个消息
        if not topics:
            logger.debug("未能提取到任何主题，使用整个消息进行查询")
            embedding = await get_embedding(message, request_type="info_retrieval")
            if not embedding:
                logger.error("获取消息嵌入向量失败")
                return ""

            related_info = self.get_info_from_db(embedding, limit=3, threshold=threshold)
            logger.info(f"知识库检索完成，总耗时: {time.time() - start_time:.3f}秒")
            return related_info, {}

        # 2. 对每个主题进行知识库查询
        logger.info(f"开始处理{len(topics)}个主题的知识库查询")

        # 优化：批量获取嵌入向量，减少API调用
        embeddings = {}
        topics_batch = [topic for topic in topics if len(topic) > 0]
        if message:  # 确保消息非空
            topics_batch.append(message)

        # 批量获取嵌入向量
        embed_start_time = time.time()
        for text in topics_batch:
            if not text or len(text.strip()) == 0:
                continue

            try:
                embedding = await get_embedding(text, request_type="info_retrieval")
                if embedding:
                    embeddings[text] = embedding
                else:
                    logger.warning(f"获取'{text}'的嵌入向量失败")
            except Exception as e:
                logger.error(f"获取'{text}'的嵌入向量时发生错误: {str(e)}")

        logger.info(f"批量获取嵌入向量完成，耗时: {time.time() - embed_start_time:.3f}秒")

        if not embeddings:
            logger.error("所有嵌入向量获取失败")
            return ""

        # 3. 对每个主题进行知识库查询
        all_results = []
        query_start_time = time.time()

        # 首先添加原始消息的查询结果
        if message in embeddings:
            original_results = self.get_info_from_db(embeddings[message], limit=3, threshold=threshold, return_raw=True)
            if original_results:
                for result in original_results:
                    result["topic"] = "原始消息"
                all_results.extend(original_results)
                logger.info(f"原始消息查询到{len(original_results)}条结果")

        # 然后添加每个主题的查询结果
        for topic in topics:
            if not topic or topic not in embeddings:
                continue

            try:
                topic_results = self.get_info_from_db(embeddings[topic], limit=3, threshold=threshold, return_raw=True)
                if topic_results:
                    # 添加主题标记
                    for result in topic_results:
                        result["topic"] = topic
                    all_results.extend(topic_results)
                    logger.info(f"主题'{topic}'查询到{len(topic_results)}条结果")
            except Exception as e:
                logger.error(f"查询主题'{topic}'时发生错误: {str(e)}")

        logger.info(f"知识库查询完成，耗时: {time.time() - query_start_time:.3f}秒，共获取{len(all_results)}条结果")

        # 4. 去重和过滤
        process_start_time = time.time()
        unique_contents = set()
        filtered_results = []
        for result in all_results:
            content = result["content"]
            if content not in unique_contents:
                unique_contents.add(content)
                filtered_results.append(result)

        # 5. 按相似度排序
        filtered_results.sort(key=lambda x: x["similarity"], reverse=True)

        # 6. 限制总数量（最多10条）
        filtered_results = filtered_results[:10]
        logger.info(
            f"结果处理完成，耗时: {time.time() - process_start_time:.3f}秒，过滤后剩余{len(filtered_results)}条结果"
        )

        # 7. 格式化输出
        if filtered_results:
            format_start_time = time.time()
            grouped_results = {}
            for result in filtered_results:
                topic = result["topic"]
                if topic not in grouped_results:
                    grouped_results[topic] = []
                grouped_results[topic].append(result)

            # 按主题组织输出
            for topic, results in grouped_results.items():
                related_info += f"【主题: {topic}】\n"
                for _i, result in enumerate(results, 1):
                    _similarity = result["similarity"]
                    content = result["content"].strip()
                    # 调试：为内容添加序号和相似度信息
                    # related_info += f"{i}. [{similarity:.2f}] {content}\n"
                    related_info += f"{content}\n"
                related_info += "\n"

            logger.info(f"格式化输出完成，耗时: {time.time() - format_start_time:.3f}秒")

        logger.info(f"知识库检索总耗时: {time.time() - start_time:.3f}秒")
        return related_info, grouped_results

    def get_info_from_db(
        self, query_embedding: list, limit: int = 1, threshold: float = 0.5, return_raw: bool = False
    ) -> Union[str, list]:
        if not query_embedding:
            return "" if not return_raw else []
        # 使用余弦相似度计算
        pipeline = [
            {
                "$addFields": {
                    "dotProduct": {
                        "$reduce": {
                            "input": {"$range": [0, {"$size": "$embedding"}]},
                            "initialValue": 0,
                            "in": {
                                "$add": [
                                    "$$value",
                                    {
                                        "$multiply": [
                                            {"$arrayElemAt": ["$embedding", "$$this"]},
                                            {"$arrayElemAt": [query_embedding, "$$this"]},
                                        ]
                                    },
                                ]
                            },
                        }
                    },
                    "magnitude1": {
                        "$sqrt": {
                            "$reduce": {
                                "input": "$embedding",
                                "initialValue": 0,
                                "in": {"$add": ["$$value", {"$multiply": ["$$this", "$$this"]}]},
                            }
                        }
                    },
                    "magnitude2": {
                        "$sqrt": {
                            "$reduce": {
                                "input": query_embedding,
                                "initialValue": 0,
                                "in": {"$add": ["$$value", {"$multiply": ["$$this", "$$this"]}]},
                            }
                        }
                    },
                }
            },
            {"$addFields": {"similarity": {"$divide": ["$dotProduct", {"$multiply": ["$magnitude1", "$magnitude2"]}]}}},
            {
                "$match": {
                    "similarity": {"$gte": threshold}  # 只保留相似度大于等于阈值的结果
                }
            },
            {"$sort": {"similarity": -1}},
            {"$limit": limit},
            {"$project": {"content": 1, "similarity": 1}},
        ]

        results = list(db.knowledges.aggregate(pipeline))
        logger.debug(f"知识库查询结果数量: {len(results)}")

        if not results:
            return "" if not return_raw else []

        if return_raw:
            return results
        else:
            # 返回所有找到的内容，用换行分隔
            return "\n".join(str(result["content"]) for result in results)
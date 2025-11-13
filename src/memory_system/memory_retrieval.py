import time
import json
import re
import random
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from src.common.logger import get_logger
from src.config.config import global_config, model_config
from src.chat.utils.prompt_builder import Prompt, global_prompt_manager
from src.plugin_system.apis import llm_api
from src.common.database.database_model import ThinkingBack
from json_repair import repair_json
from src.memory_system.retrieval_tools import get_tool_registry, init_all_tools

logger = get_logger("memory_retrieval")


def init_memory_retrieval_prompt():
    """初始化记忆检索相关的 prompt 模板和工具"""
    # 首先注册所有工具
    init_all_tools()

    # 第一步：问题生成prompt
    Prompt(
        """
你的名字是{bot_name}。现在是{time_now}。
群里正在进行的聊天内容：
{chat_history}

{recent_query_history}

现在，{sender}发送了内容:{target_message},你想要回复ta。
请仔细分析聊天内容，考虑以下几点：
1. 对话中是否提到了过去发生的事情、人物、事件或信息
2. 是否有需要回忆的内容（比如"之前说过"、"上次"、"以前"等）
3. 是否有需要查找历史信息的问题
4. 是否有问题可以搜集信息帮助你聊天

重要提示：
- 如果"最近已查询的问题和结果"中已经包含了类似的问题，请避免重复生成相同或相似的问题
- 如果之前已经查询过某个问题但未找到答案，可以尝试用不同的方式提问或更具体的问题
- 如果之前已经查询过某个问题并找到了答案，可以直接参考已有结果，不需要重复查询

如果你认为需要从记忆中检索信息来回答，请根据上下文提出一个或多个具体的问题。
问题格式示例：
- "xxx在前几天干了什么"
- "xxx是什么"
- "xxxx和xxx的关系是什么"
- "xxx在某个时间点发生了什么"

请输出JSON格式的问题数组。如果不需要检索记忆，则输出空数组[]。

输出格式示例：
```json
[
  "张三在前几天干了什么",
  "自然选择是什么",
  "李四和王五的关系是什么"
]
```

请只输出JSON数组，不要输出其他内容：
""",
        name="memory_retrieval_question_prompt",
    )

    # 第二步：ReAct Agent prompt（工具描述会在运行时动态生成）
    Prompt(
        """
你的名字是{bot_name}。现在是{time_now}。
你正在参与聊天，你需要搜集信息来回答问题，帮助你参与聊天。
你需要通过思考(Think)、行动(Action)、观察(Observation)的循环来回答问题。

当前问题：{question}
已收集的信息：
{collected_info}

你可以使用以下工具来查询信息：
{tools_description}

请按照以下格式输出你的思考过程：
```json
{{
  "thought": "你的思考过程，分析当前情况，决定下一步行动",
  "actions": [
    {{
      "action_type": {action_types_list},
      "action_params": {{参数名: 参数值}} 或 null
    }}
  ]
}}
```

重要说明：
- 你可以在一次迭代中执行多个查询，将多个action放在actions数组中
- 如果只需要执行一个查询，actions数组中只包含一个action即可
- 如果已经收集到足够的信息可以回答问题，请设置actions为包含一个action_type为"final_answer"的数组，并在action_params中提供答案（例如：{{"answer": "你的答案内容"}}）。除非明确找到答案，否则不要设置为final_answer。
- 如果经过多次查询后，确认无法找到相关信息或答案，请设置actions为包含一个action_type为"no_answer"的数组，并在action_params中说明原因（例如：{{"reason": "无法找到的原因"}}）。

请只输出JSON，不要输出其他内容：
""",
        name="memory_retrieval_react_prompt",
    )


def _parse_react_response(response: str) -> Optional[Dict[str, Any]]:
    """解析ReAct Agent的响应

    Args:
        response: LLM返回的响应

    Returns:
        Dict[str, Any]: 解析后的动作信息，如果解析失败返回None
        格式: {"thought": str, "actions": List[Dict[str, Any]]}
        每个action格式: {"action_type": str, "action_params": dict}
    """
    try:
        # 尝试提取JSON（可能包含在```json代码块中）
        json_pattern = r"```json\s*(.*?)\s*```"
        matches = re.findall(json_pattern, response, re.DOTALL)

        if matches:
            json_str = matches[0]
        else:
            # 尝试直接解析整个响应
            json_str = response.strip()

        # 修复可能的JSON错误
        repaired_json = repair_json(json_str)

        # 解析JSON
        action_info = json.loads(repaired_json)

        if not isinstance(action_info, dict):
            logger.warning(f"解析的JSON不是对象格式: {action_info}")
            return None

        # 确保actions字段存在且为列表
        if "actions" not in action_info:
            logger.warning(f"响应中缺少actions字段: {action_info}")
            return None

        if not isinstance(action_info["actions"], list):
            logger.warning(f"actions字段不是数组格式: {action_info['actions']}")
            return None

        # 确保actions不为空
        if len(action_info["actions"]) == 0:
            logger.warning("actions数组为空")
            return None

        return action_info

    except Exception as e:
        logger.error(f"解析ReAct响应失败: {e}, 响应内容: {response[:200]}...")
        return None


async def _react_agent_solve_question(
    question: str, chat_id: str, max_iterations: int = 5, timeout: float = 30.0
) -> Tuple[bool, str, List[Dict[str, Any]], bool]:
    """使用ReAct架构的Agent来解决问题

    Args:
        question: 要回答的问题
        chat_id: 聊天ID
        max_iterations: 最大迭代次数
        timeout: 超时时间（秒）

    Returns:
        Tuple[bool, str, List[Dict[str, Any]], bool]: (是否找到答案, 答案内容, 思考步骤列表, 是否超时)
    """
    start_time = time.time()
    collected_info = ""
    thinking_steps = []
    is_timeout = False

    for iteration in range(max_iterations):
        # 检查超时
        if time.time() - start_time > timeout:
            logger.warning(f"ReAct Agent超时，已迭代{iteration}次")
            is_timeout = True
            break

        logger.info(f"ReAct Agent 第 {iteration + 1} 次迭代，问题: {question}")
        logger.info(f"ReAct Agent 已收集信息: {collected_info if collected_info else '暂无信息'}")

        # 获取工具注册器
        tool_registry = get_tool_registry()

        # 获取bot_name
        bot_name = global_config.bot.nickname

        # 获取当前时间
        time_now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        # 构建prompt（动态生成工具描述）
        prompt = await global_prompt_manager.format_prompt(
            "memory_retrieval_react_prompt",
            bot_name=bot_name,
            time_now=time_now,
            question=question,
            collected_info=collected_info if collected_info else "暂无信息",
            tools_description=tool_registry.get_tools_description(),
            action_types_list=tool_registry.get_action_types_list(),
        )

        logger.info(f"ReAct Agent 第 {iteration + 1} 次迭代 Prompt: {prompt}")

        # 调用LLM
        success, response, reasoning_content, model_name = await llm_api.generate_with_model(
            prompt,
            model_config=model_config.model_task_config.tool_use,
            request_type="memory.react",
        )

        logger.info(f"ReAct Agent 第 {iteration + 1} 次迭代 LLM响应: {response}")
        logger.info(f"ReAct Agent 第 {iteration + 1} 次迭代 LLM推理: {reasoning_content}")
        logger.info(f"ReAct Agent 第 {iteration + 1} 次迭代 LLM模型: {model_name}")

        if not success:
            logger.error(f"ReAct Agent LLM调用失败: {response}")
            break

        # 解析响应
        action_info = _parse_react_response(response)
        if not action_info:
            logger.warning(f"无法解析ReAct响应，迭代{iteration + 1}")
            break

        thought = action_info.get("thought", "")
        actions = action_info.get("actions", [])

        logger.info(f"ReAct Agent 第 {iteration + 1} 次迭代 思考: {thought}")
        logger.info(f"ReAct Agent 第 {iteration + 1} 次迭代 动作数量: {len(actions)}")

        # 记录思考步骤（包含所有actions）
        step = {"iteration": iteration + 1, "thought": thought, "actions": actions, "observations": []}

        # 检查是否有final_answer或no_answer
        for action in actions:
            action_type = action.get("action_type", "")
            action_params = action.get("action_params", {})
            if action_type == "final_answer":
                # Agent认为已经找到答案
                # 从action_params中获取答案，如果没有则使用thought作为后备
                answer = action_params.get("answer", thought) if isinstance(action_params, dict) else thought
                step["observations"] = ["找到答案"]
                thinking_steps.append(step)
                logger.info(f"ReAct Agent 第 {iteration + 1} 次迭代 找到最终答案: {answer}")
                return True, answer, thinking_steps, False
            elif action_type == "no_answer":
                # Agent确认无法找到答案
                # 从action_params中获取原因，如果没有则使用thought作为后备
                answer = action_params.get("reason", thought) if isinstance(action_params, dict) else thought
                step["observations"] = ["确认无法找到答案"]
                thinking_steps.append(step)
                logger.info(f"ReAct Agent 第 {iteration + 1} 次迭代 确认无法找到答案: {answer}")
                return False, answer, thinking_steps, False

        # 并行执行所有工具
        tool_registry = get_tool_registry()
        tool_tasks = []

        for i, action in enumerate(actions):
            action_type = action.get("action_type", "")
            action_params = action.get("action_params", {})

            logger.info(
                f"ReAct Agent 第 {iteration + 1} 次迭代 动作 {i + 1}/{len(actions)}: {action_type}({action_params})"
            )

            tool = tool_registry.get_tool(action_type)

            if tool:
                # 准备工具参数（需要添加chat_id如果工具需要）
                tool_params = action_params.copy()

                # 如果工具函数签名需要chat_id，添加它
                import inspect

                sig = inspect.signature(tool.execute_func)
                if "chat_id" in sig.parameters:
                    tool_params["chat_id"] = chat_id

                # 创建异步任务
                async def execute_single_tool(tool_instance, params, act_type, act_params, iter_num):
                    try:
                        observation = await tool_instance.execute(**params)
                        param_str = ", ".join([f"{k}={v}" for k, v in act_params.items()])
                        return f"查询{act_type}({param_str})的结果：{observation}"
                    except Exception as e:
                        error_msg = f"工具执行失败: {str(e)}"
                        logger.error(f"ReAct Agent 第 {iter_num + 1} 次迭代 动作 {act_type} {error_msg}")
                        return f"查询{act_type}失败: {error_msg}"

                tool_tasks.append(execute_single_tool(tool, tool_params, action_type, action_params, iteration))
            else:
                error_msg = f"未知的工具类型: {action_type}"
                logger.warning(f"ReAct Agent 第 {iteration + 1} 次迭代 动作 {i + 1}/{len(actions)} {error_msg}")
                tool_tasks.append(asyncio.create_task(asyncio.sleep(0, result=f"查询{action_type}失败: {error_msg}")))

        # 并行执行所有工具
        if tool_tasks:
            observations = await asyncio.gather(*tool_tasks, return_exceptions=True)

            # 处理执行结果
            for i, observation in enumerate(observations):
                if isinstance(observation, Exception):
                    observation = f"工具执行异常: {str(observation)}"
                    logger.error(f"ReAct Agent 第 {iteration + 1} 次迭代 动作 {i + 1} 执行异常: {observation}")

                step["observations"].append(observation)
                collected_info += f"\n{observation}\n"
                logger.info(f"ReAct Agent 第 {iteration + 1} 次迭代 动作 {i + 1} 执行结果: {observation}")

        thinking_steps.append(step)

    # 达到最大迭代次数或超时，但Agent没有明确返回final_answer
    # 迭代超时应该直接视为no_answer，而不是使用已有信息
    # 只有Agent明确返回final_answer时，才认为找到了答案
    if collected_info:
        logger.warning(
            f"ReAct Agent达到最大迭代次数或超时，但未明确返回final_answer。已收集信息: {collected_info[:100]}..."
        )
    if is_timeout:
        logger.warning("ReAct Agent超时，直接视为no_answer")
    else:
        logger.warning("ReAct Agent达到最大迭代次数，直接视为no_answer")
    return False, "未找到相关信息", thinking_steps, is_timeout


def _get_recent_query_history(chat_id: str, time_window_seconds: float = 300.0) -> str:
    """获取最近一段时间内的查询历史

    Args:
        chat_id: 聊天ID
        time_window_seconds: 时间窗口（秒），默认10分钟

    Returns:
        str: 格式化的查询历史字符串
    """
    try:
        current_time = time.time()
        start_time = current_time - time_window_seconds

        # 查询最近时间窗口内的记录，按更新时间倒序
        records = (
            ThinkingBack.select()
            .where((ThinkingBack.chat_id == chat_id) & (ThinkingBack.update_time >= start_time))
            .order_by(ThinkingBack.update_time.desc())
            .limit(5)  # 最多返回5条最近的记录
        )

        if not records.exists():
            return ""

        history_lines = []
        history_lines.append("最近已查询的问题和结果：")

        for record in records:
            status = "✓ 已找到答案" if record.found_answer else "✗ 未找到答案"
            answer_preview = ""
            # 只有找到答案时才显示答案内容
            if record.found_answer and record.answer:
                # 截取答案前100字符
                answer_preview = record.answer[:100]
                if len(record.answer) > 100:
                    answer_preview += "..."

            history_lines.append(f"- 问题：{record.question}")
            history_lines.append(f"  状态：{status}")
            if answer_preview:
                history_lines.append(f"  答案：{answer_preview}")
            history_lines.append("")  # 空行分隔

        return "\n".join(history_lines)

    except Exception as e:
        logger.error(f"获取查询历史失败: {e}")
        return ""


def _get_cached_memories(chat_id: str, time_window_seconds: float = 300.0) -> List[str]:
    """获取最近一段时间内缓存的记忆（只返回找到答案的记录）

    Args:
        chat_id: 聊天ID
        time_window_seconds: 时间窗口（秒），默认300秒（5分钟）

    Returns:
        List[str]: 格式化的记忆列表，每个元素格式为 "问题：xxx\n答案：xxx"
    """
    try:
        current_time = time.time()
        start_time = current_time - time_window_seconds

        # 查询最近时间窗口内找到答案的记录，按更新时间倒序
        records = (
            ThinkingBack.select()
            .where(
                (ThinkingBack.chat_id == chat_id)
                & (ThinkingBack.update_time >= start_time)
                & (ThinkingBack.found_answer == 1)
            )
            .order_by(ThinkingBack.update_time.desc())
            .limit(5)  # 最多返回5条最近的记录
        )

        if not records.exists():
            return []

        cached_memories = []
        for record in records:
            if record.answer:
                cached_memories.append(f"问题：{record.question}\n答案：{record.answer}")

        return cached_memories

    except Exception as e:
        logger.error(f"获取缓存记忆失败: {e}")
        return []


def _query_thinking_back(chat_id: str, question: str) -> Optional[Tuple[bool, str]]:
    """从thinking_back数据库中查询是否有现成的答案

    Args:
        chat_id: 聊天ID
        question: 问题

    Returns:
        Optional[Tuple[bool, str]]: 如果找到记录，返回(found_answer, answer)，否则返回None
            found_answer: 是否找到答案（True表示found_answer=1，False表示found_answer=0）
            answer: 答案内容
    """
    try:
        # 查询相同chat_id和问题的所有记录（包括found_answer为0和1的）
        # 按更新时间倒序，获取最新的记录
        records = (
            ThinkingBack.select()
            .where((ThinkingBack.chat_id == chat_id) & (ThinkingBack.question == question))
            .order_by(ThinkingBack.update_time.desc())
            .limit(1)
        )

        if records.exists():
            record = records.get()
            found_answer = bool(record.found_answer)
            answer = record.answer or ""
            logger.info(f"在thinking_back中找到记录，问题: {question[:50]}...，found_answer: {found_answer}")
            return found_answer, answer

        return None

    except Exception as e:
        logger.error(f"查询thinking_back失败: {e}")
        return None


def _store_thinking_back(
    chat_id: str, question: str, context: str, found_answer: bool, answer: str, thinking_steps: List[Dict[str, Any]]
) -> None:
    """存储或更新思考过程到数据库（如果已存在则更新，否则创建）

    Args:
        chat_id: 聊天ID
        question: 问题
        context: 上下文信息
        found_answer: 是否找到答案
        answer: 答案内容
        thinking_steps: 思考步骤列表
    """
    try:
        now = time.time()

        # 先查询是否已存在相同chat_id和问题的记录
        existing = (
            ThinkingBack.select()
            .where((ThinkingBack.chat_id == chat_id) & (ThinkingBack.question == question))
            .order_by(ThinkingBack.update_time.desc())
            .limit(1)
        )

        if existing.exists():
            # 更新现有记录
            record = existing.get()
            record.context = context
            record.found_answer = found_answer
            record.answer = answer
            record.thinking_steps = json.dumps(thinking_steps, ensure_ascii=False)
            record.update_time = now
            record.save()
            logger.info(f"已更新思考过程到数据库，问题: {question[:50]}...")
        else:
            # 创建新记录
            ThinkingBack.create(
                chat_id=chat_id,
                question=question,
                context=context,
                found_answer=found_answer,
                answer=answer,
                thinking_steps=json.dumps(thinking_steps, ensure_ascii=False),
                create_time=now,
                update_time=now,
            )
            logger.info(f"已创建思考过程到数据库，问题: {question[:50]}...")
    except Exception as e:
        logger.error(f"存储思考过程失败: {e}")


async def _process_single_question(question: str, chat_id: str, context: str) -> Optional[str]:
    """处理单个问题的查询（包含缓存检查逻辑）

    Args:
        question: 要查询的问题
        chat_id: 聊天ID
        context: 上下文信息

    Returns:
        Optional[str]: 如果找到答案，返回格式化的结果字符串，否则返回None
    """
    logger.info(f"开始处理问题: {question}")

    # 先检查thinking_back数据库中是否有现成答案
    cached_result = _query_thinking_back(chat_id, question)
    should_requery = False

    if cached_result:
        cached_found_answer, cached_answer = cached_result

        # 根据found_answer的值决定是否重新查询
        if cached_found_answer:  # found_answer == 1 (True)
            # found_answer == 1：20%概率重新查询
            if random.random() < 0.2:
                should_requery = True
                logger.info(f"found_answer=1，触发20%概率重新查询，问题: {question[:50]}...")
        else:  # found_answer == 0 (False)
            # found_answer == 0：40%概率重新查询
            if random.random() < 0.4:
                should_requery = True
                logger.info(f"found_answer=0，触发40%概率重新查询，问题: {question[:50]}...")

        # 如果不需要重新查询，使用缓存答案
        if not should_requery:
            if cached_answer:
                logger.info(f"从thinking_back缓存中获取答案，问题: {question[:50]}...")
                return f"问题：{question}\n答案：{cached_answer}"
            else:
                # 缓存中没有答案，需要查询
                should_requery = True

    # 如果没有缓存答案或需要重新查询，使用ReAct Agent查询
    if not cached_result or should_requery:
        if should_requery:
            logger.info(f"概率触发重新查询，使用ReAct Agent查询，问题: {question[:50]}...")
        else:
            logger.info(f"未找到缓存答案，使用ReAct Agent查询，问题: {question[:50]}...")

        found_answer, answer, thinking_steps, is_timeout = await _react_agent_solve_question(
            question=question, chat_id=chat_id, max_iterations=5, timeout=120.0
        )

        # 存储到数据库（超时时不存储）
        if not is_timeout:
            _store_thinking_back(
                chat_id=chat_id,
                question=question,
                context=context,
                found_answer=found_answer,
                answer=answer,
                thinking_steps=thinking_steps,
            )
        else:
            logger.info(f"ReAct Agent超时，不存储到数据库，问题: {question[:50]}...")

        if found_answer and answer:
            return f"问题：{question}\n答案：{answer}"

    return None


async def build_memory_retrieval_prompt(
    message: str,
    sender: str,
    target: str,
    chat_stream,
    tool_executor,
) -> str:
    """构建记忆检索提示
    使用两段式查询：第一步生成问题，第二步使用ReAct Agent查询答案

    Args:
        message: 聊天历史记录
        sender: 发送者名称
        target: 目标消息内容
        chat_stream: 聊天流对象
        tool_executor: 工具执行器（保留参数以兼容接口）

    Returns:
        str: 记忆检索结果字符串
    """
    start_time = time.time()

    logger.info(f"检测是否需要回忆，元消息：{message[:30]}...，消息长度: {len(message)}")
    try:
        time_now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        bot_name = global_config.bot.nickname
        chat_id = chat_stream.stream_id

        # 获取最近查询历史（最近1小时内的查询）
        recent_query_history = _get_recent_query_history(chat_id, time_window_seconds=300.0)
        if not recent_query_history:
            recent_query_history = "最近没有查询记录。"

        # 第一步：生成问题
        question_prompt = await global_prompt_manager.format_prompt(
            "memory_retrieval_question_prompt",
            bot_name=bot_name,
            time_now=time_now,
            chat_history=message,
            recent_query_history=recent_query_history,
            sender=sender,
            target_message=target,
        )

        success, response, reasoning_content, model_name = await llm_api.generate_with_model(
            question_prompt,
            model_config=model_config.model_task_config.tool_use,
            request_type="memory.question",
        )

        logger.info(f"记忆检索问题生成提示词: {question_prompt}")
        logger.info(f"记忆检索问题生成响应: {response}")

        if not success:
            logger.error(f"LLM生成问题失败: {response}")
            return ""

        # 解析问题列表
        questions = _parse_questions_json(response)

        # 获取缓存的记忆（与question时使用相同的时间窗口和数量限制）
        cached_memories = _get_cached_memories(chat_id, time_window_seconds=300.0)

        if not questions:
            logger.debug("模型认为不需要检索记忆或解析失败")
            # 即使没有当次查询，也返回缓存的记忆
            if cached_memories:
                retrieved_memory = "\n\n".join(cached_memories)
                end_time = time.time()
                logger.info(
                    f"无当次查询，返回缓存记忆，耗时: {(end_time - start_time):.3f}秒，包含 {len(cached_memories)} 条缓存记忆"
                )
                return f"你回忆起了以下信息：\n{retrieved_memory}\n如果与回复内容相关，可以参考这些回忆的信息。\n"
            else:
                return ""

        logger.info(f"解析到 {len(questions)} 个问题: {questions}")

        # 第二步：并行处理所有问题（固定使用5次迭代/120秒超时）
        logger.info(f"问题数量: {len(questions)}，固定设置最大迭代次数: 5，超时时间: 120秒")

        # 并行处理所有问题
        question_tasks = [
            _process_single_question(question=question, chat_id=chat_id, context=message) for question in questions
        ]

        # 并行执行所有查询任务
        results = await asyncio.gather(*question_tasks, return_exceptions=True)

        # 收集所有有效结果
        all_results = []
        current_questions = set()  # 用于去重，避免缓存和当次查询重复
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"处理问题 '{questions[i]}' 时发生异常: {result}")
            elif result is not None:
                all_results.append(result)
                # 提取问题用于去重
                if result.startswith("问题："):
                    question = result.split("\n")[0].replace("问题：", "").strip()
                    current_questions.add(question)

        # 将缓存的记忆添加到结果中（排除当次查询已包含的问题，避免重复）
        for cached_memory in cached_memories:
            if cached_memory.startswith("问题："):
                question = cached_memory.split("\n")[0].replace("问题：", "").strip()
                # 只有当次查询中没有相同问题时，才添加缓存记忆
                if question not in current_questions:
                    all_results.append(cached_memory)
                    logger.debug(f"添加缓存记忆: {question[:50]}...")

        end_time = time.time()

        if all_results:
            retrieved_memory = "\n\n".join(all_results)
            logger.info(
                f"记忆检索成功，耗时: {(end_time - start_time):.3f}秒，包含 {len(all_results)} 条记忆（含缓存）"
            )
            return f"你回忆起了以下信息：\n{retrieved_memory}\n如果与回复内容相关，可以参考这些回忆的信息。\n"
        else:
            logger.debug("所有问题均未找到答案，且无缓存记忆")
            return ""

    except Exception as e:
        logger.error(f"记忆检索时发生异常: {str(e)}")
        return ""


def _parse_questions_json(response: str) -> List[str]:
    """解析问题JSON

    Args:
        response: LLM返回的响应

    Returns:
        List[str]: 问题列表
    """
    try:
        # 尝试提取JSON（可能包含在```json代码块中）
        json_pattern = r"```json\s*(.*?)\s*```"
        matches = re.findall(json_pattern, response, re.DOTALL)

        if matches:
            json_str = matches[0]
        else:
            # 尝试直接解析整个响应
            json_str = response.strip()

        # 修复可能的JSON错误
        repaired_json = repair_json(json_str)

        # 解析JSON
        questions = json.loads(repaired_json)

        if not isinstance(questions, list):
            logger.warning(f"解析的JSON不是数组格式: {questions}")
            return []

        # 确保所有元素都是字符串
        questions = [q for q in questions if isinstance(q, str) and q.strip()]

        return questions

    except Exception as e:
        logger.error(f"解析问题JSON失败: {e}, 响应内容: {response[:200]}...")
        return []

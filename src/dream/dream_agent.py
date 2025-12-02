import asyncio
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from src.common.logger import get_logger
from src.config.config import global_config, model_config
from src.common.database.database_model import ChatHistory
from src.chat.utils.prompt_builder import Prompt, global_prompt_manager
from src.llm_models.payload_content.message import MessageBuilder, RoleType, Message
from src.plugin_system.apis import llm_api
from src.llm_models.utils_model import LLMRequest


logger = get_logger("dream_agent")

# 初始化 utils 模型用于生成梦境总结
_dream_summary_model: Optional[LLMRequest] = None


def _get_dream_summary_model() -> LLMRequest:
    """获取用于生成梦境总结的 utils 模型实例"""
    global _dream_summary_model
    if _dream_summary_model is None:
        _dream_summary_model = LLMRequest(
            model_set=model_config.model_task_config.utils,
            request_type="dream.summary",
        )
    return _dream_summary_model


def init_dream_prompts() -> None:
    """初始化 dream agent 的提示词"""
    Prompt(
        """
你的名字是{bot_name}，你现在处于"梦境维护模式（dream agent）"。
你可以自由地在 ChatHistory 库中探索、整理、合并和删改记录，以帮助自己在未来更好地回忆和理解对话历史。

本轮要维护的聊天ID：{chat_id}
本轮随机选中的起始记忆 ID：{start_memory_id}
请优先以这条起始记忆为切入点，先理解它的内容与上下文，再决定如何在其附近进行合并、重写或删除等整理操作；如果起始记忆为空，则由你自行选择合适的切入点。

你可以使用的工具包括：
- list_chat_histories：浏览该 chat_id 下的历史概括列表
- get_chat_history_detail：查看某条概括的详细内容
- merge_chat_histories：把多条内容高度相似或应当归为一类的记录合并到一条
- update_chat_history：在不改变事实的前提下重写或精炼主题、概括、关键词、关键信息
- delete_chat_history：删除明显噪声、错误或无意义的记录（要格外谨慎）
- finish_maintenance：当你认为当前 chat_id 下的维护工作已经完成，没有更多需要整理的内容时，调用此工具来结束本次运行

**工作目标**：
- 发现冗余、重复或高度相似的记录，并进行合并或删除；
- 发现主题/概括过于含糊、啰嗦或缺少关键信息的记录，进行重写和精简；
- 尽量保持信息的真实与可用性，不要凭空捏造事实。

**轮次信息**：
- 本次维护最多执行 {max_iterations} 轮
- 每轮开始时，系统会告知你当前是第几轮，还剩多少轮
- 如果提前完成维护工作，可以调用 finish_maintenance 工具主动结束

**每一轮的执行方式（必须遵守）：**
- 第一步：先用一小段中文自然语言，写出你的「思考」和本轮计划（例如要查什么、准备怎么合并/修改）；
- 第二步：在这段思考之后，再通过工具调用来执行你的计划（可以调用 0~N 个工具）；
- 第三步：收到工具结果后，在下一轮继续先写出新的思考，再视情况继续调用工具。

请不要在没有先写出思考的情况下直接调用工具。
只输出你的思考内容或工具调用结果，由系统负责真正执行工具调用。
""",
        name="dream_react_head_prompt",
    )

    Prompt(
        """
你刚刚完成了一次对聊天记录的记忆整理工作。以下是整理过程的摘要：
整理过程：
{conversation_text}

请将这次整理涉及的相关信息改写为一个富有诗意和想象力的"梦境"，请你仅使用具体的记忆的内容，而不是整理过程编写。
要求：
1. 使用第一人称视角
2. 叙述直白，不要复杂修辞，口语化
3. 保持诗意和想象力，自由编写
4. 长度控制在200-800字
5. 用中文输出
请直接输出梦境内容，不要添加其他说明：
""",
        name="dream_summary_prompt",
    )


class DreamTool:
    """dream 模块内部使用的简易工具封装"""

    def __init__(self, name: str, description: str, parameters: List[Tuple], execute_func):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.execute_func = execute_func

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    async def execute(self, **kwargs) -> str:
        return await self.execute_func(**kwargs)


class DreamToolRegistry:
    def __init__(self) -> None:
        self.tools: Dict[str, DreamTool] = {}

    def register_tool(self, tool: DreamTool) -> None:
        if tool.name in self.tools:
            logger.debug(f"dream 工具 {tool.name} 已存在，跳过重复注册")
            return
        self.tools[tool.name] = tool
        logger.info(f"注册 dream 工具: {tool.name}")

    def get_tool(self, name: str) -> Optional[DreamTool]:
        return self.tools.get(name)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [tool.get_tool_definition() for tool in self.tools.values()]


_dream_tool_registry = DreamToolRegistry()


def get_dream_tool_registry() -> DreamToolRegistry:
    return _dream_tool_registry


def init_dream_tools() -> None:
    """注册 dream agent 可用的 ChatHistory 相关工具"""
    from src.plugin_system.apis import database_api

    async def list_chat_histories(chat_id: str, limit: int = 50) -> str:
        """列出某个 chat_id 下的 chat_history 概览"""
        try:
            logger.info(f"[dream][tool] 调用 list_chat_histories(chat_id={chat_id}, limit={limit})")
            query = (
                ChatHistory.select()
                .where(ChatHistory.chat_id == chat_id)
                .order_by(ChatHistory.start_time.asc())
                .limit(max(10, min(limit, 200)))
            )
            records = list(query)
            if not records:
                msg = f"chat_id={chat_id} 在 ChatHistory 中暂时没有记录。"
                logger.info(f"[dream][tool] list_chat_histories 无记录: {msg}")
                return msg

            lines: List[str] = []
            for r in records:
                lines.append(
                    f"ID={r.id} | 时间范围={r.start_time:.0f}-{r.end_time:.0f} | "
                    f"主题={r.theme or '无'} | 被检索次数={r.count} | 被遗忘次数={r.forget_times}"
                )
            result = "\n".join(lines)
            logger.info(
                f"[dream][tool] list_chat_histories 返回 {len(records)} 条记录，预览: {result[:200].replace(chr(10), ' ')}"
            )
            return result
        except Exception as e:
            logger.error(f"list_chat_histories 失败: {e}")
            return f"list_chat_histories 执行失败: {e}"

    async def get_chat_history_detail(memory_id: int) -> str:
        """获取单条 chat_history 的完整内容"""
        try:
            logger.info(f"[dream][tool] 调用 get_chat_history_detail(memory_id={memory_id})")
            record = ChatHistory.get_or_none(ChatHistory.id == memory_id)
            if not record:
                msg = f"未找到 ID={memory_id} 的 ChatHistory 记录。"
                logger.info(f"[dream][tool] get_chat_history_detail 未找到记录: {msg}")
                return msg

            result = (
                f"ID={record.id}\n"
                f"chat_id={record.chat_id}\n"
                f"时间范围={record.start_time}-{record.end_time}\n"
                f"主题={record.theme}\n"
                f"关键词={record.keywords}\n"
                f"参与者={record.participants}\n"
                f"概括={record.summary}\n"
                f"关键信息={record.key_point}\n"
                f"原文：\n{record.original_text}"
            )
            logger.info(
                f"[dream][tool] get_chat_history_detail 成功，原文长度={len(record.original_text or '')}，预览: {result[:200].replace(chr(10), ' ')}"
            )
            return result
        except Exception as e:
            logger.error(f"get_chat_history_detail 失败: {e}")
            return f"get_chat_history_detail 执行失败: {e}"

    async def delete_chat_history(memory_id: int) -> str:
        """删除一条 chat_history 记录"""
        try:
            logger.info(f"[dream][tool] 调用 delete_chat_history(memory_id={memory_id})")
            record = ChatHistory.get_or_none(ChatHistory.id == memory_id)
            if not record:
                msg = f"未找到 ID={memory_id} 的 ChatHistory 记录，无法删除。"
                logger.info(f"[dream][tool] delete_chat_history 未找到记录: {msg}")
                return msg
            rows = ChatHistory.delete().where(ChatHistory.id == memory_id).execute()
            msg = f"已删除 ID={memory_id} 的 ChatHistory 记录，受影响行数={rows}。"
            logger.info(f"[dream][tool] delete_chat_history 完成: {msg}")
            return msg
        except Exception as e:
            logger.error(f"delete_chat_history 失败: {e}")
            return f"delete_chat_history 执行失败: {e}"

    async def update_chat_history(
        memory_id: int,
        theme: Optional[str] = None,
        summary: Optional[str] = None,
        keywords: Optional[str] = None,
        key_point: Optional[str] = None,
    ) -> str:
        """按字段更新 chat_history（字符串字段要求 JSON 的字段须传入已序列化的字符串）"""
        try:
            logger.info(
                f"[dream][tool] 调用 update_chat_history(memory_id={memory_id}, "
                f"theme={bool(theme)}, summary={bool(summary)}, keywords={bool(keywords)}, key_point={bool(key_point)})"
            )
            record = ChatHistory.get_or_none(ChatHistory.id == memory_id)
            if not record:
                msg = f"未找到 ID={memory_id} 的 ChatHistory 记录，无法更新。"
                logger.info(f"[dream][tool] update_chat_history 未找到记录: {msg}")
                return msg

            data: Dict[str, Any] = {}
            if theme is not None:
                data["theme"] = theme
            if summary is not None:
                data["summary"] = summary
            if keywords is not None:
                data["keywords"] = keywords
            if key_point is not None:
                data["key_point"] = key_point

            if not data:
                return "未提供任何需要更新的字段。"

            await database_api.db_save(ChatHistory, data=data, key_field="id", key_value=memory_id)
            msg = f"已更新 ChatHistory 记录 ID={memory_id}，更新字段={list(data.keys())}。"
            logger.info(f"[dream][tool] update_chat_history 完成: {msg}")
            return msg
        except Exception as e:
            logger.error(f"update_chat_history 失败: {e}")
            return f"update_chat_history 执行失败: {e}"

    async def merge_chat_histories(target_id: int, from_ids: List[int] | str) -> str:
        """将多条 chat_history 合并到 target_id（合并文本与统计字段，删除 from_ids）

        from_ids 可以是整数列表，也可以是逗号/空格分隔的字符串，由本函数负责解析。
        """
        try:
            logger.info(f"[dream][tool] 调用 merge_chat_histories(target_id={target_id}, from_ids={from_ids})")
            # 兼容字符串形式的 from_ids，方便 LLM 传参
            if isinstance(from_ids, str):
                raw_parts = [p.strip() for p in from_ids.replace("，", ",").replace(" ", ",").split(",") if p.strip()]
                parsed_ids: List[int] = []
                for part in raw_parts:
                    try:
                        parsed_ids.append(int(part))
                    except ValueError:
                        continue
                from_ids = parsed_ids

            if target_id in from_ids:
                from_ids = [i for i in from_ids if i != target_id]
            if not from_ids:
                msg = "from_ids 为空或只包含 target_id，本次不执行合并。"
                logger.info(f"[dream][tool] merge_chat_histories 参数不足: {msg}")
                return msg

            target = ChatHistory.get_or_none(ChatHistory.id == target_id)
            if not target:
                msg = f"未找到合并目标 ID={target_id} 的记录。"
                logger.info(f"[dream][tool] merge_chat_histories 失败: {msg}")
                return msg

            others = list(ChatHistory.select().where(ChatHistory.id.in_(from_ids)))
            if not others:
                msg = f"未找到需要合并的来源记录: {from_ids}"
                logger.info(f"[dream][tool] merge_chat_histories 无来源记录: {msg}")
                return msg

            # 合并原文与统计字段（简单拼接）
            original_parts = [target.original_text or ""]
            for r in others:
                original_parts.append(r.original_text or "")
            target.original_text = "\n\n--- 合并分隔线 ---\n\n".join(p for p in original_parts if p)

            target.count = (target.count or 0) + sum(r.count or 0 for r in others)
            target.forget_times = (target.forget_times or 0) + sum(r.forget_times or 0 for r in others)

            target.save()
            deleted = ChatHistory.delete().where(ChatHistory.id.in_(from_ids)).execute()
            msg = (
                f"已将 ChatHistory {from_ids} 合并到 {target_id}，"
                f"合并后原文长度={len(target.original_text or '')}，删除记录数={deleted}。"
            )
            logger.info(f"[dream][tool] merge_chat_histories 完成: {msg}")
            return msg
        except Exception as e:
            logger.error(f"merge_chat_histories 失败: {e}")
            return f"merge_chat_histories 执行失败: {e}"

    async def finish_maintenance(reason: Optional[str] = None) -> str:
        """结束本次 dream 维护任务。当你认为当前 chat_id 下的维护工作已经完成，没有更多需要整理的内容时，调用此工具来结束本次运行。"""
        reason_text = f"，原因：{reason}" if reason else ""
        msg = f"DREAM_MAINTENANCE_COMPLETE{reason_text}"
        logger.info(f"[dream][tool] 调用 finish_maintenance，结束本次维护{reason_text}")
        return msg

    # 参数元组格式与 BaseTool 一致: (name, ToolParamType, desc, required, enum_values)
    from src.llm_models.payload_content.tool_option import ToolParamType

    _dream_tool_registry.register_tool(
        DreamTool(
            "list_chat_histories",
            "列出某个 chat_id 下的 ChatHistory 概览，便于全局理解该聊天的历史记忆。",
            [
                ("chat_id", ToolParamType.STRING, "需要浏览的 chat_id。", True, None),
                ("limit", ToolParamType.INTEGER, "最多返回多少条记录，默认 50，最大 200。", False, None),
            ],
            list_chat_histories,
        )
    )

    _dream_tool_registry.register_tool(
        DreamTool(
            "get_chat_history_detail",
            "根据 memory_id 获取单条 ChatHistory 的详细内容，包含原文与所有字段。",
            [
                ("memory_id", ToolParamType.INTEGER, "ChatHistory 主键 ID。", True, None),
            ],
            get_chat_history_detail,
        )
    )

    _dream_tool_registry.register_tool(
        DreamTool(
            "delete_chat_history",
            "根据 memory_id 删除一条 ChatHistory 记录（请谨慎使用）。",
            [
                ("memory_id", ToolParamType.INTEGER, "需要删除的 ChatHistory 主键 ID。", True, None),
            ],
            delete_chat_history,
        )
    )

    _dream_tool_registry.register_tool(
        DreamTool(
            "update_chat_history",
            "按字段更新 ChatHistory 记录，可用于清理、重写或补充信息。",
            [
                ("memory_id", ToolParamType.INTEGER, "需要更新的 ChatHistory 主键 ID。", True, None),
                ("theme", ToolParamType.STRING, "新的主题标题，如果不需要修改可不填。", False, None),
                ("summary", ToolParamType.STRING, "新的概括内容，如果不需要修改可不填。", False, None),
                ("keywords", ToolParamType.STRING, "新的关键词 JSON 字符串，如 ['关键词1','关键词2']。", False, None),
                ("key_point", ToolParamType.STRING, "新的关键信息 JSON 字符串，如 ['要点1','要点2']。", False, None),
            ],
            update_chat_history,
        )
    )

    _dream_tool_registry.register_tool(
        DreamTool(
            "merge_chat_histories",
            "将多条 ChatHistory 记录合并到一条中，可用于去重或把同一主题的多段记录整合在一起。",
            [
                ("target_id", ToolParamType.INTEGER, "合并的目标记录 ID。", True, None),
                (
                    "from_ids",
                    ToolParamType.STRING,
                    "需要被合并并删除的来源记录 ID 列表，可以是用逗号/空格分隔的字符串，如 '12, 13, 15'。",
                    True,
                    None,
                ),
            ],
            merge_chat_histories,
        )
    )

    _dream_tool_registry.register_tool(
        DreamTool(
            "finish_maintenance",
            "结束本次 dream 维护任务。当你认为当前 chat_id 下的维护工作已经完成，没有更多需要整理、合并或修改的内容时，调用此工具来主动结束本次运行。",
            [
                ("reason", ToolParamType.STRING, "结束维护的原因说明（可选），例如 '已完成所有记录的整理' 或 '当前记录质量良好，无需进一步维护'。", False, None),
            ],
            finish_maintenance,
        )
    )


async def run_dream_agent_once(
    chat_id: str,
    max_iterations: Optional[int] = None,
    start_memory_id: Optional[int] = None,
) -> None:
    """
    运行一次 dream agent，对指定 chat_id 的 ChatHistory 进行最多 max_iterations 轮的整理。
    如果 max_iterations 为 None，则使用配置文件中的默认值。
    """
    if max_iterations is None:
        max_iterations = global_config.dream.max_iterations
    
    start_ts = time.time()
    logger.info(f"[dream] 开始对 chat_id={chat_id} 进行 dream 维护，最多迭代 {max_iterations} 轮")

    # 初始化工具
    init_dream_tools()

    tool_registry = get_dream_tool_registry()
    tool_defs = tool_registry.get_tool_definitions()

    bot_name = global_config.bot.nickname
    time_now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    head_prompt = await global_prompt_manager.format_prompt(
        "dream_react_head_prompt",
        bot_name=bot_name,
        time_now=time_now,
        chat_id=chat_id,
        start_memory_id=start_memory_id if start_memory_id is not None else "无（本轮由你自由选择切入点）",
        max_iterations=max_iterations,
    )

    conversation_messages: List[Message] = []

    # 注意：message_factory 必须是同步函数，返回消息列表（不能是 async/coroutine）
    def message_factory(
        _client,
        *,
        _head_prompt: str = head_prompt,
        _conversation_messages: List[Message] = conversation_messages,
    ) -> List[Message]:
        messages: List[Message] = []
        system_builder = MessageBuilder()
        system_builder.set_role(RoleType.System)
        system_builder.add_text_content(_head_prompt)
        messages.append(system_builder.build())
        messages.extend(_conversation_messages)
        return messages

    for iteration in range(1, max_iterations + 1):
        # 在每轮开始时，添加轮次信息到对话中
        remaining_rounds = max_iterations - iteration + 1
        round_info_builder = MessageBuilder()
        round_info_builder.set_role(RoleType.User)
        round_info_builder.add_text_content(
            f"【轮次信息】当前是第 {iteration}/{max_iterations} 轮，还剩 {remaining_rounds} 轮。"
        )
        conversation_messages.append(round_info_builder.build())

        # 调用 LLM 让其决定是否要使用工具
        success, response, reasoning_content, model_name, tool_calls = (
            await llm_api.generate_with_model_with_tools_by_message_factory(
                message_factory,
                model_config=model_config.model_task_config.tool_use,
                tool_options=tool_defs,
                request_type="dream.react",
            )
        )

        if not success:
            logger.error(f"[dream] 第 {iteration} 轮 LLM 调用失败: {response}")
            break

        # 先输出「思考」内容，再输出工具调用信息
        thought_log = reasoning_content or (response[:300] if response else "")
        if thought_log:
            logger.info(f"[dream] 第 {iteration} 轮思考内容: {thought_log}")

        logger.info(
            f"[dream] 第 {iteration} 轮响应，模型={model_name}，工具调用数={len(tool_calls) if tool_calls else 0}"
        )

        assistant_msg: Optional[Message] = None
        if tool_calls:
            builder = MessageBuilder()
            builder.set_role(RoleType.Assistant)
            if response and response.strip():
                builder.add_text_content(response)
            builder.set_tool_calls(tool_calls)
            assistant_msg = builder.build()
        elif response and response.strip():
            builder = MessageBuilder()
            builder.set_role(RoleType.Assistant)
            builder.add_text_content(response)
            assistant_msg = builder.build()

        if assistant_msg:
            conversation_messages.append(assistant_msg)

        # 如果本轮没有工具调用，仅作为思考记录，继续下一轮
        if not tool_calls:
            logger.debug(f"[dream] 第 {iteration} 轮未调用任何工具，仅记录思考。")
            continue

        # 执行所有工具调用
        tasks = []
        finish_maintenance_called = False
        for tc in tool_calls:
            tool = tool_registry.get_tool(tc.func_name)
            if not tool:
                logger.warning(f"[dream] 未知工具：{tc.func_name}")
                continue

            # 检测是否调用了 finish_maintenance 工具
            if tc.func_name == "finish_maintenance":
                finish_maintenance_called = True

            params = tc.args or {}

            async def _run_single(t: DreamTool, p: Dict[str, Any], call_id: str, it: int):
                try:
                    result = await t.execute(**p)
                    logger.info(f"[dream] 第 {it} 轮 工具 {t.name} 执行完成。")
                    return call_id, result
                except Exception as e:
                    logger.error(f"[dream] 工具 {t.name} 执行失败: {e}")
                    return call_id, f"工具 {t.name} 执行失败: {e}"

            tasks.append(_run_single(tool, params, tc.call_id, iteration))

        if not tasks:
            continue

        tool_results = await asyncio.gather(*tasks, return_exceptions=False)

        # 将工具结果作为 Tool 消息追加
        for call_id, obs in tool_results:
            tool_builder = MessageBuilder()
            tool_builder.set_role(RoleType.Tool)
            tool_builder.add_text_content(str(obs))
            tool_builder.add_tool_call(call_id)
            conversation_messages.append(tool_builder.build())

        # 如果调用了 finish_maintenance 工具，提前结束本次运行
        if finish_maintenance_called:
            logger.info(f"[dream] 第 {iteration} 轮检测到 finish_maintenance 工具调用，提前结束本次维护。")
            break

    cost = time.time() - start_ts
    logger.info(f"[dream] 对 chat_id={chat_id} 的 dream 维护结束，共迭代 {iteration} 轮，耗时 {cost:.1f} 秒")

    # 生成梦境总结
    await _generate_dream_summary(chat_id, conversation_messages, iteration, cost)


async def _generate_dream_summary(
    chat_id: str,
    conversation_messages: List[Message],
    total_iterations: int,
    time_cost: float,
) -> None:
    """生成梦境总结并输出到日志"""
    try:
        import json
        
        # 第一步：建立工具调用结果映射 (call_id -> result)
        tool_results_map: Dict[str, str] = {}
        for msg in conversation_messages:
            if msg.role == RoleType.Tool and msg.tool_call_id:
                content = ""
                if msg.content:
                    if isinstance(msg.content, list) and msg.content:
                        content = msg.content[0].text if hasattr(msg.content[0], "text") else str(msg.content[0])
                    else:
                        content = str(msg.content)
                tool_results_map[msg.tool_call_id] = content
        
        # 第二步：详细记录所有工具调用操作和结果到日志
        tool_call_count = 0
        logger.info(f"[dream][工具调用详情] 开始记录 chat_id={chat_id} 的所有工具调用操作：")
        
        for msg in conversation_messages:
            if msg.role == RoleType.Assistant and msg.tool_calls:
                tool_call_count += 1
                # 提取思考内容
                thought_content = ""
                if msg.content:
                    if isinstance(msg.content, list) and msg.content:
                        thought_content = msg.content[0].text if hasattr(msg.content[0], "text") else str(msg.content[0])
                    else:
                        thought_content = str(msg.content)
                
                logger.info(f"[dream][工具调用详情] === 第 {tool_call_count} 组工具调用 ===")
                if thought_content:
                    logger.info(f"[dream][工具调用详情] 思考内容：{thought_content[:500]}{'...' if len(thought_content) > 500 else ''}")
                
                # 记录每个工具调用的详细信息
                for idx, tool_call in enumerate(msg.tool_calls, 1):
                    tool_name = tool_call.func_name
                    tool_args = tool_call.args or {}
                    tool_call_id = tool_call.call_id
                    tool_result = tool_results_map.get(tool_call_id, "未找到执行结果")
                    
                    # 格式化参数
                    try:
                        args_str = json.dumps(tool_args, ensure_ascii=False, indent=2) if tool_args else "无参数"
                    except Exception:
                        args_str = str(tool_args)
                    
                    logger.info(f"[dream][工具调用详情] --- 工具 {idx}: {tool_name} ---")
                    logger.info(f"[dream][工具调用详情] 调用参数：\n{args_str}")
                    logger.info(f"[dream][工具调用详情] 执行结果：\n{tool_result}")
                    logger.info(f"[dream][工具调用详情] {'-' * 60}")
        
        logger.info(f"[dream][工具调用详情] 共记录了 {tool_call_count} 组工具调用操作")
        
        # 第三步：构建对话历史摘要（用于生成梦境）
        conversation_summary = []
        for msg in conversation_messages:
            role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            content = ""
            if msg.content:
                content = msg.content[0].text if isinstance(msg.content, list) and msg.content else str(msg.content)
            
            if role == "user" and "轮次信息" in content:
                # 跳过轮次信息消息
                continue
            
            if role == "assistant":
                # 只保留思考内容，简化工具调用信息
                if content:
                    # 截取前500字符，避免过长
                    content_preview = content[:500] + ("..." if len(content) > 500 else "")
                    conversation_summary.append(f"[{role}] {content_preview}")
            elif role == "tool":
                # 工具结果，只保留关键信息
                if content:
                    # 截取前300字符
                    content_preview = content[:300] + ("..." if len(content) > 300 else "")
                    conversation_summary.append(f"[工具执行] {content_preview}")
        
        conversation_text = "\n".join(conversation_summary[-20:])  # 只保留最后20条消息
        
        # 使用 Prompt 管理器格式化梦境生成 prompt
        dream_prompt = await global_prompt_manager.format_prompt(
            "dream_summary_prompt",
            chat_id=chat_id,
            total_iterations=total_iterations,
            time_cost=time_cost,
            conversation_text=conversation_text,
        )

        # 调用 utils 模型生成梦境
        summary_model = _get_dream_summary_model()
        dream_content, (reasoning, model_name, _) = await summary_model.generate_response_async(
            dream_prompt,
            max_tokens=512,
            temperature=0.8,
        )
        
        if dream_content:
            logger.info(f"[dream][梦境总结] 对 chat_id={chat_id} 的整理过程梦境：\n{dream_content}")
        else:
            logger.warning("[dream][梦境总结] 未能生成梦境总结")
            
    except Exception as e:
        logger.error(f"[dream][梦境总结] 生成梦境总结失败: {e}", exc_info=True)


def _pick_random_chat_id() -> Optional[str]:
    """从 ChatHistory 中随机选择一个 chat_id，用于 dream agent 本次维护"""
    try:
        rows = (
            ChatHistory.select(ChatHistory.chat_id)
            .distinct()
            .order_by(ChatHistory.chat_id)
            .limit(200)
        )
        ids = [r.chat_id for r in rows]
        if not ids:
            logger.warning("[dream] ChatHistory 中暂无可用 chat_id，本轮 dream 任务跳过。")
            return None
        return random.choice(ids)
    except Exception as e:
        logger.error(f"[dream] 随机选择 chat_id 失败: {e}")
        return None


def _pick_random_memory_for_chat(chat_id: str) -> Optional[int]:
    """
    在给定 chat_id 下随机选择一条 ChatHistory 记录，作为本轮整理的起始记忆。
    """
    try:
        rows = (
            ChatHistory.select(ChatHistory.id)
            .where(ChatHistory.chat_id == chat_id)
            .order_by(ChatHistory.start_time.asc())
            .limit(200)
        )
        ids = [r.id for r in rows]
        if not ids:
            logger.warning(f"[dream] chat_id={chat_id} 下暂无 ChatHistory 记录，无法选择起始记忆。")
            return None
        return random.choice(ids)
    except Exception as e:
        logger.error(f"[dream] 在 chat_id={chat_id} 下随机选择起始记忆失败: {e}")
        return None


async def run_dream_cycle_once() -> None:
    """
    单次 dream 周期：
    - 随机选择一个 chat_id
    - 在该 chat_id 下随机选择一条 ChatHistory 作为起始记忆
    - 以这条起始记忆为切入点，对该 chat_id 运行一次 dream agent（最多 15 轮）
    """
    chat_id = _pick_random_chat_id()
    if not chat_id:
        return

    start_memory_id = _pick_random_memory_for_chat(chat_id)
    await run_dream_agent_once(
        chat_id=chat_id,
        max_iterations=None,  # 使用配置文件中的默认值
        start_memory_id=start_memory_id,
    )


async def start_dream_scheduler(
    first_delay_seconds: int = 60,
    interval_seconds: Optional[int] = None,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    """
    dream 调度器：
    - 程序启动后先等待 first_delay_seconds（默认 60s）
    - 然后每隔 interval_seconds（如果为 None，则使用配置文件中的值，默认 30 分钟）运行一次 dream agent 周期
    - 如果提供 stop_event，则在 stop_event 被 set() 后优雅退出循环
    """
    if interval_seconds is None:
        interval_seconds = global_config.dream.interval_minutes * 60
    
    logger.info(
        f"[dream] dream 调度器启动：首次延迟 {first_delay_seconds}s，之后每隔 {interval_seconds}s ({interval_seconds // 60} 分钟) 运行一次 dream agent"
    )

    try:
        await asyncio.sleep(first_delay_seconds)
        while True:
            if stop_event is not None and stop_event.is_set():
                logger.info("[dream] 收到停止事件，结束 dream 调度器循环。")
                break

            start_ts = time.time()
            try:
                await run_dream_cycle_once()
            except Exception as e:
                logger.error(f"[dream] 单次 dream 周期执行异常: {e}")

            elapsed = time.time() - start_ts
            # 保证两次执行之间至少间隔 interval_seconds
            to_sleep = max(0.0, interval_seconds - elapsed)
            await asyncio.sleep(to_sleep)
    except asyncio.CancelledError:
        logger.info("[dream] dream 调度器任务被取消，准备退出。")
        raise


# 初始化提示词
init_dream_prompts()


"""reply 内置工具。"""

from pathlib import Path
from typing import Any, Optional

import json
import asyncio
import traceback

from src.chat.replyer.replyer_manager import replyer_manager
from src.chat.utils.utils import is_bot_self
from src.cli.maisaka_cli_sender import CLI_PLATFORM_NAME, render_cli_message
from src.common.data_models.reply_generation_data_models import ReplyGenerationResult, build_reply_monitor_detail
from src.common.logger import get_logger
from src.config import config as config_module
from src.core.tooling import ToolExecutionContext, ToolExecutionResult, ToolInvocation, ToolSpec
from src.maisaka.context.message_adapter import build_visible_text_from_sequence, parse_speaker_content
from src.maisaka.context.message_id_alias import to_display_message_id
from src.maisaka.context.messages import LLMContextMessage, SessionBackedMessage
from src.maisaka.context.planner_messages import extract_quote_ids_from_message_sequence
from src.services import send_service

from .context import BuiltinToolRuntimeContext

logger = get_logger("maisaka_builtin_reply")
_REPLY_TOOL_INTERNAL_ARGUMENTS = {"msg_id", "set_quote"}
_RICH_REPLY_ARGUMENTS = {"attach_pic", "attach_emoji", "attach_at"}
_DUPLICATE_TARGET_REPLY_REMINDER_ARG = "_duplicate_target_reply_reminder"
_DUPLICATE_TARGET_REPLY_REMINDER_TEMPLATE = (
    "你刚刚已经回复过这条消息，你刚刚的发言是：“{previous_reply}”\n"
    "你现在想再次回复这条消息，进行补充，注意请不要和之前你的发言重复。"
)


def _normalize_reply_arguments(raw_arguments: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """兼容模型把 reply 参数重复包裹在 arguments 字段中的情况。"""

    if set(raw_arguments) != {"arguments"}:
        return raw_arguments, ""

    wrapped_arguments = raw_arguments["arguments"]
    if not isinstance(wrapped_arguments, str):
        return raw_arguments, (
            "reply 工具参数结构错误：顶层 `arguments` 应为包含 reply 参数的 JSON 字符串，"
            f"实际类型为 {type(wrapped_arguments).__name__}。"
        )

    try:
        parsed_arguments = json.loads(wrapped_arguments)
    except json.JSONDecodeError as exc:
        return raw_arguments, f"reply 工具参数结构错误：顶层 `arguments` 不是有效的 JSON 对象：{exc.msg}。"

    if not isinstance(parsed_arguments, dict):
        return raw_arguments, (
            "reply 工具参数结构错误：顶层 `arguments` 必须解析为 JSON 对象，"
            f"实际解析结果为 {type(parsed_arguments).__name__}。"
        )

    return parsed_arguments, ""


def _use_expression_intent() -> bool:
    return config_module.global_config.expression.use_vector_expression


def _require_hook_bool(raw_value: Any, option_name: str) -> bool:
    """读取 Hook 返回的布尔值，并拒绝不符合协议的类型。"""

    if isinstance(raw_value, bool):
        return raw_value
    raise TypeError(f"Hook 返回的 {option_name} 必须是布尔值，实际为 {type(raw_value).__name__}")


async def _invoke_before_post_process_hook(
    tool_ctx: BuiltinToolRuntimeContext,
    reply_text: str,
    target_message_id: str,
    reply_tool_args: dict[str, Any],
) -> tuple[str, dict[str, bool]]:
    """调用最终回复文本后处理前 Hook，并返回本次回复的后处理策略。"""

    post_process_options = {
        "skip_post_process": False,
        "enable_splitter": True,
        "enable_chinese_typo": True,
    }
    before_post_process_result = await tool_ctx.get_runtime_manager().invoke_hook(
        "maisaka.reply.before_post_process",
        response=reply_text,
        session_id=tool_ctx.runtime.session_id,
        reply_message_id=target_message_id,
        reply_tool_args=dict(reply_tool_args),
        **post_process_options,
    )
    before_post_process_kwargs = before_post_process_result.kwargs
    if "response" in before_post_process_kwargs:
        reply_text = str(before_post_process_kwargs["response"] or "").strip()
    for option_name in post_process_options:
        post_process_options[option_name] = _require_hook_bool(
            before_post_process_kwargs.get(option_name),
            option_name,
        )
    return reply_text, post_process_options


async def _run_expression_selector(tool_ctx: BuiltinToolRuntimeContext, system_prompt: str) -> str:
    """运行 replyer 侧表达方式选择子代理，并返回文本结果。"""
    response = await tool_ctx.runtime.run_sub_agent(
        context_message_limit=10,
        system_prompt=system_prompt,
        request_kind="expression_selector",
    )
    return (response.content or "").strip()


def get_tool_spec() -> ToolSpec:
    """获取 reply 工具声明。"""

    properties: dict[str, Any] = {
        "msg_id": {
            "type": "string",
            "description": "要回复的消息msg_id。",
        },
        "set_quote": {
            "type": "boolean",
            "description": "以引用回复的方式发送这条回复，当发言人数过多，聊天比较乱时使用。",
            "default": True,
        },
        "reply_action": {
            "type": "string",
            "description": (
                "默认 reply：回复用户消息，不能以机器人自身历史消息为目标。"
                "仅明确要补充自己上一条发言时选择 supplement_self，并将 msg_id 指向该发言。"
                "用户引用机器人消息仍属于普通 reply，不应选择 supplement_self。"
            ),
            "enum": ["reply", "supplement_self"],
            "default": "reply",
        },
        "reply_reference": {
            "type": "string",
            "description": (
                "有助于回复当前目标 msg_id 的信息，包括当前聊天状态、人物关系、事实信息、回忆信息。"
                "一次 reply 只针对这一个 msg_id，禁止把不同人或不同消息的多个问题（如两道测试题）合并写进同一条 reply_reference。"
            ),
        },
        "reply_style": {
            "type": "string",
            "description": "可选。控制本次回复的篇幅和表达方式；正常回复不会附加额外要求。",
            "enum": ["简短表达", "正常回复", "长回复"],
        },
    }
    if _use_expression_intent():
        properties["expression_intent"] = {
            "type": "object",
            "description": (
                "可选。给 replyer 表达方式选择使用的结构化意图，不是回复正文。"
                "当这次回复需要特定语气、场景或话术时填写，避免表达选择只按关键词匹配。"
            ),
            "properties": {
                "focus": {
                    "type": "string",
                    "description": "本次表达主要应该贴合的目标消息、片段或话题。",
                },
                "reply_act": {
                    "type": "string",
                    "description": "这次回复要完成的动作，例如澄清、安抚、调侃、追问、解释边界。",
                },
                "scene": {
                    "type": "string",
                    "description": "当前表达场景，例如技术排查、截图分享、撒娇玩笑、价格询问。",
                },
                "tone": {
                    "type": "string",
                    "description": "期望语气，例如轻松、可靠、吐槽、委婉、简短肯定。",
                },
                "prefer": {
                    "type": "array",
                    "description": "优先考虑的表达类型或话术倾向。",
                    "items": {"type": "string"},
                },
                "avoid": {
                    "type": "array",
                    "description": "需要避免的表达类型、误判方向或不该注入的具体结论。",
                    "items": {"type": "string"},
                },
            },
        }
    if bool(config_module.global_config.experimental.enable_rich_reply):
        properties["attach_pic"] = {
            "type": "array",
            "description": (
                "可选。随本次回复附加一张或多张上下文图片。每项使用 msg_id + index，"
                "或使用 media_index=tool_result:<call_id>:<item_index> 指向工具返回媒体。"
            ),
            "items": {
                "type": "object",
                "properties": {
                    "msg_id": {
                        "type": "string",
                        "description": "图片所在的消息编号。",
                        "default": "",
                    },
                    "media_index": {
                        "type": "string",
                        "description": "工具返回媒体索引，例如 tool_result:call_x:1；与 msg_id 二选一。",
                        "default": "",
                    },
                    "index": {
                        "type": "integer",
                        "description": "同一消息中的图片序号，从 0 开始。",
                        "default": 0,
                    },
                },
            },
            "default": [],
        }
        properties["attach_emoji"] = {
            "type": "integer",
            "minimum": 1,
            "description": "可选。从 show_emoji_list 的拼图选择一个表情包，填写图片序号，在文字后单独发送。",
        }
        properties["attach_at"] = {
            "type": "array",
            "description": "可选。随本次回复 at 一个或多个目标消息的发送者，填写目标 msg_id。",
            "items": {"type": "string"},
            "default": [],
        }

    return ToolSpec(
        name="reply",
        description="根据当前思考生成并发送一条可见回复。",
        parameters_schema={
            "type": "object",
            "properties": properties,
            "required": ["msg_id"],
        },
        provider_name="maisaka_builtin",
        provider_type="builtin",
    )


def _build_monitor_metadata(reply_result: ReplyGenerationResult) -> dict[str, object]:
    """从 reply 结果中提取统一监控详情。"""

    monitor_detail = reply_result.monitor_detail
    if isinstance(monitor_detail, dict):
        return {"monitor_detail": monitor_detail}
    return {}


def _build_send_result(
    *,
    index: int,
    segment: str,
    set_quote: bool,
    success: bool,
    message_id: str = "",
) -> dict[str, Any]:
    """构建分段回复的轻量发送结果。"""

    return {
        "index": index,
        "segment": segment,
        "set_quote": set_quote,
        "success": success,
        "message_id": message_id,
    }


def _resolve_segment_reply_context(
    *,
    index: int,
    quote_previous: bool,
    effective_set_quote: bool,
    target_message: Any,
    previous_sent_message: Any,
) -> tuple[bool, Any]:
    """确定当前分段是否引用，以及引用所使用的真实消息对象。"""

    if index == 0:
        return effective_set_quote, target_message
    if quote_previous and previous_sent_message is not None:
        return True, previous_sent_message
    return False, target_message


def _extract_guided_reply_text(message: SessionBackedMessage) -> str:
    """提取 bot 已发送 guided reply 的可见正文。"""

    plain_text = message.processed_plain_text.strip()
    _speaker, body = parse_speaker_content(plain_text)
    normalized_text = (body or plain_text).strip()
    if not normalized_text:
        normalized_text = build_visible_text_from_sequence(message.raw_message).strip()
    return " ".join(normalized_text.split())


def _find_recent_reply_to_target(
    chat_history: list[LLMContextMessage],
    target_message_id: str,
) -> str:
    """查找最近一次已经引用回复过目标消息的 bot 发言。"""

    normalized_target_message_id = target_message_id.strip()
    if not normalized_target_message_id:
        return ""

    for message in reversed(chat_history):
        if not isinstance(message, SessionBackedMessage):
            continue
        if message.source_kind != "guided_reply":
            continue
        quote_ids = extract_quote_ids_from_message_sequence(message.raw_message)
        if normalized_target_message_id not in quote_ids:
            continue
        reply_text = _extract_guided_reply_text(message)
        if reply_text:
            return reply_text
    return ""


def _with_duplicate_target_reply_reminder(
    reply_tool_args: dict[str, Any],
    previous_reply: str,
) -> dict[str, Any]:
    """把重复回复同一目标消息的提醒作为独立提示传给 replyer。"""

    normalized_previous_reply = " ".join(previous_reply.split()).strip()
    if not normalized_previous_reply:
        return reply_tool_args

    updated_args = dict(reply_tool_args)
    updated_args[_DUPLICATE_TARGET_REPLY_REMINDER_ARG] = _DUPLICATE_TARGET_REPLY_REMINDER_TEMPLATE.format(
        previous_reply=normalized_previous_reply
    )
    return updated_args


async def handle_tool(
    tool_ctx: BuiltinToolRuntimeContext,
    invocation: ToolInvocation,
    context: Optional[ToolExecutionContext] = None,
) -> ToolExecutionResult:
    """执行 reply 内置工具。"""

    raw_invocation_arguments = dict(invocation.arguments or {})
    invocation_arguments, argument_structure_error = _normalize_reply_arguments(raw_invocation_arguments)
    if argument_structure_error:
        return tool_ctx.build_failure_result(invocation.tool_name, argument_structure_error)
    if invocation_arguments != raw_invocation_arguments:
        logger.warning(
            f"{tool_ctx.runtime.log_prefix} 检测到 reply 工具参数被重复包裹，已自动解包: "
            f"调用编号={invocation.call_id}"
        )
    latest_thought = context.reasoning if context is not None else invocation.reasoning
    target_message_id = str(invocation_arguments.get("msg_id") or "").strip()
    set_quote = bool(invocation_arguments.get("set_quote", True))
    rich_reply_enabled = bool(config_module.global_config.experimental.enable_rich_reply)
    reply_tool_args = {
        key: value
        for key, value in invocation_arguments.items()
        if key not in _REPLY_TOOL_INTERNAL_ARGUMENTS
    }
    if not rich_reply_enabled:
        for key in _RICH_REPLY_ARGUMENTS:
            reply_tool_args.pop(key, None)
    if not _use_expression_intent():
        reply_tool_args.pop("expression_intent", None)
    enable_reply_quote = bool(config_module.global_config.chat.reply_style.enable_reply_quote)
    effective_set_quote = set_quote and enable_reply_quote

    if not target_message_id:
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "reply 工具需要提供有效的 `msg_id` 参数。",
        )

    target_message = tool_ctx.runtime.find_source_message_by_id(target_message_id)
    if target_message is None:
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            f"未找到要回复的目标消息，msg_id={to_display_message_id(target_message_id)}",
        )

    # 只判断解析后的目标消息作者；用户引用机器人消息仍然是用户发言。
    if (
        is_bot_self(target_message.platform, target_message.message_info.user_info.user_id)
        and invocation_arguments.get("reply_action", "reply") != "supplement_self"
    ):
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "普通 reply 不能以机器人自身历史消息为目标，请选择用户消息。",
        )

    # 生成前只查状态；不恢复、补登记或提前占用发送尝试。
    from src.maisaka.context.continuity_bridge import envelope, ledger_call
    continuity = None
    if tool_ctx.runtime.chat_stream.platform == "telegram":
        try:
            continuity = envelope(tool_ctx.runtime.session_id,
                                  target_message.message_info.user_info.user_id,
                                  target_message_id, tool_ctx.engine._active_logical_turn_id)
            row = await ledger_call("get", continuity["session_id"], continuity["user_id"], target_message_id)
        except Exception as exc:
            logger.warning("回复互动账本不可用: %s", type(exc).__name__)
            row = None
        if not row or row["last_attempt_at"] is not None or row["status"] not in {"pending", "blocked"}:
            return tool_ctx.build_failure_result(invocation.tool_name, "目标无可发送的新入站记录，停止本轮。",
                metadata={"pause_execution": True, "retryable": False})

    async def mark_continuity_blocked(reason):
        if continuity is not None:
            try:
                await ledger_call("record_blocked", continuity["session_id"], continuity["user_id"],
                                  target_message_id, reason_code=reason)
            except Exception as exc:
                logger.warning("互动阻断记录失败: %s", type(exc).__name__)

    # 策略停止只覆盖当前逻辑轮；不确定发送单独隔离，绝不自动重放。
    turn_id = getattr(tool_ctx.engine, "_active_logical_turn_id", "")
    if getattr(tool_ctx.runtime, "_reply_terminal_turn", None) != turn_id:
        tool_ctx.runtime._reply_terminal_turn = turn_id
        tool_ctx.runtime._reply_terminal_targets = {}
    terminal_targets = getattr(tool_ctx.runtime, "_reply_terminal_targets", None)
    if terminal_targets is None:
        terminal_targets = {}
        tool_ctx.runtime._reply_terminal_targets = terminal_targets
    uncertain_targets = getattr(tool_ctx.runtime, "_reply_uncertain_targets", None)
    if uncertain_targets is None:
        uncertain_targets = {}
        tool_ctx.runtime._reply_uncertain_targets = uncertain_targets
    if target_message_id in terminal_targets or target_message_id in uncertain_targets or len(uncertain_targets) >= 256:
        details = uncertain_targets.get(target_message_id) or terminal_targets.get(target_message_id) or {
            "delivery_outcome": "delivery_unknown", "sent": False, "retryable": False,
            "policy_reason": "不确定发送隔离已满，需要人工核对送达记录", 
        }
        return tool_ctx.build_failure_result(
            invocation.tool_name, f"此目标的回复已终止，不重试：{details['policy_reason']}",
            structured_content=details, metadata={**details, "pause_execution": True},
        )
    if len(terminal_targets) >= 256:
        terminal_targets.pop(next(iter(terminal_targets)))

    # Planner -> Replyer 结构化前置契约校验（Codex 耦合审计 #6）：
    # 对裸媒体占位符目标或含"看不到视频/让对方发截图"意图的 reply 调用直接按策略静默终止，不进入 Replyer 生成。
    from src.chat.utils.identity_guard import check_reply_intent_guard
    _intent_ok, _intent_reason = check_reply_intent_guard(
        getattr(target_message, "processed_plain_text", "") or "",
        str(reply_tool_args.get("reply_reference") or ""),
        is_group_chat=bool(getattr(tool_ctx.runtime, "_is_group_chat", True)),
    )
    if not _intent_ok:
        await mark_continuity_blocked("policy_preflight")
        metadata = {
            "delivery_outcome": "policy_dropped",
            "policy_reason": _intent_reason,
            "policy_silence": True,
            "sent": False,
            "retryable": False,
            "pause_execution": True,
            "outcome": "blocked_by_policy",
        }
        terminal_targets[target_message_id] = metadata
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            f"策略跳过：目标消息为未解析媒体占位或意图命中模态边界（{_intent_reason}），已静默终止，请勿补发。",
            structured_content={"msg_id": target_message_id, **metadata},
            metadata=metadata,
        )

    # Planner/Replyer 共享结构化前置策略：
    # 在调用 Replyer 生成前拦截针对裸媒体占位符、索要截图意图或作者专属 Bug 报告模板的 reply 调用。
    from src.chat.utils.identity_guard import check_planner_reply_policy
    _exp_intent = reply_tool_args.get("expression_intent")
    _prefer_list = tuple(_exp_intent.get("prefer") or ()) if isinstance(_exp_intent, dict) else ()
    _t_add_cfg = getattr(getattr(target_message, "message_info", None), "additional_config", None) or {}
    _t_directed = bool(
        getattr(target_message, "is_at", False)
        or getattr(target_message, "is_mentioned", False)
        or _t_add_cfg.get("is_mentioned")
    )
    _planner_allowed, _planner_reason = check_planner_reply_policy(
        target_text=getattr(target_message, "processed_plain_text", "") or "",
        reply_reference=str(reply_tool_args.get("reply_reference") or ""),
        prefer_items=_prefer_list,
        is_group_chat=bool(getattr(tool_ctx.runtime, "_is_group_chat", True)),
        is_directed=_t_directed,
    )
    if not _planner_allowed:
        await mark_continuity_blocked("planner_policy_guard")
        metadata = {
            "delivery_outcome": "policy_dropped",
            "policy_reason": _planner_reason,
            "policy_silence": True,
            "sent": False,
            "retryable": False,
            "pause_execution": True,
            "outcome": "blocked_by_policy",
        }
        terminal_targets[target_message_id] = metadata
        try:
            from src.self_evolution.monitor import EvolutionMonitor, MetricEvent
            from src.self_evolution.policy import resolve_self_evolution_path
            import uuid as _uuid
            EvolutionMonitor(resolve_self_evolution_path("data/self-evolution/monitor")).record(
                MetricEvent(
                    target="maisaka.replyer",
                    outcome="policy_dropped",
                    score=None,
                    metadata={"reason": str(_planner_reason)[:120]},
                    event_id=f"replyer:{_uuid.uuid4().hex}",
                )
            )
        except (OSError, ValueError) as exc:
            logger.warning("自演化监测记录失败: %s", type(exc).__name__)
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            f"策略跳过：当前目标或回复意图触发静默边界（{_planner_reason}），已停止生成，请勿补发。",
            structured_content={"msg_id": target_message_id, **metadata},
            metadata=metadata,
        )

    if tool_ctx.runtime.chat_stream.platform != CLI_PLATFORM_NAME:
        policy = await send_service.preflight_reply_policy(tool_ctx.runtime.session_id, target_message)
        if policy.get("allowed") is not True:
            await mark_continuity_blocked("policy_preflight")
            reason = str(policy.get("reason") or "策略预检未放行")
            outcome = str(policy.get("outcome") or "preflight_unavailable")
            metadata = {"delivery_outcome": outcome, "policy_reason": reason,
                        "policy_silence": outcome == "policy_dropped", "sent": False,
                        "retryable": False, "pause_execution": True,
                        "outcome": "blocked_by_policy" if outcome == "policy_dropped" else outcome}
            terminal_targets[target_message_id] = metadata
            label = "策略跳过" if outcome == "policy_dropped" else "预检不可用"
            return tool_ctx.build_failure_result(
                invocation.tool_name, f"{label}：回复生成前已停止，未生成、未发送：{reason}。请勿补发。",
                structured_content={"msg_id": target_message_id, **metadata}, metadata=metadata,
            )

    try:
        replyer = replyer_manager.get_replyer(
            chat_stream=tool_ctx.runtime.chat_stream,
            request_type="maisaka.replyer",
            replyer_type="maisaka",
        )
    except Exception:
        logger.exception(f"{tool_ctx.runtime.log_prefix} 获取回复生成器时发生异常: 目标消息编号={target_message_id}")
        await mark_continuity_blocked("replyer_unavailable")
        logger.info(traceback.format_exc())
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "获取 Maisaka 回复生成器时发生异常。",
        )

    if replyer is None:
        await mark_continuity_blocked("replyer_unavailable")
        logger.error(f"{tool_ctx.runtime.log_prefix} 获取 Maisaka 回复生成器失败")
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "Maisaka 回复生成器当前不可用。",
        )

    replyer_chat_history = list(tool_ctx.runtime._chat_history)
    from src.maisaka.context.messages import ToolResultMessage

    current_turn_id = getattr(tool_ctx.engine, "_active_logical_turn_id", "")
    # fetch_url 读到的权威页面（如结构化赛程接口）同样是本轮依据；只取最近 3 条、每条限长，防止上下文膨胀。
    search_evidence = [
        str(message.content)[:6000]
        for message in replyer_chat_history
        if isinstance(message, ToolResultMessage)
        and message.tool_name in {"web_search", "tavily_search", "fetch_url", "sports_schedule"}
        and message.success
        and message.logical_turn_id == current_turn_id
        and current_turn_id
    ][-3:]
    if search_evidence:
        # Replyer 的普通历史会过滤工具消息；通过显式参考传递同轮搜索，避免只看 Planner 猜测。
        original_reference = str(reply_tool_args.get("reply_reference") or "")
        reply_tool_args["reply_reference"] = (
            original_reference + "\n本轮搜索依据（不得添加来源之外的猜测）：\n" + "\n".join(search_evidence)
        )
    elif any(
        isinstance(message, ToolResultMessage)
        and message.tool_name in {"web_search", "tavily_search", "fetch_url", "sports_schedule"}
        and not message.success
        and message.logical_turn_id == current_turn_id
        and current_turn_id
        for message in replyer_chat_history
    ):
        # 群聊中若对方并未点名/引用我们，查询失败时直接静默终止，绝不主动跑去汇报"暂时查不到"（2026-10-25 1062376 事故）。
        _is_group = bool(getattr(tool_ctx.runtime, "_is_group_chat", True))
        _target_add_cfg = getattr(getattr(target_message, "message_info", None), "additional_config", None) or {}
        _target_directed = bool(getattr(target_message, "is_at", False) or getattr(target_message, "is_mentioned", False) or _target_add_cfg.get("is_mentioned"))
        if _is_group and not _target_directed:
            await mark_continuity_blocked("search_failed_undirected_silence")
            metadata = {
                "delivery_outcome": "policy_dropped",
                "policy_reason": "search_failed_undirected_silence",
                "policy_silence": True,
                "sent": False,
                "retryable": False,
                "pause_execution": True,
                "outcome": "blocked_by_policy",
            }
            terminal_targets[target_message_id] = metadata
            return tool_ctx.build_failure_result(
                invocation.tool_name,
                "策略跳过：群聊未被点名且本轮搜索未取得依据，保持沉默不发送「暂时查不到」。请勿补发。",
                structured_content={"msg_id": target_message_id, **metadata},
                metadata=metadata,
            )
        original_reference = str(reply_tool_args.get("reply_reference") or "")
        reply_tool_args["reply_reference"] = (
            original_reference
            + "\n【本轮查询未完成】没有取得可靠搜索依据。准确说明这次未查到或尚未核实，不虚构没看比赛、没关注等个人经历；内部凭据、路径和堆栈不对外展示。失败告知不是原问题已解决。"
        )
    if continuity is not None:
        try:
            summary = await ledger_call("summary", continuity["session_id"], continuity["user_id"])
            reply_tool_args["reply_reference"] = str(reply_tool_args.get("reply_reference") or "") + "\n" + summary
        except Exception as exc:
            logger.warning("Replyer 互动摘要降级: %s", type(exc).__name__)
    from src.maisaka.context.person_candidates import current_person_candidates
    person_candidates = await current_person_candidates(target_message)
    if person_candidates:
        reply_tool_args["reply_reference"] = str(reply_tool_args.get("reply_reference") or "") + "\n" + person_candidates
    from src.maisaka.context.reply_memory import collect_reply_memory_references
    memory_references = tuple(collect_reply_memory_references(
        replyer_chat_history, getattr(tool_ctx.engine, '_active_logical_turn_id', '')
    ))
    previous_target_reply = _find_recent_reply_to_target(replyer_chat_history, target_message_id)
    if previous_target_reply:
        reply_tool_args = _with_duplicate_target_reply_reminder(reply_tool_args, previous_target_reply)
    try:
        tool_ctx.runtime._update_stage_status("Replyer", "生成可见回复")
        success, reply_result = await replyer.generate_reply_with_context(
            reply_reason=latest_thought,
            stream_id=tool_ctx.runtime.session_id,
            reply_message=target_message,
            chat_history=replyer_chat_history,
            memory_references=memory_references,
            reply_tool_args=reply_tool_args,
            sub_agent_runner=lambda system_prompt: _run_expression_selector(
                tool_ctx,
                system_prompt,
            ),
            log_reply=False,
        )
    except Exception as exc:
        logger.exception(
            f"{tool_ctx.runtime.log_prefix} 回复生成器执行异常: 目标消息编号={target_message_id} 异常={exc}"
        )
        await mark_continuity_blocked("generation_failed")
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "生成可见回复时发生异常。",
        )

    reply_text = reply_result.completion.response_text.strip() if success else ""

    if not reply_text:
        reply_result.monitor_detail = build_reply_monitor_detail(reply_result)
        await mark_continuity_blocked("generation_empty")
        reply_metadata = _build_monitor_metadata(reply_result)
        logger.warning(
            f"{tool_ctx.runtime.log_prefix} 回复生成器返回空文本: "
            f"目标消息编号={target_message_id} 错误信息={reply_result.error_message!r}"
        )
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "生成可见回复失败。",
            metadata=reply_metadata,
        )

    try:
        reply_text, post_process_options = await _invoke_before_post_process_hook(
            tool_ctx,
            reply_text,
            target_message_id,
            reply_tool_args,
        )
    except Exception as exc:
        logger.warning(f"{tool_ctx.runtime.log_prefix} 回复文本后处理前 Hook 调用失败，将使用默认策略: {exc}")
        post_process_options = {
            "skip_post_process": False,
            "enable_splitter": True,
            "enable_chinese_typo": True,
        }

    if not reply_text:
        reply_result.completion.response_text = ""
        await mark_continuity_blocked("postprocess_empty")
        reply_result.monitor_detail = build_reply_monitor_detail(reply_result)
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "回复文本后处理前 Hook 返回了空回复。",
            metadata=_build_monitor_metadata(reply_result),
        )

    try:
        if rich_reply_enabled:
            reply_items = await tool_ctx.post_process_rich_reply_message_items_async(
                reply_text,
                invocation_arguments,
                **post_process_options,
            )
        else:
            reply_items = await tool_ctx.post_process_reply_message_items_async(
                reply_text,
                **post_process_options,
            )
    except Exception as exc:
        reply_result.completion.response_text = reply_text
        reply_result.monitor_detail = build_reply_monitor_detail(reply_result)
        reply_metadata = _build_monitor_metadata(reply_result)
        logger.exception(f"{tool_ctx.runtime.log_prefix} 解析回复附件失败: {exc}")
        await mark_continuity_blocked("postprocess_failed")
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            f"解析回复附件失败：{exc}",
            metadata=reply_metadata,
        )
    reply_sequences = [item.sequence for item in reply_items]
    reply_segments = [build_visible_text_from_sequence(sequence) for sequence in reply_sequences]
    combined_reply_text = "".join(reply_segments)
    reply_result.completion.response_text = combined_reply_text
    reply_result.text_fragments = reply_segments
    reply_result.monitor_detail = build_reply_monitor_detail(reply_result)
    reply_metadata = _build_monitor_metadata(reply_result)
    sent_message_ids: list[str] = []
    delivered_segments: list[str] = []
    delivery_body_unknown = False
    send_results: list[dict[str, Any]] = []
    first_failure_outcome = ""
    first_failure_reason = ""
    claimed = False
    try:
        sent = False
        if tool_ctx.runtime.chat_stream.platform == CLI_PLATFORM_NAME:
            for index, segment in enumerate(reply_segments):
                render_cli_message(segment)
                send_results.append(
                    _build_send_result(
                        index=index,
                        segment=segment,
                        set_quote=effective_set_quote if index == 0 else False,
                        success=True,
                    )
                )
            sent = True
        else:
            if continuity is not None:
                # 已完成生成/预检/后处理；整个批次仅此一次原子 claim。
                try:
                    claimed = bool(reply_items) and await ledger_call("claim", continuity["session_id"],
                        continuity["user_id"], target_message_id, continuity["logical_turn_id"])
                except Exception as exc:
                    logger.warning("互动发送占用失败: %s", type(exc).__name__)
                    claimed = False
                if not claimed:
                    return tool_ctx.build_failure_result(invocation.tool_name, "目标已停止或已尝试发送，不补发。",
                        metadata={"pause_execution": True, "retryable": False})
            previous_sent_message = None
            for index, reply_item in enumerate(reply_items):
                reply_sequence = reply_item.sequence
                segment = reply_segments[index]
                segment_set_quote, segment_reply_message = _resolve_segment_reply_context(
                    index=index,
                    quote_previous=reply_item.quote_previous,
                    effective_set_quote=effective_set_quote,
                    target_message=target_message,
                    previous_sent_message=previous_sent_message,
                )
                segment_delivery_report: dict[str, Any] = {}
                sent_message = await send_service._send_to_target_with_message(
                    message_sequence=reply_sequence,
                    stream_id=tool_ctx.runtime.session_id,
                    processed_plain_text=segment,
                    set_reply=segment_set_quote,
                    reply_message=segment_reply_message,
                    selected_expressions=reply_result.selected_expression_ids or None,
                    typing=index > 0,
                    sync_to_maisaka_history=True,
                    maisaka_source_kind="guided_reply",
                    delivery_report=segment_delivery_report,
                    continuity_context=continuity,
                )
                sent = sent_message is not None
                if not sent:
                    first_failure_outcome = str(segment_delivery_report.get("outcome") or "delivery_unknown")
                    first_failure_reason = str(segment_delivery_report.get("reason") or "发送结果未确认")
                    send_results.append(
                        _build_send_result(
                            index=index,
                            segment="",  # 未送达正文不进入工具历史。
                            set_quote=segment_set_quote,
                            success=False,
                        )
                    )
                    break
                from src.platform_io.delivery_content import HISTORY_BLOCK_KEY
                if (sent_message.message_info.additional_config or {}).get(HISTORY_BLOCK_KEY) is True:
                    delivery_body_unknown = True
                    segment = ""
                else:
                    segment = sent_message.processed_plain_text
                delivered_segments.append(segment)
                sent_message_id = str(getattr(sent_message, "message_id", "") or "").strip()
                receipt_ids = segment_delivery_report.get("sent_message_ids", [])
                if receipt_ids:
                    sent_message_ids.extend(str(mid) for mid in receipt_ids if mid)
                else:
                    platform_id = str(getattr(sent_message, "platform_message_id", "") or "")
                    if platform_id:
                        sent_message_ids.append(platform_id)
                send_results.append(
                    _build_send_result(
                        index=index,
                        segment=segment,
                        set_quote=segment_set_quote,
                        success=True,
                        message_id=sent_message_id,
                    )
                )
                previous_sent_message = sent_message
                if segment_delivery_report.get("partial_delivery"):
                    sent = False
                    first_failure_outcome = "partial"
                    first_failure_reason = "仅部分分段已确认送达"
                    break
    except asyncio.CancelledError:
        sent = False
        first_failure_outcome = "delivery_unknown"
        raise
    except Exception:
        logger.exception(f"{tool_ctx.runtime.log_prefix} 发送文字消息时发生异常，目标消息编号={target_message_id}")
        sent = False
        first_failure_outcome = "delivery_unknown"
        first_failure_reason = "发送或发送后处理异常，无法确认最终状态"
    finally:
        if continuity is not None and claimed:
            # 只记真实回执，不把成功传输当成问题已回答；取消亦保留一次尝试。
            delivery = ("partial" if sent_message_ids and not sent else
                        "unknown" if delivery_body_unknown or not sent_message_ids and sent or
                        first_failure_outcome == "delivery_unknown" else
                        "sent" if sent else "failed")
            try:
                await ledger_call("record_result", continuity["session_id"], continuity["user_id"],
                    target_message_id, continuity["logical_turn_id"], delivery=delivery,
                    sent_message_ids=tuple(dict.fromkeys(sent_message_ids))[:32], reason_code="reply_batch_terminal")
            except Exception as exc:
                logger.warning("互动回执记录失败（不重发）: %s", type(exc).__name__)

    if not sent:
        # 部分成功也不能声称整条回复成功，更不能重放已送达的前缀。
        partial = any(item.get("success") is True for item in send_results)
        reason = first_failure_reason or "发送失败"
        outcome = first_failure_outcome or "delivery_failed"
        result_details = {
            "msg_id": target_message_id, "sent": partial, "partial_delivery": partial,
            "sent_message_ids": sent_message_ids, "send_results": send_results,
            "delivery_outcome": outcome, "policy_reason": reason,
            "outcome": "blocked_by_policy" if outcome == "policy_dropped" else outcome,
            "policy_silence": outcome == "policy_dropped", "retryable": False,
        }
        # 失败工具历史只保留送达证据，不能携带含生成正文的 monitor_detail。
        failure_metadata = {**result_details, "pause_execution": True}
        terminal_targets[target_message_id] = result_details
        try:
            from src.self_evolution.monitor import EvolutionMonitor, MetricEvent
            from src.self_evolution.policy import resolve_self_evolution_path
            import uuid as _uuid
            _is_content_violation = any(
                str(reason).startswith(p) or f"({p}" in str(reason)
                for p in ("pollution:", "pre_send_review:", "persona:", "group_policing")
            )
            EvolutionMonitor(resolve_self_evolution_path("data/self-evolution/monitor")).record(
                MetricEvent(
                    target="maisaka.replyer",
                    outcome="failure" if _is_content_violation else ("policy_dropped" if outcome == "policy_dropped" else outcome),
                    score=0.0 if _is_content_violation else (None if outcome == "policy_dropped" else 0.2),
                    metadata={"reason": str(reason)[:120]},
                    event_id=f"replyer:{_uuid.uuid4().hex}",
                )
            )
        except (OSError, ValueError) as exc:
            logger.warning("自演化监测记录失败: %s", type(exc).__name__)
        # 部分已送达也隔离整个目标，下一逻辑轮不能重放已确认的前缀。
        if outcome == "delivery_unknown" or partial:
            uncertain_targets[target_message_id] = result_details
        label = "策略跳过" if outcome == "policy_dropped" else "发送未完成"
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            f"{label}：回复{'部分已发送，剩余停止' if partial else '未确认发送成功'}（{outcome}）：{reason}。"
            "请勿补发或重放；超时不代表未送达。",
            structured_content=result_details, metadata=failure_metadata,
        )

    if tool_ctx.runtime.chat_stream.platform != CLI_PLATFORM_NAME:
        reply_segments = delivered_segments
        combined_reply_text = "".join(delivered_segments)
    reply_metadata["delivery_body_unknown"] = delivery_body_unknown
    target_user_info = target_message.message_info.user_info
    target_user_name = target_user_info.user_cardname or target_user_info.user_nickname or target_user_info.user_id
    bot_name = config_module.global_config.bot.nickname.strip() or "MaiSaka"

    if tool_ctx.runtime.chat_stream.platform == CLI_PLATFORM_NAME:
        tool_ctx.append_guided_reply_to_chat_history(combined_reply_text)
    reply_metadata["sent_message_ids"] = sent_message_ids
    reply_metadata["send_results"] = send_results
    tool_ctx.runtime.record_planner_reply()
    track_reply_effect = getattr(tool_ctx.runtime, "track_reply_effect", None)
    if track_reply_effect is not None and not delivery_body_unknown:
        try:
            await track_reply_effect(
                tool_call_id=invocation.call_id,
                target_message=target_message,
                set_quote=effective_set_quote,
                reply_text=combined_reply_text,
                reply_segments=reply_segments,
                planner_reasoning=latest_thought,
                tool_context={
                    "tool_name": invocation.tool_name,
                    "call_id": invocation.call_id,
                    "arguments": dict(invocation.arguments or {}),
                    "reasoning": latest_thought,
                },
                send_results=send_results,
                reply_metadata=reply_metadata,
                replyer_context_messages=replyer_chat_history,
            )
        except Exception as exc:
            logger.warning("回复已发送，效果追踪失败: %s", type(exc).__name__)
    return tool_ctx.build_success_result(
        invocation.tool_name,
        (f'"{bot_name}"已向"{target_user_name}"发送回复，但正文回执不可用。请勿补发。'
         if delivery_body_unknown else f'"{bot_name}"已向"{target_user_name}"发送了回复"{combined_reply_text}"'),
        structured_content={
            "msg_id": target_message_id,
            "set_quote": set_quote,
            "effective_set_quote": effective_set_quote,
            "reply_text": combined_reply_text,
            "reply_segments": reply_segments,
            "send_results": send_results,
            "target_user_name": target_user_name,
        },
        metadata=reply_metadata,
    )

from __future__ import annotations

import traceback
from typing import Tuple, Optional
import time

from src.common.logger import get_logger
from src.config.config import global_config, model_config
from src.plugin_system.apis import message_api
from src.llm_models.utils_model import LLMRequest


logger = get_logger("bc_reply_checker")


class BrainReplyChecker:
    """
    BrainChat 的轻量级回复检查器

    设计目标：
    - 与 BrainChat 主循环低耦合：只依赖 chat_id 和 message_api
    - 更宽松：只做少量简单检查，尽量不阻塞发送
    - 非 LLM：避免额外的模型调用开销
    """

    def __init__(self, chat_id: str, max_retries: int = 1) -> None:
        self.chat_id = chat_id
        # 比 PFC 更宽松：默认只允许 1 次重试
        self.max_retries = max_retries

    def _get_last_bot_text(self) -> Optional[str]:
        """
        获取当前会话中 Bot 最近一次发送的文本内容（如果有）。
        """
        try:
            # end_time 必须是数字，这里使用当前时间戳
            recent_messages = message_api.get_messages_by_time_in_chat(
                chat_id=self.chat_id,
                start_time=0,
                end_time=time.time(),
                limit=20,
                limit_mode="latest",
                filter_mai=False,
                filter_command=False,
                filter_intercept_message_level=1,
            )

            # 使用新配置中的 QQ 账号字段
            bot_id = str(global_config.bot.qq_account)
            for msg in reversed(recent_messages):
                try:
                    if str(getattr(msg.user_info, "user_id", "")) == bot_id:
                        text = getattr(msg, "processed_plain_text", None)
                        if text:
                            return str(text)
                except Exception:
                    # 单条消息解析失败不影响整体
                    continue
        except Exception as e:
            logger.warning(f"[{self.chat_id}] 获取最近 Bot 消息失败: {e}")

        return None

    def check(
        self,
        reply_text: str,
        retry_count: int = 0,
    ) -> Tuple[bool, str, bool]:
        """
        检查生成的回复是否合适（宽松版本）。

        返回:
            (suitable, reason, need_retry)
        """
        reply_text = reply_text or ""
        reply_text = reply_text.strip()

        if not reply_text:
            return False, "回复内容为空", retry_count < self.max_retries

        # 1. 与最近一条 Bot 消息做重复/高度相似检查
        last_bot_text = self._get_last_bot_text()
        if last_bot_text:
            last_bot_text = last_bot_text.strip()
            if reply_text == last_bot_text:
                logger.info(f"[{self.chat_id}] ReplyChecker: 与上一条 Bot 消息完全相同，尝试重试生成。")
                need_retry = retry_count < self.max_retries
                return (
                    not need_retry,  # 如果已经没有重试机会，就放行
                    "回复内容与上一条完全相同",
                    need_retry,
                )

        # 2. 粗略长度限制（过长时给一次重试机会，但整体仍偏宽松）
        max_len = 300
        if len(reply_text) > max_len:
            logger.info(f"[{self.chat_id}] ReplyChecker: 回复长度为 {len(reply_text)}，超过 {max_len} 字。")
            need_retry = retry_count < self.max_retries
            return (
                not need_retry,  # 超过长度但重试耗尽时也允许发送
                f"回复内容偏长（{len(reply_text)} 字）",
                need_retry,
            )

        # 其他情况全部放行
        return True, "通过检查", False


class BrainLLMReplyChecker:
    """
    使用 planner 模型做一次轻量 LLM 逻辑检查。

    - 不参与主决策，只作为“这句话现在说合适吗”的顾问
    - 至多触发一次重生成机会
    """

    def __init__(self, chat_id: str, max_retries: int = 1) -> None:
        self.chat_id = chat_id
        self.max_retries = max_retries
        # 复用 planner 模型配置
        self.llm = LLMRequest(model_set=model_config.model_task_config.planner, request_type="brain_reply_check")

    def _build_chat_history_text(self, limit: int = 15) -> str:
        """构造一段简短的聊天文本上下文，供 LLM 参考。"""
        try:
            recent_messages = message_api.get_messages_by_time_in_chat(
                chat_id=self.chat_id,
                start_time=0,
                end_time=time.time(),  # end_time 也必须是数字
                limit=limit,
                limit_mode="latest",
                filter_mai=False,
                filter_command=False,
                filter_intercept_message_level=1,
            )

            lines = []
            for msg in recent_messages:
                try:
                    user = getattr(msg.user_info, "user_nickname", None) or getattr(
                        msg.user_info, "user_id", "unknown"
                    )
                    text = getattr(msg, "processed_plain_text", "") or ""
                    if text:
                        lines.append(f"{user}: {text}")
                except Exception:
                    continue

            return "\n".join(lines) if lines else "（当前几乎没有聊天记录）"
        except Exception as e:
            logger.warning(f"[{self.chat_id}] 构造聊天上下文文本失败: {e}")
            return "（构造聊天上下文时出错）"

    async def check(self, reply_text: str, retry_count: int = 0) -> Tuple[bool, str, bool]:
        """
        使用 planner 模型检查一次回复是否合适。

        返回:
            (suitable, reason, need_retry)
        """
        reply_text = (reply_text or "").strip()
        if not reply_text:
            return False, "回复内容为空", retry_count < self.max_retries

        chat_history_text = self._build_chat_history_text()

        prompt = f"""你是一个聊天逻辑检查器，使用 JSON 评估下面这条回复是否适合当前上下文。

最近的聊天记录（按时间从旧到新）：
{chat_history_text}

候选回复：
{reply_text}

请综合考虑：
1. 是否和最近的聊天内容衔接自然
2. 是否明显重复、啰嗦或完全没必要
3. 是否有可能被认为不礼貌或不合时宜
4. 是否在当前时机继续说话会打扰对方（如果对方已经长时间没回，可以宽松一点，只要内容自然即可）

请只用 JSON 格式回答，不要输出多余文字，例如：
{{
  "suitable": true,
  "reason": "整体自然得体"
}}

其中：
- suitable: 是否建议发送 (true/false)
- reason: 你的简短理由
"""

        # 调试：展示用于 LLM 检查的 Prompt
        logger.info(f"[{self.chat_id}] BrainLLMReplyChecker Prompt:\n{prompt}")

        try:
            content, _ = await self.llm.generate_response_async(prompt=prompt)
            content = (content or "").strip()

            import json

            result = json.loads(content)
            suitable = bool(result.get("suitable", True))
            reason = str(result.get("reason", "未提供原因")).strip() or "未提供原因"
        except Exception as e:
            logger.warning(f"[{self.chat_id}] LLM 回复检查失败，将默认放行: {e}")
            logger.debug(f"[{self.chat_id}] LLM 返回内容: {content[:200] if content else '(空)'}")
            logger.debug(traceback.format_exc())
            return True, "LLM 检查失败，默认放行", False

        if not suitable and retry_count < self.max_retries:
            # 给一次重新生成机会
            return False, reason, True

        # 不适合但已经没有重试机会时，只记录原因但不强制拦截
        return True, reason, False



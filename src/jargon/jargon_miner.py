import time
import json
from typing import List
from json_repair import repair_json

from src.common.logger import get_logger
from src.common.database.database_model import Jargon
from src.llm_models.utils_model import LLMRequest
from src.config.config import model_config
from src.chat.message_receive.chat_stream import get_chat_manager
from src.chat.utils.chat_message_builder import (
    build_anonymous_messages,
    get_raw_msg_by_timestamp_with_chat_inclusive,
)
from src.chat.utils.prompt_builder import Prompt, global_prompt_manager


logger = get_logger("jargon")


def _init_prompt() -> None:
    prompt_str = """
**聊天内容**
{chat_str}

请从上面这段聊天内容中提取"可能是黑话"的候选项（黑话/俚语/网络缩写/口头禅）。
- 必须为对话中真实出现过的短词或短语
- 必须是你无法理解含义的词语，或者出现频率较高的词语
- 必须是这几种类别之一：英文或中文缩写、中文拼音短语、字母数字混合、意义不明但频繁的词汇
- 排除：人名、@、明显的表情/图片占位、纯标点、常规功能词（如的、了、呢、啊等）
- 每个词条长度建议 2-8 个字符（不强制），尽量短小
- 合并重复项，去重

分类规则：
- p（拼音缩写）：由字母或字母和汉字构成的，疑似拼音简写词，例如：nb、yyds、xswl
- c（中文缩写）：中文词语的缩写，用几个汉字概括一个词汇或含义，例如：社死、内卷
- e（英文缩写）：英文词语的缩写，用英文字母概括一个词汇或含义，例如：CPU、GPU、API

以 JSON 数组输出，元素为对象（严格按以下结构）：
[
  {{"content": "词条", "raw_content": "包含该词条的完整句子", "type": "p"}},
  {{"content": "词条2", "raw_content": "包含该词条的完整句子", "type": "c"}}
]

现在请输出：
"""
    Prompt(prompt_str, "extract_jargon_prompt")


_init_prompt()


class JargonMiner:
    def __init__(self, chat_id: str) -> None:
        self.chat_id = chat_id
        self.last_learning_time: float = time.time()
        # 频率控制，可按需调整
        self.min_messages_for_learning: int = 20
        self.min_learning_interval: float = 30  

        self.llm = LLMRequest(
            model_set=model_config.model_task_config.utils,
            request_type="jargon.extract",
        )

    def should_trigger(self) -> bool:
        # 冷却时间检查
        if time.time() - self.last_learning_time < self.min_learning_interval:
            return False

        # 拉取最近消息数量是否足够
        recent_messages = get_raw_msg_by_timestamp_with_chat_inclusive(
            chat_id=self.chat_id,
            timestamp_start=self.last_learning_time,
            timestamp_end=time.time(),
        )
        return bool(recent_messages and len(recent_messages) >= self.min_messages_for_learning)

    async def run_once(self) -> None:
        try:
            if not self.should_trigger():
                return

            chat_stream = get_chat_manager().get_stream(self.chat_id)
            if not chat_stream:
                return

            # 拉取学习窗口内的消息
            messages = get_raw_msg_by_timestamp_with_chat_inclusive(
                chat_id=self.chat_id,
                timestamp_start=self.last_learning_time,
                timestamp_end=time.time(),
                limit=20,
            )
            if not messages:
                return

            chat_str: str = await build_anonymous_messages(messages)
            if not chat_str.strip():
                return

            prompt: str = await global_prompt_manager.format_prompt(
                "extract_jargon_prompt",
                chat_str=chat_str,
            )

            response, _ = await self.llm.generate_response_async(prompt, temperature=0.2)
            if not response:
                return
            
            logger.info(f"jargon提取提示词: {prompt}")
            logger.info(f"jargon提取结果: {response}")

            # 解析为JSON
            entries: List[dict] = []
            try:
                resp = response.strip()
                parsed = None
                if resp.startswith("[") and resp.endswith("]"):
                    parsed = json.loads(resp)
                else:
                    repaired = repair_json(resp)
                    if isinstance(repaired, str):
                        parsed = json.loads(repaired)
                    else:
                        parsed = repaired

                if isinstance(parsed, dict):
                    parsed = [parsed]

                if not isinstance(parsed, list):
                    return

                for item in parsed:
                    if not isinstance(item, dict):
                        continue
                    content = str(item.get("content", "")).strip()
                    raw_content = str(item.get("raw_content", "")).strip()
                    type_str = str(item.get("type", "")).strip().lower()
                    
                    # 验证type是否为有效值
                    if type_str not in ["p", "c", "e"]:
                        type_str = "p"  # 默认值
                    
                    if content:
                        entries.append({
                            "content": content,
                            "raw_content": raw_content,
                            "type": type_str
                        })
            except Exception as e:
                logger.error(f"解析jargon JSON失败: {e}; 原始: {response}")
                return

            if not entries:
                return

            # 去重并写入DB（按 chat_id + content 去重）
            # 使用content作为去重键
            seen = set()
            uniq_entries = []
            for entry in entries:
                content_key = entry["content"]
                if content_key not in seen:
                    seen.add(content_key)
                    uniq_entries.append(entry)
            
            saved = 0
            updated = 0
            for entry in uniq_entries:
                content = entry["content"]
                raw_content = entry["raw_content"]
                type_str = entry["type"]
                try:
                    query = (
                        Jargon.select()
                        .where((Jargon.chat_id == self.chat_id) & (Jargon.content == content))
                    )
                    if query.exists():
                        obj = query.get()
                        try:
                            obj.count = (obj.count or 0) + 1
                        except Exception:
                            obj.count = 1
                        # 更新raw_content和type（如果为空或需要更新）
                        if raw_content and not obj.raw_content:
                            obj.raw_content = raw_content
                        if type_str and not obj.type:
                            obj.type = type_str
                        obj.save()
                        updated += 1
                    else:
                        Jargon.create(
                            content=content,
                            raw_content=raw_content,
                            type=type_str,
                            chat_id=self.chat_id,
                            is_global=False,
                            count=1
                        )
                        saved += 1
                except Exception as e:
                    logger.error(f"保存jargon失败: chat_id={self.chat_id}, content={content}, err={e}")
                    continue

            if saved or updated:
                logger.info(f"jargon写入: 新增 {saved} 条，更新 {updated} 条，chat_id={self.chat_id}")
                self.last_learning_time = time.time()
        except Exception as e:
            logger.error(f"JargonMiner 运行失败: {e}")


class JargonMinerManager:
    def __init__(self) -> None:
        self._miners: dict[str, JargonMiner] = {}

    def get_miner(self, chat_id: str) -> JargonMiner:
        if chat_id not in self._miners:
            self._miners[chat_id] = JargonMiner(chat_id)
        return self._miners[chat_id]


miner_manager = JargonMinerManager()


async def extract_and_store_jargon(chat_id: str) -> None:
    miner = miner_manager.get_miner(chat_id)
    await miner.run_once()



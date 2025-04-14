import time
from loguru import logger
from ..schedule.schedule_generator import bot_schedule
from ..models.utils_model import LLM_request

from ..config.config import global_config
from ..chat.chat_stream import ChatStream
from .mode_classical import WillingManager
from ..chat.utils import get_recent_group_detailed_plain_text


import re
from src.common.logger import get_module_logger, CHAT_STYLE_CONFIG, LogConfig

# 定义日志配置
chat_config = LogConfig(
    # 使用消息发送专用样式
    console_format=CHAT_STYLE_CONFIG["console_format"],
    file_format=CHAT_STYLE_CONFIG["file_format"],
)

# 配置主程序日志格式
logger = get_module_logger("llm_willing", config=chat_config)

class WillingManager(WillingManager):

    def __init__(self):
        super().__init__()
        self.model_v3 = LLM_request(model=global_config.llm_normal, temperature=0.3)

    async def change_reply_willing_received(self, chat_stream: ChatStream, is_mentioned_bot: bool = False, config=None,
                                            is_emoji: bool = False, interested_rate: float = 0, sender_id: str = None,
                                            **kwargs) -> float:
        stream_id = chat_stream.stream_id
        if chat_stream.group_info and config:
            if chat_stream.group_info.group_id not in config.talk_allowed_groups:
                reply_probability = 0
                return reply_probability

        current_date = time.strftime("%Y-%m-%d", time.localtime())
        current_time = time.strftime("%H:%M:%S", time.localtime())
        chat_in_group = True
        chat_talking_prompt = ""
        if stream_id:
            chat_talking_prompt = get_recent_group_detailed_plain_text(
                stream_id, limit=5, combine=True
            )
            if chat_stream.group_info:
                if str(config.BOT_QQ) in chat_talking_prompt:
                    pass
                    # logger.info(f"{chat_talking_prompt}")
                    # logger.info(f"bot在群聊中5条内发过言，启动llm计算回复概率")
                else:
                    return self.default_change_reply_willing_received(
                        chat_stream=chat_stream,
                        is_mentioned_bot=is_mentioned_bot,
                        config=config,
                        is_emoji=is_emoji,
                        interested_rate=interested_rate,
                        sender_id=sender_id,
                    )
            else:
                chat_in_group = False
                chat_talking_prompt = chat_talking_prompt
                # print(f"\033[1;34m[调试]\033[0m 已从数据库获取群 {group_id} 的消息记录:{chat_talking_prompt}")

        # if is_mentioned_bot:
        #     return 1.0
        prompt = f"""
        假设你正在查看一个群聊，你在这个群聊里的网名叫{global_config.BOT_NICKNAME}，你还有很多别名: {"/".join(global_config.BOT_ALIAS_NAMES)}，
        现在群里聊天的内容是{chat_talking_prompt}，
        今天是{current_date}，现在是{current_time}。
        综合群内的氛围和你自己之前的发言，给出你认为**最新的消息**需要你回复的概率，数值在0到1之间。请注意，群聊内容杂乱，很多时候对话连续，但很可能不是在和你说话。
        如果最新的消息和你之前的发言在内容上连续，或者提到了你的名字或者称谓，将其视作明确指向你的互动，给出高于0.8的概率。如果现在是睡眠时间，直接概率为0。如果话题内容与你之前不是紧密相关，请不要给出高于0.1的概率。
        请注意是判断概率，而不是编写回复内容，
        仅输出在0到1区间内的概率值，不要给出你的判断依据。
        """

        # 非群聊的意愿管理 未来可能可以用对话缓冲区来确定合适的回复时机
        if not chat_in_group:
            prompt = f"""
        假设你在和网友聊天，网名叫{global_config.BOT_NICKNAME}，你还有很多别名: {"/".join(global_config.BOT_ALIAS_NAMES)}，
        现在你和朋友私聊的内容是{chat_talking_prompt}，
        今天是{current_date}，现在是{current_time}。
        综合以上的内容，给出你认为最新的消息是在和你交流的概率，数值在0到1之间。如果现在是个人休息时间，直接概率为0，请注意是决定是否需要发言，而不是编写回复内容，
        仅输出在0到1区间内的概率值，不要给出你的判断依据。
        """
        content_check, reasoning_check, _ = await self.model_v3.generate_response(prompt)
        # logger.info(f"{prompt}")
        logger.info(f"{content_check} {reasoning_check}")
        probability = self.extract_marked_probability(content_check)
        # 兴趣系数修正 无关激活效率太高，暂时停用，待新记忆系统上线后调整
        probability += (interested_rate * 0.25)
        probability = min(1.0, probability)
        if probability <= 0.1:
            probability = min(0.03, probability)
        if probability >= 0.8:
            probability = max(probability, 0.90)

        # 当前表情包理解能力较差，少说就少错
        if is_emoji:
            probability *= 0.1

        return probability

    @staticmethod
    def extract_marked_probability(text):
        """提取带标记的概率值 该方法主要用于测试微调prompt阶段"""
        text = text.strip()
        pattern = r'##PROBABILITY_START##(.*?)##PROBABILITY_END##'
        match = re.search(pattern, text, re.DOTALL)
        if match:
            prob_str = match.group(1).strip()
            # 处理百分比（65% → 0.65）
            if '%' in prob_str:
                return float(prob_str.replace('%', '')) / 100
            # 处理分数（2/3 → 0.666...）
            elif '/' in prob_str:
                numerator, denominator = map(float, prob_str.split('/'))
                return numerator / denominator
            # 直接处理小数
            else:
                return float(prob_str)

        percent_match = re.search(r'(\d{1,3})%', text)  # 65%
        decimal_match = re.search(r'(0\.\d+|1\.0+)', text)  # 0.65
        fraction_match = re.search(r'(\d+)/(\d+)', text)  # 2/3
        try:
            if percent_match:
                prob = float(percent_match.group(1)) / 100
            elif decimal_match:
                prob = float(decimal_match.group(0))
            elif fraction_match:
                numerator, denominator = map(float, fraction_match.groups())
                prob = numerator / denominator
            else:
                return 0  # 无匹配格式

            # 验证范围是否合法
            if 0 <= prob <= 1:
                return prob
            return 0
        except (ValueError, ZeroDivisionError):
            return 0

    def default_change_reply_willing_received(self, chat_stream: ChatStream, is_mentioned_bot: bool = False, config=None,
                                            is_emoji: bool = False, interested_rate: float = 0, sender_id: str = None,
                                            **kwargs) -> float:

        current_willing = self.chat_reply_willing.get(chat_stream.stream_id, 0)
        interested_rate = interested_rate * config.response_interested_rate_amplifier
        if interested_rate > 0.4:
            current_willing += interested_rate - 0.3
        if is_mentioned_bot and current_willing < 1.0:
            current_willing += 1
        elif is_mentioned_bot:
            current_willing += 0.05
        if is_emoji:
            current_willing *= 0.5
        self.chat_reply_willing[chat_stream.stream_id] = min(current_willing, 3.0)
        reply_probability = min(max((current_willing - 0.5), 0.01) * config.response_willing_amplifier * 2, 1)

        return reply_probability

from src.common.logger import get_module_logger, LogConfig, RELATION_STYLE_CONFIG
from .chat_stream import ChatStream
import math
from bson.decimal128 import Decimal128
from .person_info import person_info_manager
import time

relationship_config = LogConfig(
    # 使用关系专用样式
    console_format=RELATION_STYLE_CONFIG["console_format"],
    file_format=RELATION_STYLE_CONFIG["file_format"],
)
logger = get_module_logger("rel_manager", config=relationship_config)

class RelationshipManager:
    def __init__(self):
        self.positive_feedback_dict = {}  # 正反馈系统

    def positive_feedback_sys(self, person_id, value, label: str, stance: str):
        """正反馈系统"""

        positive_list = [
            "开心",
            "惊讶",
            "害羞",
        ]

        negative_list = [
            "愤怒",
            "悲伤",
            "恐惧",
            "厌恶",
        ]

        if person_id not in self.positive_feedback_dict:
            self.positive_feedback_dict[person_id] = 0

        if label in positive_list and stance != "反对":
            if 7 > self.positive_feedback_dict[person_id] >= 0:
                self.positive_feedback_dict[person_id] += 1
            elif self.positive_feedback_dict[person_id] < 0:
                self.positive_feedback_dict[person_id] = 0
                return value
        elif label in negative_list and stance != "支持":
            if -7 < self.positive_feedback_dict[person_id] <= 0:
                self.positive_feedback_dict[person_id] -= 1
            elif self.positive_feedback_dict[person_id] > 0:
                self.positive_feedback_dict[person_id] = 0
                return value
        else:
            return value

        gain_coefficient = [1.0, 1.1, 1.2, 1.4, 1.7, 1.9, 2.0]
        value *= gain_coefficient[abs(self.positive_feedback_dict[person_id])-1]
        if abs(self.positive_feedback_dict[person_id]) - 1:
            logger.info(f"触发增益，当前增益系数：{gain_coefficient[abs(self.positive_feedback_dict[person_id])-1]}")

        return value


    async def calculate_update_relationship_value(self, chat_stream: ChatStream, label: str, stance: str) -> None:
        """计算并变更关系值
        新的关系值变更计算方式：
            将关系值限定在-1000到1000
            对于关系值的变更，期望：
                1.向两端逼近时会逐渐减缓
                2.关系越差，改善越难，关系越好，恶化越容易
                3.人维护关系的精力往往有限，所以当高关系值用户越多，对于中高关系值用户增长越慢
                4.连续正面或负面情感会正反馈
        """
        stancedict = {
            "支持": 0,
            "中立": 1,
            "反对": 2,
        }
        
        valuedict = {
            "开心": 1.5,
            "愤怒": -2.0,
            "悲伤": -0.5,
            "惊讶": 0.6,
            "害羞": 2.0,
            "平静": 0.3,
            "恐惧": -1.5,
            "厌恶": -1.0,
            "困惑": 0.5,
        }

        person_id = person_info_manager.get_person_id(chat_stream.user_info.platform, chat_stream.user_info.user_id)
        data = {
            "platform" : chat_stream.user_info.platform,
            "user_id" : chat_stream.user_info.user_id,
            "nickname" : chat_stream.user_info.user_nickname,
            "konw_time" : int(time.time())
        }
        old_value = await person_info_manager.get_value(person_id, "relationship_value")
        old_value = self.ensure_float(old_value, person_id)

        if old_value > 1000:
            old_value = 1000
        elif old_value < -1000:
            old_value = -1000

        value = valuedict[label]
        if old_value >= 0:
            if valuedict[label] >= 0 and stancedict[stance] != 2:
                value = value * math.cos(math.pi * old_value / 2000)
                if old_value > 500:
                    rdict = await person_info_manager.get_specific_value_list("relationship_value", lambda x: x > 700)
                    high_value_count = len(rdict)
                    if old_value > 700:
                        value *= 3 / (high_value_count + 2)  # 排除自己
                    else:
                        value *= 3 / (high_value_count + 3)
            elif valuedict[label] < 0 and stancedict[stance] != 0:
                value = value * math.exp(old_value / 2000)
            else:
                value = 0
        elif old_value < 0:
            if valuedict[label] >= 0 and stancedict[stance] != 2:
                value = value * math.exp(old_value / 2000)
            elif valuedict[label] < 0 and stancedict[stance] != 0:
                value = value * math.cos(math.pi * old_value / 2000)
            else:
                value = 0

        value = self.positive_feedback_sys(person_id, value, label, stance)

        level_num = self.calculate_level_num(old_value + value)
        relationship_level = ["厌恶", "冷漠", "一般", "友好", "喜欢", "暧昧"]
        logger.info(
            f"当前关系: {relationship_level[level_num]}, "
            f"关系值: {old_value:.2f}, "
            f"当前立场情感: {stance}-{label}, "
            f"变更: {value:+.5f}"
        )

        await person_info_manager.update_one_field(person_id, "relationship_value", old_value + value, data)

    async def build_relationship_info(self, person) -> str:
        person_id = person_info_manager.get_person_id(person[0], person[1])
        relationship_value = await person_info_manager.get_value(person_id, "relationship_value")
        level_num = self.calculate_level_num(relationship_value)
        relationship_level = ["厌恶", "冷漠", "一般", "友好", "喜欢", "暧昧"]
        relation_prompt2_list = [
            "厌恶回应",
            "冷淡回复",
            "保持理性",
            "愿意回复",
            "积极回复",
            "无条件支持",
        ]

        return (
            f"你对昵称为'({person[1]}){person[2]}'的用户的态度为{relationship_level[level_num]}，"
            f"回复态度为{relation_prompt2_list[level_num]}，关系等级为{level_num}。"
        )

    def calculate_level_num(self, relationship_value) -> int:
        """关系等级计算"""
        if -1000 <= relationship_value < -227:
            level_num = 0
        elif -227 <= relationship_value < -73:
            level_num = 1
        elif -73 <= relationship_value < 227:
            level_num = 2
        elif 227 <= relationship_value < 587:
            level_num = 3
        elif 587 <= relationship_value < 900:
            level_num = 4
        elif 900 <= relationship_value <= 1000:
            level_num = 5
        else:
            level_num = 5 if relationship_value > 1000 else 0
        return level_num

    def ensure_float(elsf, value, person_id):
        """确保返回浮点数，转换失败返回0.0"""
        if isinstance(value, float):
            return value
        try:
            return float(value.to_decimal() if isinstance(value, Decimal128) else value)
        except (ValueError, TypeError, AttributeError):
            logger.warning(f"[关系管理] {person_id}值转换失败（原始值：{value}），已重置为0")
            return 0.0

relationship_manager = RelationshipManager()

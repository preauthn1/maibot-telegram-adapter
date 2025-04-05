from dataclasses import dataclass
from typing import Dict, List

@dataclass
class Personality:
    """人格特质类"""
    openness: float  # 开放性
    conscientiousness: float  # 尽责性
    extraversion: float  # 外向性
    agreeableness: float  # 宜人性
    neuroticism: float  # 神经质
    bot_nickname: str  # 机器人昵称
    personality_core: str  # 人格核心特点
    personality_detail: List[str]  # 人格细节描述
    
    def to_dict(self) -> Dict:
        """将人格特质转换为字典格式"""
        return {
            "openness": self.openness,
            "conscientiousness": self.conscientiousness,
            "extraversion": self.extraversion,
            "agreeableness": self.agreeableness,
            "neuroticism": self.neuroticism,
            "bot_nickname": self.bot_nickname,
            "personality_core": self.personality_core,
            "personality_detail": self.personality_detail
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Personality':
        """从字典创建人格特质实例"""
        return cls(**data) 
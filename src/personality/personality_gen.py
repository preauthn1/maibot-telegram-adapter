import os
import json
import sys
from typing import Optional, List

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from src.personality.offline_llm import LLM_request_off
from src.common.logger import get_module_logger
from src.personality.personality import Personality

logger = get_module_logger("personality_gen")

class PersonalityGenerator:
    """人格生成器类"""
    def __init__(self, bot_nickname: str):
        self.bot_nickname = bot_nickname
        self.llm = LLM_request_off()
        self.personality: Optional[Personality] = None
        self.save_path = os.path.join("data", "personality")
        
        # 确保保存目录存在
        os.makedirs(self.save_path, exist_ok=True)
    
    def personality_exists(self) -> bool:
        """检查是否已存在该机器人的人格文件"""
        file_path = os.path.join(self.save_path, f"{self.bot_nickname}_personality.per")
        return os.path.exists(file_path)
    
    async def generate_personality(
        self,
        personality_core: str,
        personality_detail: List[str],
        height: int,
        weight: int,
        age: int,
        gender: str,
        appearance: str,
        interests: List[str],
        others: List[str]
    ) -> Optional[Personality]:
        """根据配置生成人格特质"""
        # 检查是否已存在
        if self.personality_exists():
            logger.info(f"机器人 {self.bot_nickname} 的人格文件已存在，跳过生成")
            return await self.load_personality()
            
        # 构建提示文本
        prompt = f"""你是一个心理学家，专职心理测量和大五人格研究。请根据以下信息分析并给出这个人的大五人格特质评分。
每个特质的分数范围是0到1之间的小数，请确保返回标准的JSON格式。

机器人信息：
- 昵称：{self.bot_nickname}
- 性格核心的特质：{personality_core}
- 性格细节：{', '.join(personality_detail)}
- 身高：{height}cm
- 体重：{weight}kg
- 年龄：{age}岁
- 性别：{gender}
- 外貌：{appearance}
- 兴趣爱好：{', '.join(interests)}
- 其他信息：{', '.join(others)}
请只返回如下JSON格式数据（不要包含任何其他文字）：
{{
    "openness": 0.x,
    "conscientiousness": 0.x,
    "extraversion": 0.x,
    "agreeableness": 0.x,
    "neuroticism": 0.x
}}"""
        
        response, _ = await self.llm.generate_response_async(prompt)
        try:
            # 尝试清理响应文本，只保留JSON部分
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].strip()
                
            traits = json.loads(json_str)
            
            # 验证所有必需的字段是否存在
            required_fields = ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]
            if not all(field in traits for field in required_fields):
                raise ValueError("缺少必需的人格特质字段")
                
            # 验证数值是否在合理范围内
            for field in required_fields:
                if not 0 <= traits[field] <= 1:
                    traits[field] = max(0, min(traits[field], 1))
            
            self.personality = Personality(
                **traits,
                bot_nickname=self.bot_nickname
            )
            await self.save_personality()
            return self.personality
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}\n响应内容: {response}")
            raise
        except Exception as e:
            logger.error(f"生成人格特质失败: {e}")
            raise
    
    async def save_personality(self) -> None:
        """保存人格特质到文件"""
        if not self.personality:
            raise ValueError("没有可保存的人格特质")
            
        file_path = os.path.join(self.save_path, f"{self.bot_nickname}_personality.per")
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.personality.to_dict(), f, ensure_ascii=False, indent=4)
            logger.info(f"人格特质已保存到: {file_path}")
        except Exception as e:
            logger.error(f"保存人格特质失败: {e}")
            raise
    
    async def load_personality(self) -> Optional[Personality]:
        """从文件加载人格特质"""
        file_path = os.path.join(self.save_path, f"{self.bot_nickname}_personality.per")
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.personality = Personality.from_dict(data)
                return self.personality
        except Exception as e:
            logger.error(f"加载人格特质失败: {e}")
        return None

async def main():
    """主函数，用于测试人格生成"""
    # 创建人格生成器实例
    generator = PersonalityGenerator("麦麦")
    
    # 生成或加载人格
    personality = await generator.generate_personality(
        personality_core="对世界抱着善意和好奇，愿意尝试新奇事物",
        personality_detail=[
            "你会刷小红书",
            "你会刷贴吧",
            "学习心理学和脑科学",
            "你会刷b站，对ACG文化感兴趣",
            "有时候有些搞怪",
        ],
        height=160,
        weight=45,
        age=20,
        gender="女",
        appearance="有着橙色短发",
        interests=["摄影", "绘画"],
        others=["是一个大二女大学生"]
    )
    
    if personality:
        logger.info("人格特质生成成功：")
        logger.info(f"开放性: {personality.openness}")
        logger.info(f"尽责性: {personality.conscientiousness}")
        logger.info(f"外向性: {personality.extraversion}")
        logger.info(f"宜人性: {personality.agreeableness}")
        logger.info(f"神经质: {personality.neuroticism}")
    else:
        logger.error("人格特质生成失败")

if __name__ == "__main__":
    import asyncio
    import platform
    
    if platform.system() == 'Windows':
        # Windows平台特殊处理
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    finally:
        # 确保所有待处理的任务都完成
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        
        # 运行一次以处理取消的任务
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()

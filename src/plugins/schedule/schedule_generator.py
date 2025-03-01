import datetime
import os
from typing import List, Dict
from .schedule_llm_module import LLMModel
from dotenv import load_dotenv
from ...common.database import Database  # 使用正确的导入语法
from ..chat.config import global_config


# import sys
# sys.path.append("C:/GitHub/MegMeg-bot")  # 添加项目根目录到 Python 路径
# from src.plugins.schedule.schedule_llm_module import LLMModel
# from src.common.database import Database  # 使用正确的导入语法

# 获取当前文件的绝对路径
#TODO: 这个好几个地方用需要封装
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
load_dotenv(os.path.join(root_dir, '.env'))

Database.initialize(
            host= os.getenv("MONGODB_HOST"),
            port= int(os.getenv("MONGODB_PORT")),
            db_name=  os.getenv("DATABASE_NAME"),
            username= os.getenv("MONGODB_USERNAME"),
            password= os.getenv("MONGODB_PASSWORD"),
            auth_source=os.getenv("MONGODB_AUTH_SOURCE")
        )

class ScheduleGenerator:
    def __init__(self):
        self.llm_scheduler = LLMModel(model_name="Pro/deepseek-ai/DeepSeek-V3")
        self.db = Database.get_instance()
        
        today = datetime.datetime.now()
        tomorrow = datetime.datetime.now() + datetime.timedelta(days=1)
        yesterday = datetime.datetime.now() - datetime.timedelta(days=1)
        
        self.today_schedule_text, self.today_schedule = self.generate_daily_schedule(target_date=today)
        
        self.tomorrow_schedule_text, self.tomorrow_schedule = self.generate_daily_schedule(target_date=tomorrow,read_only=True)
        self.yesterday_schedule_text, self.yesterday_schedule = self.generate_daily_schedule(target_date=yesterday,read_only=True)
            
    def generate_daily_schedule(self, target_date: datetime.datetime = None,read_only:bool = False) -> Dict[str, str]:
        if target_date is None:
            target_date = datetime.datetime.now()
            
        date_str = target_date.strftime("%Y-%m-%d")
        weekday = target_date.strftime("%A")
        

        schedule_text = str
        
        existing_schedule = self.db.db.schedule.find_one({"date": date_str})
        if existing_schedule:
            print(f"{date_str}的日程已存在:")
            schedule_text = existing_schedule["schedule"]
            # print(self.schedule_text)

        elif read_only == False:
            print(f"{date_str}的日程不存在，准备生成新的日程。")
            prompt = f"""我是{global_config.BOT_NICKNAME}，一个曾经学习地质,现在学习心理学和脑科学的女大学生，喜欢刷qq，贴吧，知乎和小红书，请为我生成{date_str}（{weekday}）的日程安排，包括：
            1. 早上的学习和工作安排
            2. 下午的活动和任务
            3. 晚上的计划和休息时间
            请按照时间顺序列出具体时间点和对应的活动，用一个时间点而不是时间段来表示时间，用逗号,隔开时间与活动，格式为"时间,活动"，例如"08:00,起床"。"""
            
            schedule_text, _ = self.llm_scheduler.generate_response(prompt)
            # print(self.schedule_text)
            self.db.db.schedule.insert_one({"date": date_str, "schedule": schedule_text})
        else:
            print(f"{date_str}的日程不存在。")
            schedule_text = "忘了"

            return schedule_text,None
            
        schedule_form = self._parse_schedule(schedule_text)
        return schedule_text,schedule_form
    
    def _parse_schedule(self, schedule_text: str) -> Dict[str, str]:
        """解析日程文本，转换为时间和活动的字典"""
        schedule_dict = {}
            # 按行分割日程文本
        lines = schedule_text.strip().split('\n')
        for line in lines:
            # print(line)
            if ',' in line:
                # 假设格式为 "时间: 活动"
                time_str, activity = line.split(',', 1)
                # print(time_str)
                # print(activity)
                schedule_dict[time_str.strip()] = activity.strip()
        return schedule_dict
    
    def _parse_time(self, time_str: str) -> str:
        """解析时间字符串，转换为时间"""
        return datetime.datetime.strptime(time_str, "%H:%M")
    
    def get_current_task(self) -> str:
        """获取当前时间应该进行的任务"""
        current_time = datetime.datetime.now().strftime("%H:%M")
        
        # 找到最接近当前时间的任务
        closest_time = None
        min_diff = float('inf')
        
        # 检查今天的日程
        for time_str in self.today_schedule.keys():
            diff = abs(self._time_diff(current_time, time_str))
            if closest_time is None or diff < min_diff:
                closest_time = time_str
                min_diff = diff
        
        # 检查昨天的日程中的晚间任务
        if self.yesterday_schedule:
            for time_str in self.yesterday_schedule.keys():
                if time_str >= "20:00":  # 只考虑晚上8点之后的任务
                    # 计算与昨天这个时间点的差异（需要加24小时）
                    diff = abs(self._time_diff(current_time, time_str))
                    if diff < min_diff:
                        closest_time = time_str
                        min_diff = diff
                        return closest_time, self.yesterday_schedule[closest_time]
        
        if closest_time:
            return closest_time, self.today_schedule[closest_time]
        return "摸鱼"
    
    def _time_diff(self, time1: str, time2: str) -> int:
        """计算两个时间字符串之间的分钟差"""
        t1 = datetime.datetime.strptime(time1, "%H:%M")
        t2 = datetime.datetime.strptime(time2, "%H:%M")
        diff = int((t2 - t1).total_seconds() / 60)
        # 考虑时间的循环性
        if diff < -720:
            diff += 1440  # 加一天的分钟
        elif diff > 720:
            diff -= 1440  # 减一天的分钟
        # print(f"时间1[{time1}]: 时间2[{time2}]，差值[{diff}]分钟")
        return diff
    
    def print_schedule(self):
        """打印完整的日程安排"""
                
        print("\n=== 今日日程安排 ===")
        for time_str, activity in self.today_schedule.items():
            print(f"时间[{time_str}]: 活动[{activity}]")
        print("==================\n")

# def main():
#     # 使用示例
#     scheduler = ScheduleGenerator()
#     # new_schedule = scheduler.generate_daily_schedule()
#     scheduler.print_schedule()
#     print("\n当前任务：")
#     print(scheduler.get_current_task())
    
#     print("昨天日程：")
#     print(scheduler.yesterday_schedule)
#     print("今天日程：")
#     print(scheduler.today_schedule)
#     print("明天日程：")
#     print(scheduler.tomorrow_schedule)

# if __name__ == "__main__":
#     main() 
    
bot_schedule = ScheduleGenerator()
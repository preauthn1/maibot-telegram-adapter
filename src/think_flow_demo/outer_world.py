#定义了来自外部世界的信息
import asyncio
from datetime import datetime
from src.common.database import db
from .offline_llm import LLMModel
#存储一段聊天的大致内容
class Talking_info:
    def __init__(self,chat_id):
        self.chat_id = chat_id
        self.talking_message = []
        self.talking_message_str = ""
        self.talking_summary = ""
        self.last_message_time = None  # 记录最新消息的时间
        
        self.llm_summary = LLMModel("Pro/Qwen/Qwen2.5-7B-Instruct")  
        
    def update_talking_message(self):
        #从数据库取最近30条该聊天流的消息
        messages = db.messages.find({"chat_id": self.chat_id}).sort("time", -1).limit(15)
        self.talking_message = []
        self.talking_message_str = ""
        for message in messages:
            self.talking_message.append(message)
            self.talking_message_str += message["detailed_plain_text"]

    async def update_talking_summary(self,new_summary=""):
        #基于已经有的talking_summary，和新的talking_message，生成一个summary
        prompt = f"聊天内容：{self.talking_message_str}\n\n"
        prompt += f"以上是群里在进行的聊天，请你对这个聊天内容进行总结，总结内容要包含聊天的大致内容，以及聊天中的一些重要信息，记得不要分点，不要太长，精简的概括成一段文本\n\n"
        prompt += f"总结："
        self.talking_summary, reasoning_content = await self.llm_summary.generate_response_async(prompt)
    
class SheduleInfo:
    def __init__(self):
        self.shedule_info = ""

class OuterWorld:
    def __init__(self):
        self.talking_info_list = [] #装的一堆talking_info
        self.shedule_info = "无日程"
        self.interest_info = "麦麦你好"
        
        self.outer_world_info = ""
        
        self.start_time = int(datetime.now().timestamp())
        
        self.llm_summary = LLMModel("Qwen/Qwen2.5-32B-Instruct")   
        

    async def open_eyes(self):
        while True:
            await asyncio.sleep(60)
            print("更新所有聊天信息")
            await self.update_all_talking_info()
            print("更新outer_world_info")
            await self.update_outer_world_info()
            
            print(self.outer_world_info)
            
            for talking_info in self.talking_info_list:
                # print(talking_info.talking_message_str)
                # print(talking_info.talking_summary)
                pass
    
    async def update_outer_world_info(self):
        print("总结当前outer_world_info")
        all_talking_summary = ""
        for talking_info in self.talking_info_list:
            all_talking_summary += talking_info.talking_summary
        
        prompt = f"聊天内容：{all_talking_summary}\n\n"
        prompt += f"以上是多个群里在进行的聊天，请你对所有聊天内容进行总结，总结内容要包含聊天的大致内容，以及聊天中的一些重要信息，记得不要分点，不要太长，精简的概括成一段文本\n\n"
        prompt += f"总结："
        self.outer_world_info, reasoning_content = await self.llm_summary.generate_response_async(prompt)
    
            
    async def update_talking_info(self,chat_id):
        # 查找现有的talking_info
        talking_info = next((info for info in self.talking_info_list if info.chat_id == chat_id), None)
        
        if talking_info is None:
            print("新聊天流")
            talking_info = Talking_info(chat_id)
            talking_info.update_talking_message()
            await talking_info.update_talking_summary()
            self.talking_info_list.append(talking_info)
        else:
            print("旧聊天流")
            talking_info.update_talking_message()
            await talking_info.update_talking_summary()
    
    async def update_all_talking_info(self):
        all_streams = db.chat_streams.find({})
        update_tasks = []
        
        for data in all_streams:         
            stream_id = data.get("stream_id")
            # print(stream_id)
            last_active_time = data.get("last_active_time")
            
            if last_active_time > self.start_time or 1:
                update_tasks.append(self.update_talking_info(stream_id))
        
        # 并行执行所有更新任务
        if update_tasks:
            await asyncio.gather(*update_tasks)

outer_world = OuterWorld()

if __name__ == "__main__":
    asyncio.run(outer_world.open_eyes())

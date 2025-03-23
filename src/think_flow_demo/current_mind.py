from .outer_world import outer_world
import asyncio
from .offline_llm import LLMModel

class CuttentState:
    def __init__(self):
        self.willing = 0
        self.mood = 'TODO'
        self.current_state_info = ""
        
class InnerWorld:
    def __init__(self):
        self.inner_world_info = ""
        self.current_state : CuttentState = CuttentState()


class BRain:
    def __init__(self):
        self.current_mind = ""
        self.past_mind = []
        self.inner_world = InnerWorld()
        self.llm_model = LLMModel("Pro/Qwen/Qwen2.5-7B-Instruct")
        if not self.current_mind:
            self.current_mind = "你是麦麦,曾经是一个学习地质的女大学生，现在学习心理学和脑科学，你会刷贴吧,你现在正在浏览qq群，想着qq群里发生的事情，人们在谈论什么，以及和你有什么关系，你应该怎样在qq群中回复和发言。现在请麦麦你继续思考"

    async def brain_start_working(self):
        while True:
            await self.do_a_thinking()
            await asyncio.sleep(10)
    
    async def do_a_thinking(self):
        print("麦麦脑袋转起来了")
        current_thinking = self.current_mind
        outer_world_info = self.build_outer_world_info()
        inner_world_info = self.build_inner_world_info(self.inner_world)
        current_state_info = self.build_current_state_info(self.inner_world.current_state)
        
        
        # prompt += f"这是你当前的脑内状态{current_state_info}\n\n"
        prompt = f"这是你刚刚接触的内容：{outer_world_info}\n\n"
        # prompt += f"这是你当前的脑内状态{inner_world_info}\n\n"
        prompt += f"这是你之前的想法{current_thinking}\n\n"
        
        prompt += f"现在你接下去继续思考，产生新的想法，不要分点输出，输出连贯的内心独白，不要太长，注重当前的思考:"
        
        reponse, reasoning_content = await self.llm_model.generate_response_async(prompt)
        
        self.update_current_mind(reponse)
        
        self.current_mind = reponse
        print(f"麦麦的脑内状态：{self.current_mind}")
    
    async def do_after_reply(self,reply_content,chat_talking_prompt):
        print("麦麦脑袋转起来了")
        current_thinking = self.current_mind
        outer_world_info = self.build_outer_world_info()
        inner_world_info = self.build_inner_world_info(self.inner_world)
        current_state_info = self.build_current_state_info(self.inner_world.current_state)
        
        
        # prompt += f"这是你当前的脑内状态{current_state_info}\n\n"
        prompt = f"这是你刚刚接触的内容：{outer_world_info}\n\n"
        # prompt += f"这是你当前的脑内状态{inner_world_info}\n\n"
        prompt += f"这是你之前想要回复的内容：{chat_talking_prompt}\n\n"
        prompt += f"这是你之前的想法{current_thinking}\n\n"
        prompt += f"这是你自己刚刚回复的内容{reply_content}\n\n"
        prompt += f"现在你接下去继续思考，产生新的想法，不要分点输出，输出连贯的内心独白:"
        
        reponse, reasoning_content = await self.llm_model.generate_response_async(prompt)
        
        self.update_current_mind(reponse)
        
        self.current_mind = reponse
        print(f"麦麦的脑内状态：{self.current_mind}")
        
    def update_current_state_from_current_mind(self):
        self.inner_world.current_state.willing += 0.01
        
        
    def build_current_state_info(self,current_state):
        current_state_info = current_state.current_state_info
        return current_state_info
    
    def build_inner_world_info(self,inner_world):
        inner_world_info = inner_world.inner_world_info
        return inner_world_info
    
    def build_outer_world_info(self):
        outer_world_info = outer_world.outer_world_info
        return outer_world_info

    def update_current_mind(self,reponse):
        self.past_mind.append(self.current_mind)
        self.current_mind = reponse


brain = BRain()

async def main():
    # 创建两个任务
    brain_task = asyncio.create_task(brain.brain_start_working())
    outer_world_task = asyncio.create_task(outer_world.open_eyes())
    
    # 等待两个任务
    await asyncio.gather(brain_task, outer_world_task)

if __name__ == "__main__":
    asyncio.run(main())


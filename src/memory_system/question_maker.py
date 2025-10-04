import time
import random
from src.chat.utils.chat_message_builder import get_raw_msg_before_timestamp_with_chat, build_readable_messages
from src.common.database.database_model import MemoryConflict
from src.config.config import global_config


class QuestionMaker:
    def __init__(self, chat_id: str,context: str = ""):
        self.chat_id = chat_id
        self.context = context

    def get_context(self):
        latest_30_msgs = get_raw_msg_before_timestamp_with_chat(
            chat_id=self.chat_id,
            timestamp=time.time(),
            limit=30,
        )   

        all_dialogue_prompt_str = build_readable_messages(
            latest_30_msgs,
            replace_bot_name=True,
            timestamp_mode="normal_no_YMD",
        )
        return all_dialogue_prompt_str


    async def get_all_conflicts(self):
        conflicts = list(MemoryConflict.select())
        return conflicts
    
    async def get_un_answered_conflict(self):
        conflicts = await self.get_all_conflicts()
        return [conflict for conflict in conflicts if not conflict.answer]

    async def get_random_unanswered_conflict(self):
        conflicts = await self.get_un_answered_conflict()
        return random.choice(conflicts)

    async def make_question(self):
        conflict = await self.get_random_unanswered_conflict()
        question = conflict.conflict_content
        conflict_context = conflict.context
        chat_context = self.get_context()

        return question, conflict_context
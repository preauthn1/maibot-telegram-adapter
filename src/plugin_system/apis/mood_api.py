import asyncio
import traceback
import time
from typing import Optional, Union, Dict, List, TYPE_CHECKING, Tuple

from src.chat.message_receive import message
from src.common.logger import get_logger
from src.mood.mood_manager import mood_manager

logger = get_logger("mood_api")


async def get_mood_by_chat_id(chat_id: str) -> Optional[float]:
    chat_mood = mood_manager.get_mood_by_chat_id(chat_id)
    mood = asyncio.create_task(chat_mood.get_mood())    
    return mood
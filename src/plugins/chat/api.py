from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from .bot import chat_bot
from .message_cq import MessageRecvCQ
from .message_base import UserInfo, GroupInfo
from src.common.logger import get_module_logger

logger = get_module_logger("chat_api")

app = FastAPI()


class MessageRequest(BaseModel):
    message_id: int
    user_info: Dict[str, Any]
    raw_message: str
    group_info: Optional[Dict[str, Any]] = None
    reply_message: Optional[Dict[str, Any]] = None
    platform: str = "api"


@app.post("/api/message")
async def handle_message(message: MessageRequest):
    try:
        user_info = UserInfo(
            user_id=message.user_info["user_id"],
            user_nickname=message.user_info["user_nickname"],
            user_cardname=message.user_info.get("user_cardname"),
            platform=message.platform,
        )

        group_info = None
        if message.group_info:
            group_info = GroupInfo(
                group_id=message.group_info["group_id"],
                group_name=message.group_info.get("group_name"),
                platform=message.platform,
            )

        message_cq = MessageRecvCQ(
            message_id=message.message_id,
            user_info=user_info,
            raw_message=message.raw_message,
            group_info=group_info,
            reply_message=message.reply_message,
            platform=message.platform,
        )

        await chat_bot.message_process(message_cq)
        return {"status": "success"}
    except Exception as e:
        logger.exception("API处理消息时出错")
        raise HTTPException(status_code=500, detail=str(e)) from e

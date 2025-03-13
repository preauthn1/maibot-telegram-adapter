from .config import global_config
from .relationship_manager import relationship_manager


def get_user_nickname(user_id: int) -> str:
    if user_id == "all":
        return "全体成员"
    if int(user_id) == int(global_config.BOT_QQ):
        return global_config.BOT_NICKNAME
    #     print(user_id)
    return relationship_manager.get_name(user_id)


def get_user_cardname(user_id: int) -> str:
    if int(user_id) == int(global_config.BOT_QQ):
        return global_config.BOT_NICKNAME
    #     print(user_id)
    return ""


def get_groupname(group_id: int) -> str:
    return f"群{group_id}"

"""话题群白名单匹配测试。

ja-netfilter(-1001680975844) 是 forum 话题群，入站 session_key 形如
``-1001680975844::tg-topic::mt=7310786``。而 ``chat_id_aliases`` 只处理
``-100``/``100``/裸号三种写法，不剥离话题后缀，导致配置里写裸群号时
两个别名集合无交集 —— 话题群消息会被白名单静默丢弃。

这类"配了却不生效"的问题在日志里只有 debug 级输出，极易被忽略，
因此用测试固定住。
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.utils import (  # noqa: E402
    build_topic_group_id,
    chat_id_aliases,
)

FORUM_CHAT = "-1009000000005"
TOPIC_ID = 7310786


def test_topic_session_key_matches_bare_group_id() -> None:
    """话题群 session_key 必须能命中配置里的裸群号。"""

    session_key = build_topic_group_id(FORUM_CHAT, TOPIC_ID)

    assert chat_id_aliases(session_key) & chat_id_aliases(FORUM_CHAT)


def test_topic_session_key_matches_signless_form() -> None:
    """去掉 -100 前缀的写法同样要能命中。"""

    session_key = build_topic_group_id(FORUM_CHAT, TOPIC_ID)

    assert chat_id_aliases(session_key) & chat_id_aliases("9000000005")


def test_plain_group_alias_unchanged() -> None:
    """非话题群的别名行为不受影响。"""

    aliases = chat_id_aliases("-1009000000005")

    assert "-1009000000005" in aliases
    assert "9000000005" in aliases


def test_different_topics_share_group_alias() -> None:
    """同群不同话题都应命中同一个群号配置。"""

    first = build_topic_group_id(FORUM_CHAT, 111)
    second = build_topic_group_id(FORUM_CHAT, 222)
    target = chat_id_aliases(FORUM_CHAT)

    assert chat_id_aliases(first) & target
    assert chat_id_aliases(second) & target


def test_other_group_still_rejected() -> None:
    """不能因为放宽话题匹配就把别的群也匹配上。"""

    session_key = build_topic_group_id(FORUM_CHAT, TOPIC_ID)

    assert not (chat_id_aliases(session_key) & chat_id_aliases("-1009000000006"))

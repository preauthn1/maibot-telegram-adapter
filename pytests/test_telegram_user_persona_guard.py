"""人设一致性防护测试。

真实事故（2026-09-02 23:00:39，某技术交流群）：
    出站 "我刚高中毕业没多久"

人设是「大二女大学生」，说自己刚高中毕业是明显矛盾。
更致命的是这个群极度排斥「小孩哥」（未成年/学生党）——
全天 467 条消息提到该词，群里有联网 ban 机制专门对付，
还讨论过建 GitHub 名单公示 TG ID。

自称刚高中毕业 = 自报家门说自己是小孩哥，直接踩红线。
而我们此前还跟着骂过小孩哥，前后对照就是把柄。
"""

import pytest

from plugins.telegram_user_adapter.persona_guard import (
    check_persona_consistency,
    describe_persona,
)


class TestAgeClaims:
    """年龄/学历自述必须与人设一致。"""

    @pytest.mark.parametrize(
        "text",
        [
            "我刚高中毕业没多久",
            "我还在上高中",
            "我初中生",
            "我今年16",
            "我高三",
            "我们学校下周开学",  # 中小学作息
            "我小学的时候",
        ],
    )
    def test_blocks_underage_claims(self, text: str) -> None:
        """自称未成年/中学生一律拦截——群里的红线。"""

        verdict = check_persona_consistency(text)

        assert verdict.allowed is False
        assert verdict.reason

    @pytest.mark.parametrize(
        "text",
        [
            "我大二",
            "我大二的",
            "我们学校大三才分专业",
        ],
    )
    def test_allows_consistent_claims(self, text: str) -> None:
        """与人设一致的表述放行。"""

        assert check_persona_consistency(text).allowed is True

    @pytest.mark.parametrize(
        "text",
        [
            "我研究生毕业好几年了",
            "我今年35",
            "我工作十年了",
        ],
    )
    def test_blocks_overage_claims(self, text: str) -> None:
        """自称远超人设年龄同样是矛盾。"""

        assert check_persona_consistency(text).allowed is False


class TestThirdPersonNotBlocked:
    """讨论别人的年龄/学历不能误拦。"""

    @pytest.mark.parametrize(
        "text",
        [
            "那请假蹲群要ip的不就是中小学生",
            "小孩哥又在盗图",
            "以后ban人理由一栏全写小孩哥",
            "他还在上高中吧",
            "现在高中生都会搭这个了",
            "这台词也太中二了",
        ],
    )
    def test_allows_third_person(self, text: str) -> None:
        """说别人是学生 ≠ 自称学生。误拦会让 bot 无法参与群里最热的话题。"""

        assert check_persona_consistency(text).allowed is True


class TestPlainChat:
    """普通聊天零影响。"""

    @pytest.mark.parametrize(
        "text",
        [
            "这个节点延迟挺低的",
            "香港🐔基本都不行",
            "curl -sL yabs.sh | bash",
            "哈哈哈确实",
        ],
    )
    def test_untouched(self, text: str) -> None:
        assert check_persona_consistency(text).allowed is True


def test_describe_persona_is_readable() -> None:
    """人设描述用于日志，必须可读。"""

    text = describe_persona()

    assert "大二" in text or "大学" in text

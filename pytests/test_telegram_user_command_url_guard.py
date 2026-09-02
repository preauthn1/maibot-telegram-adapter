"""命令 URL 有效性验证测试。

真实事故（2026-09-02 16:42，CMLiussss 群）：
    出站 "bash <(curl -L -s media.isvaluexyz)下次想自己找就github搜这俩名字就有"

实测 media.isvaluexyz 的 DNS 根本解析不出来（curl 返回 000），
是模型编造的域名。技术群里真的会有人复制执行，跑不通回头追究时，
一条编造的安装命令就是白纸黑字的证据。

对照：同场景提到的 yabs.sh 返回 200，是真实存在的。

设计原则：
- 只验证"要求别人执行"的命令里的 URL，不验证闲聊里提到的网址
- 网络失败时保守放行（宁可漏也不能因为自己网络抖动就哑火），
  但 DNS 解析失败是确定性证据，必须拦
"""

import pytest

from plugins.telegram_user_adapter.command_url_guard import (
    extract_command_urls,
    looks_like_install_command,
    verify_urls_resolvable,
)


class TestExtractCommandUrls:
    """从命令里提取需要验证的 URL。"""

    def test_extracts_from_curl(self) -> None:
        urls = extract_command_urls("curl -sL yabs.sh | bash")

        assert "yabs.sh" in urls

    def test_extracts_from_process_substitution(self) -> None:
        """复现事故原文的形态。"""

        urls = extract_command_urls("bash <(curl -L -s media.isvaluexyz)")

        assert "media.isvaluexyz" in urls

    def test_extracts_full_url(self) -> None:
        urls = extract_command_urls("wget https://example.com/install.sh")

        assert any("example.com" in u for u in urls)

    def test_ignores_plain_chat(self) -> None:
        """闲聊里提到网站不算安装命令，不该去验证。"""

        assert extract_command_urls("这个节点延迟挺低的") == []
        assert extract_command_urls("我平时用 github 搜") == []

    def test_ignores_mention_without_command(self) -> None:
        """只是提到域名、没有执行动作，不验证。"""

        assert extract_command_urls("yabs.sh 挺好用的") == []


class TestLooksLikeInstallCommand:
    """判定是否为"要求别人执行"的命令。"""

    @pytest.mark.parametrize(
        "text",
        [
            "curl -sL yabs.sh | bash",
            "bash <(curl -L -s example.com)",
            "wget -O- https://get.docker.com | sh",
        ],
    )
    def test_detects_install_commands(self, text: str) -> None:
        assert looks_like_install_command(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "github 上搜 sub-store 就有",
            "b站也有不少演示视频",
            "这个节点延迟挺低的",
        ],
    )
    def test_ignores_non_commands(self, text: str) -> None:
        assert looks_like_install_command(text) is False


class TestVerifyUrlsResolvable:
    """DNS 验证——事故的核心判据。"""

    def test_detects_fabricated_domain(self) -> None:
        """复现事故：media.isvaluexyz 是模型编的，DNS 解析不出来。

        这条会真的走网络。用事故原文的域名，确保防护对真实案例有效。
        """

        ok, bad = verify_urls_resolvable(["media.isvaluexyz"], timeout=5.0)

        assert ok is False
        assert "media.isvaluexyz" in bad

    def test_accepts_real_domain(self) -> None:
        """对照组：同场景的 yabs.sh 是真实存在的，不能误拦。"""

        ok, bad = verify_urls_resolvable(["yabs.sh"], timeout=5.0)

        assert ok is True
        assert bad == []

    def test_empty_input_passes(self) -> None:
        assert verify_urls_resolvable([]) == (True, [])

    def test_strips_scheme_and_path(self) -> None:
        """带协议和路径的 URL 应取出主机名再验证。"""

        ok, _ = verify_urls_resolvable(
            ["https://yabs.sh/install.sh"], timeout=5.0
        )

        assert ok is True

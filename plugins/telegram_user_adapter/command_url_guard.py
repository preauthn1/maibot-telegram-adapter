"""安装命令 URL 有效性验证。

真实事故（2026-09-02 16:42，CMLiussss 技术交流群）：

    出站  bash <(curl -L -s media.isvaluexyz)下次想自己找就github搜这俩名字就有

实测 ``media.isvaluexyz`` 的 DNS 根本解析不出来（curl 返回 000），
是模型顺口编的域名。同场景提到的 ``yabs.sh`` 返回 200、真实存在，
说明模型并非不知道真域名，只是生成时把 ``media.is/valuexyz``
之类的路径揉成了一个不存在的主机名。

危害等级：技术群里真的有人复制执行。跑不通之后回头看，
一条编造的安装命令是**白纸黑字的证据**——比"反应太快"这种
主观印象难辩解得多。

设计取舍：
- 只验证「要求别人执行」的命令，闲聊里提到网址不碰
- DNS 解析失败 = 确定性证据，拦截
- 网络超时/自身网络异常 = 保守放行，不能因为自己网络抖动就哑火
- 验证要有超时上限，绝不能拖慢发送链路
"""

from typing import List, Tuple

import re
import socket

# 执行动作：只有出现这些才算「要求别人跑」。
#
# 单纯提到域名（"yabs.sh 挺好用的"）不验证——那是闲聊，
# 验证它既无意义又会拖慢发送。
_EXEC_VERB = re.compile(
    r"\b(?:curl|wget)\b[^|;\n]*"
    r"|\bbash\s*<\("
    r"|\|\s*(?:bash|sh)\b"
    r"|\bgit\s+clone\b"
    r"|\bdocker\s+(?:run|pull)\b",
    re.IGNORECASE,
)

# 从命令片段里抽主机名/URL。
#
# 覆盖三种写法：
#   curl -sL yabs.sh          裸域名
#   bash <(curl -L -s a.b.c)  进程替换，右括号要排除
#   wget https://x.com/y.sh   完整 URL
_URL_IN_CMD = re.compile(
    r"https?://[^\s)|;'\"]+"
    r"|\b(?:[a-z0-9][a-z0-9-]{0,61}\.)+[a-z]{2,}\b(?:/[^\s)|;'\"]*)?",
    re.IGNORECASE,
)

# 这些不是要访问的目标，是命令参数或常见词
_NOT_A_HOST = frozenset({
    "e.g", "i.e", "vs.js", "index.js", "package.json",
})


def looks_like_install_command(text: str) -> bool:
    """判断文本是否在要求别人执行安装命令。

    Args:
        text: 待判定文本。

    Returns:
        bool: 是安装/执行类命令时返回 ``True``。
    """

    if not text:
        return False
    return bool(_EXEC_VERB.search(text))


def extract_command_urls(text: str) -> List[str]:
    """提取安装命令里需要验证的 URL/主机名。

    只在文本确实是执行类命令时才提取；闲聊里提到的网址返回空列表。

    Args:
        text: 待处理文本。

    Returns:
        List[str]: 待验证的 URL 或主机名列表。
    """

    if not looks_like_install_command(text):
        return []

    found: List[str] = []
    for match in _URL_IN_CMD.finditer(text):
        raw = match.group(0).rstrip(".,;)")
        if not raw or raw.lower() in _NOT_A_HOST:
            continue
        if raw not in found:
            found.append(raw)
    return found


def _hostname_of(url: str) -> str:
    """从 URL 或裸域名里取主机名。"""

    stripped = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    return stripped.split("/", 1)[0].split(":", 1)[0]


def verify_urls_resolvable(
    urls: List[str],
    *,
    timeout: float = 3.0,
) -> Tuple[bool, List[str]]:
    """验证 URL 的主机名能否解析。

    只做 DNS 解析，不发 HTTP 请求：
    DNS 失败是确定性证据（域名压根不存在），而 HTTP 状态码会受
    墙、限流、临时故障影响，用它判断会产生大量误拦。

    Args:
        urls: 待验证的 URL 列表。
        timeout: 单次解析超时秒数。

    Returns:
        Tuple[bool, List[str]]: ``(是否全部可解析, 解析失败的主机名)``。
    """

    if not urls:
        return True, []

    original = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    bad: List[str] = []
    try:
        for url in urls:
            host = _hostname_of(url)
            if not host:
                continue
            try:
                socket.getaddrinfo(host, None)
            except socket.gaierror:
                # 解析不出来 = 域名不存在，这是确定性证据
                bad.append(host)
            except (socket.timeout, OSError):
                # 自身网络问题，保守放行——不能因为本机网络抖动就哑火
                continue
    finally:
        socket.setdefaulttimeout(original)

    return (not bad), bad

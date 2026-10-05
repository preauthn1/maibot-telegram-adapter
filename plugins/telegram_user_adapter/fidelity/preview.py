# SPDX-License-Identifier: GPL-3.0-only
# Modified 2026-10-06; see PORT_NOTICES.md.
"""默认不抓取；已有 Telegram 网页预览才表示发送方同意展示。

无预览不能区分“发送方关闭”与“未生成”，因此绝不自动补抓。
可选 fetch_public_preview 只接受明确 sender_enabled=True；DNS 检查绑定连接。
"""
from html.parser import HTMLParser
from typing import Any, Dict
from urllib.parse import urljoin, urlsplit
import asyncio
import ipaddress
import socket


def public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    # 同时拒绝 IPv4 映射、6to4、Teredo 等可能绕过路由预期的地址。
    if isinstance(address, ipaddress.IPv6Address) and (address.ipv4_mapped or address.sixtofour or address.teredo):
        return False
    return address.is_global and not address.is_multicast and not address.is_reserved


def validate_url(url: str) -> Any:
    if len(url) > 4096 or any(ord(ch) < 33 for ch in url) or "\\" in url:
        raise ValueError("无效预览 URL")
    value = urlsplit(url)
    if value.scheme not in ("http", "https") or not value.hostname or value.username is not None or value.password is not None:
        raise ValueError("不允许的预览 URL")
    if value.port not in (None, 80, 443):
        raise ValueError("预览端口不受支持")
    if "%" in value.hostname:
        raise ValueError("不允许带作用域的地址")
    try:
        ipaddress.ip_address(value.hostname)
    except ValueError:
        pass
    else:
        if not public_address(value.hostname):
            raise ValueError("预览地址非公网")
    return value


def existing_preview(message: Any) -> Dict[str, str]:
    if getattr(message, "no_webpage", False):
        return {}
    page = getattr(getattr(message, "media", None), "webpage", None)
    if page is None:
        return {}
    url = getattr(page, "url", "") or ""
    try:
        validate_url(url)
    except ValueError:
        return {}
    return {key: str(getattr(page, key, "") or "")[:1024]
            for key in ("url", "title", "description", "site_name")}


class MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.result = {}
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            values = dict(attrs)
            name = values.get("property") or values.get("name")
            if name in ("og:title", "og:description", "og:site_name", "description"):
                self.result[name] = str(values.get("content") or "")[:1024]

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.result["title"] = (self.result.get("title", "") + data)[:1024]


def guarded_resolver():
    from aiohttp.abc import AbstractResolver
    from aiohttp.resolver import DefaultResolver

    class PublicResolver(AbstractResolver):
        def __init__(self):
            self.inner = DefaultResolver()

        async def resolve(self, host, port=0, family=socket.AF_UNSPEC):
            rows = await self.inner.resolve(host, port, family)
            if not rows or not all(public_address(row["host"]) for row in rows):
                raise ValueError("DNS 含非公网地址")
            return rows

        async def close(self):
            await self.inner.close()

    return PublicResolver()


async def fetch_public_preview(url: str, *, sender_enabled: bool = False) -> Dict[str, str]:
    if sender_enabled is not True:
        return {}  # 在 URL 解析、DNS、网络之前执行
    import aiohttp
    resolver = guarded_resolver()
    try:
        async with asyncio.timeout(8):
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False, limit=1),
                timeout=aiohttp.ClientTimeout(total=6), trust_env=False,
                cookie_jar=aiohttp.DummyCookieJar(), auto_decompress=False,
                headers={"Accept": "text/html", "Accept-Encoding": "identity"},
                max_line_size=8192, max_field_size=8192,
            ) as session:
                for hop in range(4):
                    validate_url(url)
                    async with session.get(url, allow_redirects=False, proxy=None) as response:
                        if response.status in (301, 302, 303, 307, 308):
                            location = response.headers.get("Location")
                            if not location or hop == 3:
                                raise ValueError("预览重定向过多/无目标")
                            next_url = urljoin(url, location)
                            validate_url(next_url)
                            url = next_url
                            continue
                        if response.status != 200 or "text/html" not in response.headers.get("Content-Type", "").lower():
                            return {}
                        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                            return {}  # 不解压不可信压缩包
                        data = bytearray()
                        async for chunk in response.content.iter_chunked(8192):
                            data.extend(chunk[:262144 - len(data)])
                            if len(data) >= 262144:
                                break
                        parser = MetaParser()
                        parser.feed(data.decode("utf-8", errors="replace"))
                        return {"url": url, **parser.result}
    finally:
        await resolver.close()
    return {}

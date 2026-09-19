"""Telegram 真人账号登录：仅内存中保存临时凭据，不启动机器人。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Literal
from urllib.parse import urlparse

import asyncio
import hashlib
import os
import re
import secrets
import tempfile
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError, FloodWaitError, PasswordHashInvalidError, PhoneCodeExpiredError,
    PhoneCodeInvalidError, PhoneNumberBannedError, PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession
import socks
import tomlkit

from src.webui.dependencies import require_auth

CONFIG_PATH = Path(__file__).resolve().parents[3] / 'plugins/telegram_user_adapter/config.toml'
TTL = 600
TIMEOUT = 75  # 覆盖连接 + PhoneMigrate 切换数据中心 + 重试的总时长
MASK = '********'
PLUGIN_ID = 'preauthn1.telegram-user-adapter'
ALLOWED_ORIGINS = {'https://maibot.080933.xyz', 'http://127.0.0.1:8001', 'http://localhost:8001'}

async def guard(request: Request, response: Response, owner: str = Depends(require_auth)) -> str:
    response.headers['Cache-Control'] = 'no-store'
    if request.method != 'GET':
        if request.headers.get('origin') not in ALLOWED_ORIGINS or request.headers.get('x-telegram-onboarding') != '1':
            raise HTTPException(403, '请求来源或操作确认头无效')
    return hashlib.sha256(owner.encode()).hexdigest()

router = APIRouter(prefix='/api/webui/telegram-onboarding', tags=['Telegram 登录'], dependencies=[Depends(guard)])

class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    api_id: int | None = Field(default=None, gt=0, le=2147483647)
    api_hash: SecretStr | None = Field(default=None, min_length=32, max_length=32)
    phone: str = Field(default='', max_length=16)
    session_string: SecretStr = Field(default=SecretStr(''), max_length=4096)
    mode: Literal['phone', 'import'] = 'phone'

class Verification(BaseModel):
    model_config = ConfigDict(extra='forbid')
    value: SecretStr = Field(min_length=1, max_length=256)

@dataclass
class Attempt:
    owner: str
    client: Any
    account: Dict[str, Any]
    expires: float
    digest: str
    step: str = 'code'
    phone_code_hash: str = ''
    failures: int = 0
    timer: Any = None


def load_config() -> Any:
    if CONFIG_PATH.is_symlink() or not CONFIG_PATH.is_file():
        raise HTTPException(409, '适配器配置不存在或路径不安全')
    return tomlkit.parse(CONFIG_PATH.read_text(encoding='utf-8'))


def fixed_parameters() -> Dict[str, Any]:
    account = load_config()['telegram_account']
    return {key: str(account.get(key, '')) for key in ('proxy_url', 'device_model', 'system_version', 'app_version')}


def resolve_credentials(body: Credentials, saved: Any) -> Dict[str, Any]:
    # API ID / Hash 是一对；禁止把新 ID 与已保存的 Hash 混用。
    if (body.api_id is None) != (body.api_hash is None):
        raise HTTPException(400, '覆盖 API 凭据时必须同时提供 API ID 和 API Hash；省略两项则复用服务器配置')
    api_id = body.api_id if body.api_id is not None else saved.get('api_id')
    secret = body.api_hash.get_secret_value() if body.api_hash is not None else saved.get('api_hash', '')
    if not isinstance(api_id, int) or isinstance(api_id, bool) or not 0 < api_id <= 2147483647 or not isinstance(secret, str) or not re.fullmatch('[a-fA-F0-9]{32}', secret):
        raise HTTPException(400, 'API 凭据缺失或格式无效，请在服务器配置有效的 API ID 和 API Hash，或同时提供两项')
    return {'api_id': api_id, 'api_hash': secret}


def make_client(account: Dict[str, Any], session: str) -> Any:
    p = urlparse(account['proxy_url'])
    proxy = None
    if account['proxy_url']:
        types = {'socks5': socks.SOCKS5, 'socks5h': socks.SOCKS5, 'socks4': socks.SOCKS4, 'http': socks.HTTP}
        if p.scheme not in types or not p.hostname or not p.port:
            raise ValueError('invalid fixed proxy')
        proxy = (types[p.scheme], p.hostname, p.port, True, p.username, p.password)
    return TelegramClient(StringSession(session), account['api_id'], account['api_hash'],
                          proxy=proxy, device_model=account['device_model'],
                          system_version=account['system_version'], app_version=account['app_version'],
                          # request_retries 至少为 2：Telegram 常对新号返回 PhoneMigrateError，
                          # Telethon 会消耗一次 attempt 去切换数据中心，重试次数不足时它只会抛出
                          # 裸 ValueError('Request was unsuccessful N time(s)')，真正的原因全部丢失。
                          connection_retries=2, request_retries=2, flood_sleep_threshold=0,
                          receive_updates=False, timeout=15)


def account_digest() -> str:
    return hashlib.sha256(tomlkit.dumps({'telegram_account': load_config()['telegram_account']}).encode()).hexdigest()


def persist(attempt: Attempt, session: str, phone: str) -> None:
    # 并发编辑账号时拒绝覆盖；其他分区总是以磁盘最新内容为准。
    if account_digest() != attempt.digest:
        raise HTTPException(409, '账号配置已被其他操作修改，请取消后重新登录')
    doc = load_config()
    # 只更新授权相关字段；保留未知字段（包括已有 client_id）和固定设置原值。
    for key, value in {'api_id': attempt.account['api_id'], 'api_hash': attempt.account['api_hash'], 'session_string': session, 'phone': phone}.items():
        doc['telegram_account'][key] = value
    payload = tomlkit.dumps(doc)
    fd, temporary = tempfile.mkstemp(prefix='.telegram-login-', dir=CONFIG_PATH.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, CONFIG_PATH)
        if CONFIG_PATH.read_text(encoding='utf-8') != payload:
            raise RuntimeError('persistence verification failed')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class LoginManager:
    def __init__(self) -> None:
        self.attempts: Dict[str, Attempt] = {}
        self.lock = asyncio.Lock()
        self.last_start = 0.0

    async def remove(self, key: str) -> None:
        # 先同步摘除并清空敏感字段：即使随后的断开被取消，槽位也已释放，
        # 不会把后续登录挡在 429 上直到 TTL 到期。
        item = self.attempts.pop(key, None)
        if not item:
            return
        if item.timer:
            item.timer.cancel()
        item.account.clear()
        item.phone_code_hash = ''
        try:
            # shield：本任务已被取消时，断开动作仍要跑完，避免泄漏 Telegram 连接。
            await asyncio.shield(asyncio.wait_for(item.client.disconnect(), 5))
        except Exception:
            pass  # 不记录包含手机号/会话的第三方异常。
        except asyncio.CancelledError:
            pass  # 断开是最后的清理动作，取消不再向上传播。

    async def expire(self, key: str) -> None:
        async with self.lock:
            await self.remove(key)

    def get(self, key: str, owner: str) -> Attempt:
        item = self.attempts.get(key)
        if not item or item.owner != owner or item.expires <= time.monotonic():
            raise HTTPException(410, '登录已过期或不存在，请重新开始')
        return item

    async def finish(self, item: Attempt) -> Dict[str, Any]:
        if not await item.client.is_user_authorized():
            raise HTTPException(400, '会话尚未获得 Telegram 授权')
        me = await item.client.get_me()
        if not me or me.bot:
            raise HTTPException(400, '需要 Telegram 真人账号，不能使用机器人账号')
        phone = '+' + (me.phone or '').lstrip('+')
        persist(item, item.client.session.save(), phone)
        return {'step': 'done', 'authorized': True, 'message': '授权已验证并安全保存；机器人运行状态未改变。'}

    async def start(self, body: Credentials, owner: str) -> Dict[str, Any]:
        async with self.lock:
            now = time.monotonic()
            if self.attempts or now - self.last_start < 30:
                raise HTTPException(429, '已有登录进行中或请求过快，请取消/稍后重试')
            saved = load_config()['telegram_account']
            credentials = resolve_credentials(body, saved)
            if body.mode == 'phone' and not re.fullmatch(r'\+[1-9][0-9]{6,14}', body.phone):
                raise HTTPException(400, '请输入带国际区号的手机号')
            session = body.session_string.get_secret_value() if body.mode == 'import' else ''
            if body.mode == 'import' and not session:
                raise HTTPException(400, '请输入 StringSession')
            account = {key: saved.get(key, '') for key in ('proxy_url', 'device_model', 'system_version', 'app_version')}
            account.update(credentials)
            account['phone'] = body.phone
            key = secrets.token_urlsafe(32)
            try:
                client = make_client(account, session)
            except Exception:
                raise HTTPException(400, 'StringSession 或固定连接参数无效') from None
            item = Attempt(owner, client, account, now + TTL, hashlib.sha256(tomlkit.dumps({'telegram_account': saved}).encode()).hexdigest())
            self.attempts[key] = item
            self.last_start = now
            item.timer = asyncio.get_running_loop().call_later(TTL, lambda: asyncio.create_task(self.expire(key)))
            try:
                async with asyncio.timeout(TIMEOUT):
                    await client.connect()
                    if body.mode == 'import':
                        result = await self.finish(item)
                        await self.remove(key)
                        return result
                    sent = await client.send_code_request(body.phone)
                    item.phone_code_hash = sent.phone_code_hash
                return {'step': 'code', 'attempt_id': key, 'expires_in': TTL}
            except BaseException as exc:
                # 必须用 BaseException：CancelledError 不是 Exception 的子类，
                # 浏览器断开连接时 uvicorn 会取消本任务，用 except Exception 会跳过清理，
                # 泄漏的 attempt 会让后续登录一直收到 429，直到 TTL（10 分钟）到期。
                await self.remove(key)
                if isinstance(exc, Exception):
                    self.fail(exc)
                raise

    def fail(self, exc: Exception) -> None:
        # 全部使用 4xx：反向代理（Cloudflare）会把源站 5xx 响应体替换成自己的错误页，
        # 前端就只能看到 HTML 而拿不到这里的中文原因。
        if isinstance(exc, HTTPException):
            raise exc
        if isinstance(exc, FloodWaitError):
            raise HTTPException(429, 'Telegram 限流，请稍后重新登录') from None
        if isinstance(exc, (PhoneCodeInvalidError, PasswordHashInvalidError)):
            raise HTTPException(400, '验证码或两步验证密码错误') from None
        if isinstance(exc, PhoneCodeExpiredError):
            raise HTTPException(410, '验证码过期，请重新开始') from None
        if isinstance(exc, PhoneNumberInvalidError):
            raise HTTPException(400, 'Telegram 不接受该手机号，请确认国际区号与号码') from None
        if isinstance(exc, PhoneNumberBannedError):
            raise HTTPException(400, '该手机号已被 Telegram 封禁，无法登录') from None
        if isinstance(exc, ApiIdInvalidError):
            raise HTTPException(400, 'API ID 与 API Hash 不匹配，请检查服务器配置') from None
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            raise HTTPException(408, '连接 Telegram 超时，请检查固定代理后重试') from None
        if isinstance(exc, ValueError) and 'unsuccessful' in str(exc):
            # Telethon 在重试次数用尽（含数据中心迁移）后抛出的裸 ValueError。
            raise HTTPException(424, 'Telegram 要求切换数据中心后仍未成功，请重新发起登录') from None
        raise HTTPException(424, 'Telegram 操作失败；请检查固定网络配置或稍后重试') from None

    async def verify(self, key: str, owner: str, value: str, step: str) -> Dict[str, Any]:
        async with self.lock:
            item = self.get(key, owner)
            if item.step != step:
                raise HTTPException(409, '登录步骤不匹配')
            try:
                async with asyncio.timeout(TIMEOUT):
                    if step == 'code':
                        if not re.fullmatch('[0-9]{3,8}', value):
                            raise HTTPException(400, '验证码格式无效')
                        await item.client.sign_in(phone=item.account['phone'], code=value, phone_code_hash=item.phone_code_hash)
                    else:
                        await item.client.sign_in(password=value)
                    result = await self.finish(item)
                await self.remove(key)
                return result
            except SessionPasswordNeededError:
                item.step = 'password'
                return {'step': 'password'}
            except Exception as exc:
                item.failures += 1
                if item.failures >= 5 or not isinstance(exc, (PhoneCodeInvalidError, PasswordHashInvalidError, HTTPException)):
                    await self.remove(key)
                self.fail(exc)
            except asyncio.CancelledError:
                # 客户端断开：清理该尝试，避免槽位泄漏挡住后续登录。
                await self.remove(key)
                raise

    async def close(self) -> None:
        async with self.lock:
            for key in list(self.attempts):
                await self.remove(key)

manager = LoginManager()

@router.get('/status')
async def status(owner: str = Depends(guard)) -> Dict[str, Any]:
    account = load_config()['telegram_account']
    params = fixed_parameters()
    try:
        resolve_credentials(Credentials(), account)
        credentials_saved = True
    except HTTPException:
        credentials_saved = False
    # 代理可能包含认证信息，只展示是否固定配置，不回显 URL。
    return {'configured': bool(account.get('session_string')), 'proxy_configured': bool(params.pop('proxy_url')),
            'device': params, 'expires_in': TTL, 'api_id': account.get('api_id'),
            'api_hash': MASK if account.get('api_hash') else '', 'credentials_saved': credentials_saved}

@router.post('/start')
async def start(body: Credentials, owner: str = Depends(guard)) -> Dict[str, Any]:
    return await manager.start(body, owner)

@router.post('/{key}/code')
async def code(key: str, body: Verification, owner: str = Depends(guard)) -> Dict[str, Any]:
    return await manager.verify(key, owner, body.value.get_secret_value(), 'code')

@router.post('/{key}/password')
async def password(key: str, body: Verification, owner: str = Depends(guard)) -> Dict[str, Any]:
    return await manager.verify(key, owner, body.value.get_secret_value(), 'password')

@router.delete('/{key}')
async def cancel(key: str, owner: str = Depends(guard)) -> Dict[str, bool]:
    async with manager.lock:
        manager.get(key, owner)
        await manager.remove(key)
    return {'cancelled': True}

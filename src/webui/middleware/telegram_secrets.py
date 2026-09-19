"""保护通用插件配置 API 中的 Telegram 凭据，账号授权写入独占于登录向导。"""
from urllib.parse import unquote, urlsplit, urlunsplit

import json

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import tomlkit

from src.webui.routers.telegram_onboarding import ALLOWED_ORIGINS, MASK, PLUGIN_ID

# 仅授权凭据与个人标识：这些字段只能由已验证的登录向导写入。
LOCKED_KEYS = {'api_hash', 'session_string', 'phone'}


def redact_proxy(value):
    """只隐藏代理 URL 中的账号密码，保留协议与地址，便于在通用页面继续查看与编辑。"""
    if not isinstance(value, str) or not value:
        return value
    parts = urlsplit(value)
    if not parts.hostname or not (parts.username or parts.password):
        return value
    host = parts.hostname + (f':{parts.port}' if parts.port else '')
    return urlunsplit((parts.scheme, f'{MASK}@{host}', parts.path, parts.query, parts.fragment))


def redact(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in LOCKED_KEYS and item:
                result[key] = MASK
            elif key == 'proxy_url':
                result[key] = redact_proxy(item)
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def locked_writes(config):
    """找出请求试图写入的受保护字段；等于掩码的回显不算修改。"""
    attempts = set()
    account = config.get('telegram_account')
    sources = [account] if isinstance(account, dict) else []
    for key, value in config.items():
        section, _, field = key.partition('.')
        if section == 'telegram_account' and field:
            sources.append({field: value})
    for source in sources:
        for key, value in source.items():
            if key in LOCKED_KEYS and isinstance(value, str) and value and value != MASK:
                attempts.add(key)
    return attempts


def drop_mask_echo(config):
    """移除掩码回显，避免把 ******** 写回磁盘覆盖真实凭据。"""
    account = config.get('telegram_account')
    if isinstance(account, dict):
        for key in LOCKED_KEYS:
            if account.get(key) == MASK:
                account.pop(key)
        if isinstance(account.get('proxy_url'), str) and MASK in account['proxy_url']:
            account.pop('proxy_url')
    for key in list(config):
        section, _, field = key.partition('.')
        if section == 'telegram_account' and field in LOCKED_KEYS and config[key] == MASK:
            config.pop(key)


class TelegramSecretsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = unquote(request.url.path)
        target = f'/plugins/config/{PLUGIN_ID}' in path or '/plugins/config/telegram_user_adapter' in path
        if target and request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            if request.headers.get('origin') not in ALLOWED_ORIGINS:
                return JSONResponse({'detail': '请求来源无效'}, status_code=403)
            # 通用 raw/reset 会整体覆写或清空账号授权，必须走已验证向导。
            if path.endswith(('/raw', '/reset')):
                return JSONResponse({'detail': 'Telegram 原始配置与重置已锁定，请使用登录向导'}, status_code=403)
            if request.method == 'PUT':
                try:
                    data = await request.json()
                except Exception:
                    return JSONResponse({'detail': '配置请求无效'}, status_code=400)
                config = data.get('config')
                if not isinstance(config, dict):
                    return JSONResponse({'detail': '配置请求无效'}, status_code=400)
                blocked = locked_writes(config)
                if blocked:
                    # 明确拒绝而非静默丢弃：否则界面会显示保存成功但磁盘未变。
                    return JSONResponse(
                        {'detail': f'字段 {"、".join(sorted(blocked))} 只能通过 Telegram 登录向导修改'},
                        status_code=403,
                    )
                drop_mask_echo(config)
                request._body = json.dumps(data).encode()
        response = await call_next(request)
        if target and request.method == 'GET' and response.status_code == 200:
            payload = b''.join([part async for part in response.body_iterator])
            try:
                data = json.loads(payload)
                for field in ('raw_config', 'config'):
                    if isinstance(data.get(field), str) and data[field]:
                        data[field] = tomlkit.dumps(redact(tomlkit.parse(data[field]).unwrap()))
                data = redact(data)
                # Schema 的 default/example 同样来自磁盘账号，需清空并标记为密码输入。
                sections = data.get('schema', {}).get('sections', {})
                account = sections.get('telegram_account', {})
                fields = account.get('fields', account)
                if isinstance(fields, dict):
                    for key in LOCKED_KEYS:
                        if isinstance(fields.get(key), dict):
                            fields[key].update(default='', example=None, disabled=True, input_type='password')
                return JSONResponse(data, headers={'Cache-Control': 'no-store'})
            except Exception:
                return JSONResponse({'detail': '账号配置无法安全显示'}, status_code=500)
        if '/telegram-onboarding' in path:
            if response.status_code == 422:
                # FastAPI 默认验证错误会回显原始输入，凭据端点不能返回。
                return JSONResponse({'detail': '输入格式无效，请检查必填字段'}, status_code=422,
                                    headers={'Cache-Control': 'no-store'})
            response.headers['Cache-Control'] = 'no-store'
        return response

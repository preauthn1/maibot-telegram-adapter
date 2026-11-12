"""宿主与适配器共用账号本地账本；导入不建库，不从模型参数猜作用域。"""
from pathlib import Path
import asyncio

from src.maisaka.context.interaction_continuity import InteractionLedger, is_explicit_stop

ROOT = Path(__file__).resolve().parents[3]
ACCOUNT_SCOPE = str(ROOT)
LEDGER_PATH = ROOT / 'data/persona-continuity/interactions.sqlite3'
ENVELOPE_KEY = 'interaction_continuity_v1'
FIELDS = ('session_id', 'user_id', 'source_message_id', 'logical_turn_id')

async def ledger_call(method, *args, **kwargs):
    def run():
        ledger = InteractionLedger(LEDGER_PATH, ACCOUNT_SCOPE)
        return getattr(ledger, method)(*args, **kwargs)
    return await asyncio.to_thread(run)

def envelope(session_id, user_id, source_message_id, logical_turn_id):
    result = dict(account_scope=ACCOUNT_SCOPE, session_id=str(session_id), user_id=str(user_id),
                  source_message_id=str(source_message_id), logical_turn_id=str(logical_turn_id))
    validate_envelope(result)
    return result

def validate_envelope(value):
    if not isinstance(value, dict) or set(value) != {'account_scope', *FIELDS}:
        raise ValueError('invalid continuity envelope')
    if value['account_scope'] != ACCOUNT_SCOPE or any(not isinstance(value[k], str) or not value[k] for k in FIELDS):
        raise ValueError('invalid continuity scope')
    return {k: value[k] for k in FIELDS}

async def final_can_send(value):
    if value is None:
        return True
    try:
        return await ledger_call('can_send', **validate_envelope(value))
    except Exception:
        return False  # 带账本标记的消息在存储故障时失败关闭。

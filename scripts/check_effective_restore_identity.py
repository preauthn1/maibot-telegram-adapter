"""仅在数据库副本沙箱运行：实际配置窗口与清空规则后的身份统计。"""
import json
from collections import defaultdict
from src.maisaka.runtime import MaisakaHeartFlowChatting
from src.maisaka.context.clear_context import select_messages_after_latest_clear_marker, is_clear_context_marker
from src.common.message_repository import find_messages


def check(sessions):
    result=[]
    for session in sessions.values():
        runtime=object.__new__(MaisakaHeartFlowChatting)
        runtime.chat_stream=session
        limit=runtime._get_context_restore_limit()
        queried=find_messages(session_id=session.session_id,limit=limit,limit_mode='latest')
        selected=select_messages_after_latest_clear_marker(queried)
        rows=[m for m in selected if not m.is_notify]
        markers=[i for i,m in enumerate(queried) if is_clear_context_marker(m)]
        boundary=markers[-1]+1 if markers else 0
        removed_before_boundary=boundary
        removed_commands=sum(m.is_command for m in queried[boundary:])
        removed_notifications=sum(m.is_notify for m in selected)
        if len(queried) != removed_before_boundary + removed_commands + removed_notifications + len(rows):
            raise RuntimeError('Restore exclusion accounting mismatch')
        # 在副本上执行真实恢复方法，不只重演查询/过滤规则。
        import asyncio
        from src.maisaka.reasoning_engine import MaisakaReasoningEngine
        runtime.session_id=session.session_id
        runtime.log_prefix='isolated-restore'
        runtime._chat_history=[]
        runtime.message_cache=[]
        runtime._is_focus_mode_active_for_current_chat=lambda: False
        engine=object.__new__(MaisakaReasoningEngine)
        engine._runtime=runtime
        runtime._reasoning_engine=engine
        asyncio.run(runtime._restore_recent_context_from_db())
        restored=[h for h in runtime._chat_history if getattr(h,'original_message',None) is not None]
        expected_ids=[m.message_id for m in rows]
        if [h.message_id for h in restored] != expected_ids:
            raise RuntimeError('Actual restore differs from selected message order')
        expected_users=[m.message_id for m in rows if runtime._resolve_restored_message_source_kind(m)=='user']
        if [m.message_id for m in runtime.message_cache] != expected_users[-200:]:
            raise RuntimeError('Actual restored user cache mismatch')
        if runtime._context_restore_failed:
            raise RuntimeError('Actual restore flagged failure')
        names, accounts=defaultdict(set),defaultdict(set)
        for m in rows:
            u=m.message_info.user_info
            name=u.user_cardname or u.user_nickname or u.user_id
            names[(m.platform,name)].add(u.user_id)
            accounts[(m.platform,u.user_id)].add(name)
        result.append({'limit':limit,'queried':len(queried),'after_clear':len(selected),'eligible':len(rows),
            'clear_markers':len(markers),'removed_before_boundary':removed_before_boundary,
            'removed_commands':removed_commands,'removed_notifications':removed_notifications,
            'collision_groups':sum(len(v)>1 for v in names.values()),
            'display_changes':sum(len(v)>1 for v in accounts.values())})
    report={'scope':'backup DB, current core config, actual restore method and history builder on minimal runtime; non-focus mode, no start or final model request',
        'sessions':len(result),'limits':sorted({r['limit'] for r in result}),
        **{k:sum(r[k] for r in result) for k in ('queried','after_clear','eligible','collision_groups','display_changes','clear_markers','removed_before_boundary','removed_commands','removed_notifications')},
        'sessions_with_collisions':sum(r['collision_groups']>0 for r in result),
        'sessions_with_display_changes':sum(r['display_changes']>0 for r in result)}
    print('EFFECTIVE_IDENTITY_RESULT='+json.dumps(report))

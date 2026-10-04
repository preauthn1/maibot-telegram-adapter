"""只读平台归属审计；不导入运行时，不输出正文或原始标识。"""
import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]

def main():
    os.umask(0o077)
    state=lambda: subprocess.check_output(['systemctl','show','maibot.service','--property=ActiveState','--value'],text=True).strip()
    if state()!='inactive': raise RuntimeError('Expected stopped service')
    paths=list((ROOT/'data').glob('MaiBot.db*'))
    before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    with sqlite3.connect((ROOT/'data/MaiBot.db').as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        scalar=lambda sql: db.execute(sql).fetchone()[0]
        report={
            'scope':'all stored message metadata and session platform mapping; not other memory/retrieval sources',
            'messages':scalar('SELECT COUNT(*) FROM mai_messages'),
            'sessions':scalar('SELECT COUNT(*) FROM chat_sessions'),
            'message_sessions':scalar('SELECT COUNT(DISTINCT session_id) FROM mai_messages'),
            'mixed_platform_sessions':scalar('SELECT COUNT(*) FROM (SELECT session_id FROM mai_messages GROUP BY session_id HAVING COUNT(DISTINCT platform)>1)'),
            'missing_platform_messages':scalar("SELECT COUNT(*) FROM mai_messages WHERE platform IS NULL OR trim(platform)=''"),
            'missing_session_messages':scalar("SELECT COUNT(*) FROM mai_messages WHERE session_id IS NULL OR trim(session_id)=''"),
            'orphan_messages':scalar('SELECT COUNT(*) FROM mai_messages m WHERE NOT EXISTS (SELECT 1 FROM chat_sessions s WHERE s.session_id=m.session_id)'),
            'session_platform_mismatch_messages':scalar('SELECT COUNT(*) FROM mai_messages m JOIN chat_sessions s ON s.session_id=m.session_id WHERE m.platform IS NOT s.platform'),
        }
        # 只在会话内部比较展示名；跨会话重名不等于上下文歧义。
        identity_cte = """WITH identities AS (
            SELECT DISTINCT session_id, platform, user_id,
                CASE WHEN trim(coalesce(user_cardname,''))<>'' THEN user_cardname
                     WHEN trim(coalesce(user_nickname,''))<>'' THEN user_nickname
                     ELSE user_id END AS display_name
            FROM mai_messages WHERE user_id IS NOT NULL AND trim(user_id)<>''
        ) """
        collisions = identity_cte + """SELECT session_id, platform, display_name,
            COUNT(DISTINCT user_id) AS accounts FROM identities
            GROUP BY session_id, platform, display_name HAVING COUNT(DISTINCT user_id)>1"""
        renames = identity_cte + """SELECT session_id, platform, user_id,
            COUNT(DISTINCT display_name) AS names FROM identities
            GROUP BY session_id, platform, user_id HAVING COUNT(DISTINCT display_name)>1"""
        collision_rows = db.execute(collisions).fetchall()
        rename_rows = db.execute(renames).fetchall()
        report['identity_metadata_audit'] = {
            'missing_sender_id_messages': scalar("SELECT COUNT(*) FROM mai_messages WHERE user_id IS NULL OR trim(user_id)=''"),
            'same_display_name_groups': len(collision_rows),
            'sessions_with_name_collisions': len({r[0] for r in collision_rows}),
            'max_accounts_sharing_display_name': max((r[3] for r in collision_rows), default=0),
            'account_session_pairs_with_display_changes': len(rename_rows),
            'sessions_with_display_changes': len({r[0] for r in rename_rows}),
            'interpretation': 'Historical display metadata, not simultaneous name collision, verified human identity, or measured model error. Cardname/nickname fallback changes also count.'
        }
        # 有界窗口审计仅比较元数据，不把全库重名当作一次请求中的重名。
        window_reports = []
        for size in (20, 50, 100):
            sql = """WITH ranked AS (
                SELECT session_id, platform, user_id,
                    coalesce(nullif(user_cardname,''),nullif(user_nickname,''),user_id) AS display_name,
                    ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY timestamp DESC,id DESC) AS rn
                FROM mai_messages WHERE is_notify=0
            ) SELECT session_id,platform,user_id,display_name FROM ranked WHERE rn<=?"""
            from collections import defaultdict
            by_name, by_account = defaultdict(set), defaultdict(set)
            rows = db.execute(sql, (size,)).fetchall()
            for sid, platform, uid, name in rows:
                by_name[(sid,platform,name)].add(uid)
                by_account[(sid,platform,uid)].add(name)
            clashes = [k for k,v in by_name.items() if len(v)>1]
            changes = [k for k,v in by_account.items() if len(v)>1]
            window_reports.append({'window_size':size,'messages_checked':len(rows),
                'sessions_checked':len({r[0] for r in rows}),
                'name_collision_groups':len(clashes),'sessions_with_name_collisions':len({k[0] for k in clashes}),
                'account_display_changes':len(changes),'sessions_with_display_changes':len({k[0] for k in changes})})
        report['recent_window_audit'] = window_reports
        report['window_scope'] = 'Latest non-notify rows per session at audit time; diagnostic sizes, not actual configured context or clear-marker-aware restoration.'
        db.rollback()
    report['database_files_unchanged']=all(p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==h for p,h in before.items())
    report['service_state']=state()
    out=ROOT/'data/dialogue-evaluations'/('platform-scope-audit-'+uuid4().hex[:8]);out.mkdir()
    (out/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'directory':str(out),**report}))
    return int(not report['database_files_unchanged'] or report['service_state']!='inactive')

if __name__=='__main__':raise SystemExit(main())

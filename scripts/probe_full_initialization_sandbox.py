"""实际调用 MainSystem.initialize；断网、只读生产根、可丢弃数据副本。"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BACKUP = Path('/root/backups/maibot-state/20260920T161508470492Z/MaiBot.db')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fail-session-restore', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if subprocess.check_output(['systemctl','show','maibot.service','--property=ActiveState','--value'],text=True).strip() != 'inactive':
        raise RuntimeError('Service must remain inactive')
    protected = [BACKUP, *list((ROOT/'data').glob('MaiBot.db*')), *list((ROOT/'config').glob('*.toml')), ROOT/'plugins/telegram_user_adapter/config.toml']
    before = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    out = ROOT/'data/dialogue-evaluations'/('full-init-'+uuid4().hex[:8])
    out.mkdir(mode=0o700)
    with tempfile.TemporaryDirectory(prefix='maibot-full-init-',dir='/root') as temp:
        temp = Path(temp)
        data = temp/'data'; data.mkdir()
        shutil.copyfile(BACKUP,data/'MaiBot.db')
        shutil.copytree(ROOT/'data/plugins',data/'plugins')
        if (ROOT/'data/a-memorix').is_dir():
            shutil.copytree(ROOT/'data/a-memorix',data/'a-memorix')
        config = temp/'config'; shutil.copytree(ROOT/'config',config)
        code = '''import asyncio,json
from src.common.database.database import initialize_database
from src.main import MainSystem
async def run():
    initialize_database()
    system=MainSystem()
    try:
        import os
        injected = os.environ.get('MAIBOT_DRILL_FAIL_SESSION') == '1'
        if injected:
            from src.chat.message_receive.chat_manager import chat_manager
            async def fail_restore():
                raise OSError('synthetic restore failure')
            chat_manager.load_all_sessions_from_db = fail_restore
        try:
            await asyncio.wait_for(system.initialize(),timeout=45)
        except OSError:
            if not injected:
                raise
            print('INIT_RESULT='+json.dumps({'completed':False,'expected_error':'OSError'}),flush=True)
        else:
            if injected:
                raise RuntimeError('Injected failure was swallowed')
            print('INIT_RESULT='+json.dumps({'completed':True}),flush=True)
        # 从入口源码提取真实关闭函数，避免导入 bot.py 的启动副作用。
        import ast
        from pathlib import Path
        from src.common.shutdown import request_shutdown
        from src.common.logger import get_logger
        from src.common.i18n import t, tn
        from src.manager.async_task_manager import async_task_manager
        from src.plugin_runtime.integration import get_plugin_runtime_manager
        manager = get_plugin_runtime_manager()
        processes = [s._runner_process for s in manager.supervisors if s._runner_process is not None]
        tree = ast.parse(Path('bot.py').read_text())
        nodes = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name in ('graceful_shutdown','_await_shutdown_step')]
        namespace = dict(asyncio=asyncio, MainSystem=MainSystem, request_shutdown=request_shutdown,
                         logger=get_logger('shutdown_drill'),t=t,tn=tn,async_task_manager=async_task_manager)
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'bot.py','exec'),namespace)
        await namespace['graceful_shutdown'](system)
        alive = sum(p.returncode is None for p in processes)
        pending = sum(not task.done() for task in asyncio.all_tasks() if task is not asyncio.current_task())
        print('SHUTDOWN_RESULT='+json.dumps({'runner_count':len(processes),'runners_alive':alive,'pending_tasks':pending}),flush=True)
        if alive or pending:
            raise RuntimeError('Shutdown left resources pending')
    except BaseException as exc:
        print('INIT_RESULT='+json.dumps({'completed':False,'error_type':type(exc).__name__}),flush=True)
        raise
asyncio.run(run())
'''
        cmd=['bwrap','--setenv','MAIBOT_DRILL_FAIL_SESSION','1' if args.fail_session_restore else '0','--die-with-parent','--unshare-pid','--unshare-net','--ro-bind','/','/',
             '--tmpfs','/tmp','--bind',str(data),str(ROOT/'data'),'--tmpfs',str(ROOT/'logs'),
             '--bind',str(config),str(ROOT/'config'),'--proc','/proc','--dev','/dev','--chdir',str(ROOT),
             str(ROOT/'.venv/bin/python'),'-c',code]
        timed_out=False
        with (out/'initialization.log').open('x') as log:
            try:
                p=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=75,umask=0o022)
                returncode=p.returncode
            except subprocess.TimeoutExpired:
                timed_out=True; returncode=None
    markers=[]
    shutdown=[]
    for line in (out/'initialization.log').read_text(errors='replace').splitlines():
        if line.startswith('INIT_RESULT='): markers.append(json.loads(line.partition('=')[2]))
        if line.startswith('SHUTDOWN_RESULT='): shutdown.append(json.loads(line.partition('=')[2]))
    report={'shutdown':shutdown, 'scope':'actual initialize and extracted real shutdown functions on copies; outbound networking blocked; not online readiness',
            'completed':returncode==0 and markers==([{'completed':False,'expected_error':'OSError'}] if args.fail_session_restore else [{'completed':True}]) and len(shutdown)==1 and shutdown[0]['runners_alive']==0 and shutdown[0]['pending_tasks']==0, 'fault_injected':args.fail_session_restore, 'returncode':returncode,
            'outer_timeout':timed_out,'markers':markers,
            'protected_files_unchanged':all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in before.items()),
            'service_state':subprocess.check_output(['systemctl','show','maibot.service','--property=ActiveState','--value'],text=True).strip()}
    (out/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'directory':str(out),**report}))
    return int(not report['completed'])

if __name__=='__main__': raise SystemExit(main())

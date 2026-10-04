"""在断网、只读根目录沙箱运行对话回归；日志单独保留。"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET


def regression_passed(returncode, totals):
    # 完整回归的跳过项不能被包装成全通过。
    return (returncode == 0 and totals['tests'] > 0
            and all(totals[key] == 0 for key in ('failures', 'errors', 'skipped')))
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def prompt_hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / 'prompts').rglob('*.prompt'))}


def fixture_hashes():
    # 只记录测试输入的路径和摘要，不将样本正文或配置写入报告。
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for directory in ('tests', 'plugins/telegram_user_adapter/tests')
            for p in sorted((ROOT / directory).rglob('*.json')) if p.is_file()}


def main():
    paths = [ROOT / 'config/bot_config.toml', ROOT / 'config/model_config.toml']
    def hashes():
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before = hashes()
    templates = prompt_hashes()
    fixtures = fixture_hashes()
    import os
    evaluation_options = {
        'background_repeats': int(os.environ.get('MAIBOT_TEST_BACKGROUND_REPEATS', '60')),
        'background_mode': os.environ.get('MAIBOT_TEST_BACKGROUND_MODE', 'repeated'),
        'history_enabled': os.environ.get('MAIBOT_TEST_HISTORY', '0'),
        'production_persona': os.environ.get('MAIBOT_TEST_PRODUCTION_PERSONA', '0'),
    }
    if (not 60 <= evaluation_options['background_repeats'] <= 6000
            or evaluation_options['background_mode'] not in ('repeated', 'distractors')
            or evaluation_options['history_enabled'] not in ('0', '1')
            or evaluation_options['production_persona'] not in ('0', '1')):
        raise ValueError('Invalid isolated evaluation options')
    # 把证据绑定到实际工作树，包括未提交源码；不收集配置或凭据内容。
    source_paths = sorted({p for directory in ('src', 'scripts', 'tests', 'plugins/telegram_user_adapter')
                           for p in (ROOT / directory).rglob('*.py')
                           if '__pycache__' not in p.parts})
    source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in source_paths}
    out = ROOT / 'data/dialogue-evaluations' / ('isolated-regression-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    (out / 'prompt-manifest.json').write_text(json.dumps(templates, sort_keys=True, indent=2))
    (out / 'source-manifest.json').write_text(json.dumps(source_hashes, sort_keys=True, indent=2))
    (out / 'fixture-manifest.json').write_text(json.dumps(fixtures, sort_keys=True, indent=2))
    result = {'scope': 'offline isolated regression, not production deployment', 'passed': False,
              'evaluation_options': evaluation_options,
              'source_files': len(source_hashes),
              'fixture_files': len(fixtures),
              'fixture_manifest_sha256': hashlib.sha256((out / 'fixture-manifest.json').read_bytes()).hexdigest(),
              'prompt_files': len(templates),
              'prompt_manifest_sha256': hashlib.sha256((out / 'prompt-manifest.json').read_bytes()).hexdigest(),
              'source_manifest_sha256': hashlib.sha256((out / 'source-manifest.json').read_bytes()).hexdigest()}
    try:
        with tempfile.TemporaryDirectory(prefix='maibot-tests-') as temp:
            config = Path(temp) / 'config'
            shutil.copytree(ROOT / 'config', config)
            artifacts = Path(temp) / 'artifacts'
            artifacts.mkdir()
            # 子进程绑定生命周期，超时杀死包装进程后不遗留测试后代。
            cmd = ['bwrap', '--setenv', 'MAIBOT_ASSEMBLED_PROMPT_OUTPUT', '/tmp/test-artifacts', '--die-with-parent', '--unshare-pid', '--unshare-net', '--ro-bind', '/', '/', '--tmpfs', '/tmp',
                   '--tmpfs', str(ROOT / 'data'), '--tmpfs', str(ROOT / 'logs'),
                   '--bind', str(config), str(ROOT / 'config'), '--bind', str(artifacts), '/tmp/test-artifacts', '--proc', '/proc', '--dev', '/dev',
                   '--chdir', str(ROOT), str(ROOT / '.venv/bin/python'), '-m', 'pytest',
                   'tests', 'plugins/telegram_user_adapter/tests', '-v', '-o', 'faulthandler_timeout=60', '-p', 'no:cacheprovider', '--tb=short', '--junitxml=/tmp/test-artifacts/pytest.xml']
            # 直接写日志，超时也保留已产生的输出；权限防止异常信息外泄。
            log_path = out / 'pytest.log'
            with log_path.open('x') as log:
                log_path.chmod(0o600)
                completed = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=180)
            assembled = list(artifacts.glob('assembled-*.json'))
            for source in assembled:
                shutil.copyfile(source, out / source.name)
                (out / source.name).chmod(0o600)
            for name in ('sender-request.json', 'sender-request-first.json', 'sender-request-renamed.json', 'sender-request-first-renamed.json', 'sender-request-corrected.json', 'sender-request-first-corrected.json', 'sender-request-renamed-corrected.json', 'sender-request-first-renamed-corrected.json', 'sender-request-dual.json', 'sender-request-first-dual.json', 'sender-request-renamed-dual.json', 'sender-request-first-renamed-dual.json'):
                sender_request = artifacts / name
                if sender_request.exists():
                    shutil.copyfile(sender_request, out / sender_request.name)
                    (out / sender_request.name).chmod(0o600)
            result['assembled_prompt_exports'] = len(assembled)
            result['returncode'] = completed.returncode
            xml_path = out / 'pytest.xml'
            shutil.copyfile(artifacts / 'pytest.xml', xml_path)
            xml_path.chmod(0o600)
            from junit_evidence import verified_counts
            totals = verified_counts(xml_path)
            result['test_counts'] = totals
            result['passed'] = regression_passed(completed.returncode, totals)
    except (OSError, subprocess.TimeoutExpired, ET.ParseError, ValueError, KeyError) as exc:
        result['error_type'] = type(exc).__name__
    finally:
        result['production_configs_unchanged'] = hashes() == before
        after_source_paths = sorted({p for directory in ('src', 'scripts', 'tests', 'plugins/telegram_user_adapter')
                                    for p in (ROOT / directory).rglob('*.py')
                                    if '__pycache__' not in p.parts})
        after_sources = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in after_source_paths}
        result['source_tree_unchanged'] = after_sources == source_hashes
        result['prompt_tree_unchanged'] = prompt_hashes() == templates
        result['fixture_tree_unchanged'] = fixture_hashes() == fixtures
        result['passed'] = (result['passed'] and result['fixture_tree_unchanged'] and result['production_configs_unchanged'])
        result['passed'] = (result['passed'] and result['production_configs_unchanged']
                            and result['source_tree_unchanged'] and result['prompt_tree_unchanged'])
        (out / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({'result_dir': str(out), **result}))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

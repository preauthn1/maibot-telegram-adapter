"""合成画像缓存微基准；不读取部署画像，不启动平台。"""
import importlib.util
import json
import os
from pathlib import Path
import statistics
import tempfile
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def main():
    spec = importlib.util.spec_from_file_location('isolated_scene', ROOT / 'src/chat/utils/scene_context.py')
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as directory:
        try:
            os.chdir(directory)
            header = '---\nstyle_enabled: true\nstyle_max_chars: 80\nmax_emoji: 0\nmanual_style_enabled: true\n---\n'
            for i in range(10):
                path = Path('data/plugins/test/chats') / str(-i-1) / 'SKILL.md'
                path.parent.mkdir(parents=True)
                path.write_text(header + '合成规则。' * 300 + 'OLD', encoding='utf-8')
            def timed():
                start = time.perf_counter_ns()
                text = module._load_chat_style('-1')
                return (time.perf_counter_ns()-start)/1e6, text
            cold, result = timed()
            assert 'OLD' in result
            samples = [timed()[0] for _ in range(200)]
            target = Path('data/plugins/test/chats/-1/SKILL.md')
            target.write_text(target.read_text().replace('OLD', 'NEW'), encoding='utf-8')
            reload_ms, result = timed()
            assert 'NEW' in result and 'OLD' not in result
            report = {'scope': 'synthetic local warm-filesystem microbenchmark; not model latency',
                      'profiles': 10, 'warm_iterations': len(samples),
                      'cold_ms': cold, 'warm_median_ms': statistics.median(samples),
                      'warm_p95_ms': sorted(samples)[int(len(samples)*0.95)-1],
                      'reload_ms': reload_ms, 'same_length_update_verified': True}
        finally:
            os.chdir(original_cwd)
    output = ROOT / 'data/dialogue-evaluations' / ('style-benchmark-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(output)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

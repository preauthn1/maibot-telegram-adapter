"""记录优化器可能吞掉的模型异常，避免基线回退被误报为成功。"""
import json


class TrackedCompletion:
    def __init__(self, complete, journal):
        self.complete = complete
        self.journal = journal
        self.failures = []

    def __call__(self, messages):
        try:
            return self.complete(messages)
        except Exception as exc:
            # 不记录异常文本、URL 或请求正文，以免鉴权和私有配置进入报告。
            record = {'phase': 'reflection' if isinstance(messages, str) else 'evaluation',
                      'error_type': type(exc).__name__}
            self.failures.append(record)
            with self.journal.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(record) + '\n')
            raise

    def require_clean(self):
        if self.failures:
            raise RuntimeError('model calls failed; experiment is not valid')

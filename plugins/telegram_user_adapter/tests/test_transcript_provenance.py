"""未捕获候选不能伪装成已捕获原文。"""
from pathlib import Path
import asyncio
import json
import logging
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.transcript import ChatTranscriptLogger


@pytest.mark.parametrize('captured', [True, False])
def test_candidate_provenance(tmp_path, captured):
    logger = ChatTranscriptLogger(tmp_path, logging.getLogger(__name__))
    asyncio.run(logger.log_outbound(
        chat_id='test', message_id=1, text='保留原句', original_text='保留原句',
        queue_wait_seconds=0, typing_seconds=0, reply_latency_seconds=None,
        priority=0, original_captured=captured,
    ))
    row = json.loads((tmp_path / 'chat_test.jsonl').read_text())
    assert row['candidate_stage'] == 'adapter_pre_humanize'
    assert row['original_captured'] is captured
    assert row['original_text'] == ('保留原句' if captured else None)
    assert row['rewritten'] == (False if captured else None)

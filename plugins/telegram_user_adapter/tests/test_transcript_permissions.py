"""聊天原文日志应私有保存，拒绝符号链接目标。"""
import asyncio
import logging
import os
import stat
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.transcript import ChatTranscriptLogger


def test_new_transcript_private_even_with_open_umask(tmp_path):
    previous = os.umask(0)
    try:
        root = tmp_path / 'transcripts'
        logger = ChatTranscriptLogger(root, logging.getLogger('test'))
        asyncio.run(logger.log_event('synthetic', 'test', {}))
    finally:
        os.umask(previous)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / 'chat_synthetic.jsonl').stat().st_mode) == 0o600


def test_existing_transcript_restricted_before_append(tmp_path):
    path = tmp_path / 'chat_synthetic.jsonl'
    path.write_text('previous\n')
    path.chmod(0o644)
    logger = ChatTranscriptLogger(tmp_path, logging.getLogger('test'))
    asyncio.run(logger.log_event('synthetic', 'test', {}))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text().startswith('previous\n')


def test_transcript_does_not_follow_file_symlink(tmp_path):
    target = tmp_path / 'outside'
    target.write_text('unchanged')
    root = tmp_path / 'transcripts'
    root.mkdir()
    (root / 'chat_synthetic.jsonl').symlink_to(target)
    logger = ChatTranscriptLogger(root, logging.getLogger('test'))
    asyncio.run(logger.log_event('synthetic', 'test', {}))
    assert target.read_text() == 'unchanged'

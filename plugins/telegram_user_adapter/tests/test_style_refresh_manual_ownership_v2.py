"""刷新归属回归：只导入纯标准库模块，所有文件位于临时目录。"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import json
import sys

import pytest

_SOURCE = Path(__file__).resolve().parents[1] / "style_profiles.py"
_SPEC = spec_from_file_location("style_ownership_v2_isolated", _SOURCE)
assert _SPEC is not None and _SPEC.loader is not None
style = module_from_spec(_SPEC)
sys.modules[_SPEC.name] = style
_SPEC.loader.exec_module(style)


def prepare(tmp_path, header, count=25):
    (tmp_path / "account_profile.json").write_text(json.dumps({"user_id": "owner"}))
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    rows = [{"direction": "in", "sender_id": "owner", "chat_id": "-1",
             "message_id": str(i), "text": f"本地样本{i}。"} for i in range(count)]
    (transcripts / "chat_test.jsonl").write_text("\n".join(map(json.dumps, rows)))
    path = tmp_path / "chats/-1/SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(("---\r\n" + header.replace("\n", "\r\n") +
                      "---\r\n\r\n  人工正文\r\n").encode())
    return path


@pytest.mark.parametrize("header", [
    "style_source: manual\nstyle_enabled: true\nmax_emoji: 0\n",
    "style_enabled: true\nmax_emoji: 0\n",
    "style_source: obsolete\nstyle_owner_samples: 999\n",
    "style_source: owner_inbound_v1\nstyle_enabled: true\nmanual_style_enabled: true\nmax_emoji: 0\n",
    "style_source: owner_inbound_v1\nstyle_source: manual\n",
    "style_source: owner_inbound_v1\nmanual_style_enabled: false\n",
])
@pytest.mark.parametrize("count", [0, 25])
def test_protected_profile_bytes_and_mtime_unchanged(tmp_path, header, count):
    path = prepare(tmp_path, header, count)
    before, stamp = path.read_bytes(), path.stat().st_mtime_ns
    assert style.sync_style_profiles(tmp_path) == []
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == stamp
    controls = style.derive_style_controls(["足够样本"] * 25)
    original = before.decode()
    assert style.merge_style_frontmatter(original, controls) == original


def test_known_automatic_refresh_and_revocation(tmp_path):
    path = prepare(tmp_path, "style_source: owner_inbound_v1\nstyle_enabled: true\n"
                   "style_owner_samples: 99\nmax_chars: 12\n")
    assert style.sync_style_profiles(tmp_path) == ["-1"]
    assert "style_owner_samples: 25\n" in path.read_text()
    assert "max_chars: 12\n" in path.read_text()
    assert style.sync_style_profiles(tmp_path) == []
    (tmp_path / "transcripts/chat_test.jsonl").write_text("")
    assert style.sync_style_profiles(tmp_path) == ["-1"]
    assert "style_enabled: false\n" in path.read_text()


def test_operator_corpus_precedence_and_actual_refresh(tmp_path):
    path = prepare(tmp_path, "max_chars: 12\n")
    corpus = tmp_path / "style_corpus/owner_verified.jsonl"
    corpus.parent.mkdir()
    rows = [{"schema_version": 1, "source": "operator_attested_owner", "sender_id": "owner",
             "chat_id": "-1", "message_id": str(i), "text": f"操作员声明样本{i}😀"} for i in range(25)]
    corpus.write_text("\n".join(map(json.dumps, rows)))
    assert style._collect_outbound_messages(tmp_path, "owner") == {"-1": [r["text"] for r in rows]}
    assert style.sync_style_profiles(tmp_path) == ["-1"]
    assert "style_owner_samples: 25\n" in path.read_text()
    assert "style_source: owner_inbound_v1\n" in path.read_text()
    assert "max_chars: 12\n" in path.read_text()
    assert path.read_bytes().endswith("\r\n  人工正文\r\n".encode())


@pytest.mark.parametrize("change", [
    {"schema_version": True}, {"schema_version": "1"}, {"source": "verified_human"},
    {"sender_id": "other"}, {"chat_id": "../../escape"}, {"chat_id": "/tmp/escape"},
    {"chat_id": "-1::tg-topic::mt=x"}, {"chat_id": "-1\n"},
    {"chat_id": ""}, {"chat_id": 1}, {"message_id": " "}, {"message_id": 1},
    {"text": None}, {"text": " "}, {"text": "[回复<原文]，说：正文"},
    {"text": "[文件:占位]"},
])
def test_invalid_operator_corpus_is_not_sampled(tmp_path, change):
    corpus = tmp_path / "style_corpus/owner_verified.jsonl"
    corpus.parent.mkdir()
    row = {"schema_version": 1, "source": "operator_attested_owner", "sender_id": "owner",
           "chat_id": "-1", "message_id": "1", "text": "操作员声明"}
    row.update(change)
    corpus.write_text(json.dumps(row) + '\nnull\n[]\nbroken json\n')
    assert style._collect_outbound_messages(tmp_path, "owner") == {}


def test_topic_corpus_and_automatic_outbound_exclusion(tmp_path):
    prepare(tmp_path, "max_chars: 12\n", count=0)
    corpus = tmp_path / "style_corpus/owner_verified.jsonl"
    corpus.parent.mkdir()
    row = {"schema_version": 1, "source": "operator_attested_owner", "sender_id": "owner",
           "chat_id": "-1::tg-topic::mt=10", "message_id": "1", "text": "声明话题文本"}
    corpus.write_text(json.dumps(row))
    (tmp_path / "transcripts/chat_test.jsonl").write_text(json.dumps({
        "direction": "out", "sender_id": "owner", "chat_id": "-1", "text": "自动出站"}))
    assert style._collect_outbound_messages(tmp_path, "owner") == {row["chat_id"]: [row["text"]]}
    assert style.sync_style_profiles(tmp_path, min_samples=1) == [row["chat_id"]]
    assert (tmp_path / "chats" / row["chat_id"] / "SKILL.md").is_file()

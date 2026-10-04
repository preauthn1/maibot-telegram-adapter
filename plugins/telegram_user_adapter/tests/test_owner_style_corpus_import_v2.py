"""独立语料导入的真实文件验收，不导入生产运行时。"""
from pathlib import Path

import importlib.util
import json
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("owner_corpus_import", ROOT / "scripts/import_owner_style_corpus.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("导入脚本未找到")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def row(**changes):
    value = dict(chat_id="-10042", message_id="1", sender_id="test-owner", text="先留着条件，再谈结论。", authorship="owner_authored")
    value.update(changes)
    return value


def validate(items):
    return MODULE.validate_rows("\n".join(json.dumps(item) for item in items), "test-owner")


def test_roundtrip_and_idempotency(tmp_path):
    rows = validate([row(), row()])
    first = MODULE.publish_corpus(tmp_path, rows)
    target = Path(first["path"])
    stamp = target.stat().st_mtime_ns
    second = MODULE.publish_corpus(tmp_path, rows)
    assert first["total"] == first["added"] == 1
    assert second["added"] == 0 and second["changed"] is False
    assert target.stat().st_mtime_ns == stamp
    assert target.stat().st_mode & 0o777 == 0o600
    stored = json.loads(target.read_text())
    assert stored["text"] == row()["text"]
    assert stored["source"] == "operator_attested_owner"


@pytest.mark.parametrize("changes", [
    {"authorship": "bot_output"}, {"sender_id": "someone-else"}, {"message_id": 1},
    {"text": ""}, {"direction": "out"}, {"source": "model_generated"},
    {"generated": True}, {"generated": "false"}, {"chat_id": "../../outside"},
])
def test_reject_invalid_sources(changes):
    with pytest.raises(ValueError):
        validate([row(**changes)])


def test_conflicting_batch_rejected():
    with pytest.raises(ValueError):
        validate([row(), row(text="不同正文")])


def test_conflicting_existing_preserves_all_bytes(tmp_path):
    result = MODULE.publish_corpus(tmp_path, validate([row()]))
    target = Path(result["path"])
    original = target.read_bytes()
    with pytest.raises(ValueError):
        MODULE.publish_corpus(tmp_path, validate([row(message_id="2"), row(text="冲突")]))
    assert target.read_bytes() == original


def test_cli_dry_run_and_attestation(tmp_path):
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(row()), encoding="utf-8")
    dest = tmp_path / "data"
    command = [sys.executable, str(ROOT / "scripts/import_owner_style_corpus.py"), str(source),
               "--owner-id", "test-owner", "--data-dir", str(dest)]
    dry = subprocess.run(command, capture_output=True, text=True)
    assert dry.returncode == 0
    assert not dest.exists()
    rejected = subprocess.run(command + ["--apply"], capture_output=True, text=True)
    assert rejected.returncode != 0 and not dest.exists()
    applied = subprocess.run(command + ["--apply", "--attest-owner-authored"], capture_output=True, text=True)
    assert applied.returncode == 0
    assert json.loads(applied.stdout)["added"] == 1


def test_symlink_target_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    folder = tmp_path / "style_corpus"
    folder.mkdir()
    (folder / "owner_verified.jsonl").symlink_to(outside)
    with pytest.raises(ValueError):
        MODULE.publish_corpus(tmp_path, validate([row()]))
    assert outside.read_text() == "untouched"


def test_import_to_real_profile_refresh(tmp_path):
    spec = importlib.util.spec_from_file_location("owner_import_style_integration", ROOT / "plugins/telegram_user_adapter/style_profiles.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("画像模块未找到")
    style = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = style
    spec.loader.exec_module(style)
    (tmp_path / "account_profile.json").write_text(json.dumps({"user_id": "test-owner"}))
    rows = validate([row(message_id=str(i), text=f"这是本人声明语料第{i}条。") for i in range(25)])
    MODULE.publish_corpus(tmp_path, rows)
    assert style.sync_style_profiles(tmp_path) == ["-10042"]
    profile = tmp_path / "chats/-10042/SKILL.md"
    text = profile.read_text()
    assert "style_owner_samples: 25" in text
    assert "style_enabled: true" in text
    assert style.sync_style_profiles(tmp_path) == []

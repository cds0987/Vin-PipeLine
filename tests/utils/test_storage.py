"""
Storage utility tests — covers gaps not in existing suite:
  - read_binary: local file happy path, FileNotFoundError
  - write_dlq_file: creates file with correct content, creates nested parent dirs
"""
from __future__ import annotations

import pytest

from utils.storage import read_binary, write_dlq_file


# ─── read_binary ──────────────────────────────────────────────────────────────

def test_read_binary_returns_file_contents(tmp_path):
    f = tmp_path / "data.bin"
    f.write_bytes(b"\x00\x01\x02hello")
    assert read_binary(str(f)) == b"\x00\x01\x02hello"


def test_read_binary_text_file_as_bytes(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes("xin chào".encode("utf-8"))
    assert read_binary(str(f)) == "xin chào".encode("utf-8")


def test_read_binary_raises_for_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_binary(str(tmp_path / "nonexistent.bin"))


def test_read_binary_rejects_path_outside_allowed_root(tmp_path, monkeypatch):
    import config.settings as cfg

    outside = tmp_path.parent / "outside.txt"
    outside.write_bytes(b"secret")
    monkeypatch.setattr(cfg, "LOCAL_FILE_ROOT", tmp_path.resolve())

    with pytest.raises(ValueError, match="Path traversal denied"):
        read_binary(str(outside))


def test_read_binary_rejects_file_larger_than_limit(tmp_path, monkeypatch):
    import config.settings as cfg

    target = tmp_path / "large.bin"
    target.write_bytes(b"0123456789")
    monkeypatch.setattr(cfg, "LOCAL_FILE_ROOT", tmp_path.resolve())
    monkeypatch.setattr(cfg, "MAX_FILE_SIZE_BYTES", 4)

    with pytest.raises(ValueError, match="File exceeds MAX_FILE_SIZE_BYTES"):
        read_binary(str(target))


# ─── write_dlq_file ───────────────────────────────────────────────────────────

def test_write_dlq_file_creates_file(tmp_path, monkeypatch):
    import config.settings as cfg
    monkeypatch.setattr(cfg, "DLQ_DIR", tmp_path / "dlq")

    target = write_dlq_file("error.json", '{"reason": "test"}')
    assert target.exists()


def test_write_dlq_file_content_matches(tmp_path, monkeypatch):
    import config.settings as cfg
    monkeypatch.setattr(cfg, "DLQ_DIR", tmp_path / "dlq")

    payload = '{"event": "DLQ", "doc_id": "abc"}'
    target = write_dlq_file("event.json", payload)
    assert target.read_text(encoding="utf-8") == payload


def test_write_dlq_file_creates_parent_directory(tmp_path, monkeypatch):
    import config.settings as cfg
    deep_dir = tmp_path / "a" / "b" / "c"
    monkeypatch.setattr(cfg, "DLQ_DIR", deep_dir)

    target = write_dlq_file("event.json", "{}")
    assert target.parent.exists()
    assert target.exists()


def test_write_dlq_file_returns_path_object(tmp_path, monkeypatch):
    import config.settings as cfg
    from pathlib import Path
    monkeypatch.setattr(cfg, "DLQ_DIR", tmp_path / "dlq")

    result = write_dlq_file("out.json", "{}")
    assert isinstance(result, Path)


def test_write_dlq_file_filename_preserved(tmp_path, monkeypatch):
    import config.settings as cfg
    monkeypatch.setattr(cfg, "DLQ_DIR", tmp_path / "dlq")

    target = write_dlq_file("schema_error_20260529.json", "{}")
    assert target.name == "schema_error_20260529.json"

"""
Tests for utils/storage.py — S3 read path.

read_binary() is the single entry point for all file I/O in the pipeline.
These tests cover:
  - S3 URI routing (s3:// → S3 client, otherwise → local)
  - Bucket validation (cross-bucket access denied)
  - File size limit enforcement (head_object → validate before read)
  - S3 client error propagation
  - Local path traversal protection
  - S3 key parsing edge cases
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ── S3 path routing ───────────────────────────────────────────────────────────

def test_s3_uri_calls_s3_client(monkeypatch, tmp_path):
    """s3:// URI must go through the S3 code path, not local filesystem."""
    monkeypatch.setattr("config.settings.S3_BUCKET", "my-bucket")
    monkeypatch.setattr("config.settings.MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024)

    fake_body = MagicMock()
    fake_body.read.return_value = b"s3 file content"
    fake_client = MagicMock()
    fake_client.head_object.return_value = {"ContentLength": 15}
    fake_client.get_object.return_value = {"Body": fake_body}

    with patch("utils.storage._s3_client", return_value=fake_client):
        from utils.storage import read_binary
        result = read_binary("s3://my-bucket/path/to/file.pdf")

    assert result == b"s3 file content"
    fake_client.head_object.assert_called_once_with(Bucket="my-bucket", Key="path/to/file.pdf")
    fake_client.get_object.assert_called_once_with(Bucket="my-bucket", Key="path/to/file.pdf")


def test_local_path_bypasses_s3(tmp_path, monkeypatch):
    """Non-s3:// URI must read from local filesystem."""
    monkeypatch.setattr("config.settings.MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024)

    f = tmp_path / "local.txt"
    f.write_bytes(b"local content")

    with patch("utils.storage._s3_client") as mock_s3:
        from utils.storage import read_binary
        result = read_binary(str(f))

    mock_s3.assert_not_called()
    assert result == b"local content"


# ── bucket validation ─────────────────────────────────────────────────────────

def test_cross_bucket_access_denied(monkeypatch):
    monkeypatch.setattr("config.settings.S3_BUCKET", "allowed-bucket")
    monkeypatch.setattr("config.settings.MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024)

    from utils.storage import read_binary
    with pytest.raises(ValueError, match="Cross-bucket access denied"):
        read_binary("s3://other-bucket/file.pdf")


def test_same_bucket_allowed(monkeypatch):
    monkeypatch.setattr("config.settings.S3_BUCKET", "my-bucket")
    monkeypatch.setattr("config.settings.MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024)

    fake_body = MagicMock()
    fake_body.read.return_value = b"ok"
    fake_client = MagicMock()
    fake_client.head_object.return_value = {"ContentLength": 2}
    fake_client.get_object.return_value = {"Body": fake_body}

    with patch("utils.storage._s3_client", return_value=fake_client):
        from utils.storage import read_binary
        result = read_binary("s3://my-bucket/file.txt")
    assert result == b"ok"


# ── file size limit ───────────────────────────────────────────────────────────

def test_s3_file_exceeding_max_size_raises(monkeypatch):
    monkeypatch.setattr("config.settings.S3_BUCKET", "b")
    monkeypatch.setattr("config.settings.MAX_FILE_SIZE_BYTES", 100)

    fake_client = MagicMock()
    fake_client.head_object.return_value = {"ContentLength": 200}

    with patch("utils.storage._s3_client", return_value=fake_client):
        from utils.storage import read_binary
        with pytest.raises(ValueError, match="MAX_FILE_SIZE_BYTES"):
            read_binary("s3://b/huge.pdf")

    fake_client.get_object.assert_not_called()


def test_s3_file_at_exact_limit_is_allowed(monkeypatch):
    monkeypatch.setattr("config.settings.S3_BUCKET", "b")
    monkeypatch.setattr("config.settings.MAX_FILE_SIZE_BYTES", 100)

    fake_body = MagicMock()
    fake_body.read.return_value = b"x" * 100
    fake_client = MagicMock()
    fake_client.head_object.return_value = {"ContentLength": 100}
    fake_client.get_object.return_value = {"Body": fake_body}

    with patch("utils.storage._s3_client", return_value=fake_client):
        from utils.storage import read_binary
        result = read_binary("s3://b/file.txt")
    assert len(result) == 100


def test_local_file_exceeding_max_size_raises(monkeypatch, tmp_path):
    monkeypatch.setattr("config.settings.MAX_FILE_SIZE_BYTES", 10)

    f = tmp_path / "big.txt"
    f.write_bytes(b"x" * 20)

    from utils.storage import read_binary
    with pytest.raises(ValueError, match="MAX_FILE_SIZE_BYTES"):
        read_binary(str(f))


# ── S3 key parsing ────────────────────────────────────────────────────────────

def test_s3_uri_with_nested_key(monkeypatch):
    monkeypatch.setattr("config.settings.S3_BUCKET", "bucket")
    monkeypatch.setattr("config.settings.MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024)

    fake_body = MagicMock()
    fake_body.read.return_value = b"nested"
    fake_client = MagicMock()
    fake_client.head_object.return_value = {"ContentLength": 6}
    fake_client.get_object.return_value = {"Body": fake_body}

    with patch("utils.storage._s3_client", return_value=fake_client):
        from utils.storage import read_binary
        read_binary("s3://bucket/a/b/c/deep.pdf")

    _, kwargs = fake_client.head_object.call_args
    assert fake_client.head_object.call_args[1]["Key"] == "a/b/c/deep.pdf" or \
           fake_client.head_object.call_args[0][1] == "a/b/c/deep.pdf" or \
           "a/b/c/deep.pdf" in str(fake_client.head_object.call_args)


def test_s3_uri_without_key_raises(monkeypatch):
    monkeypatch.setattr("config.settings.S3_BUCKET", "bucket")
    monkeypatch.setattr("config.settings.MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024)

    fake_client = MagicMock()
    with patch("utils.storage._s3_client", return_value=fake_client):
        from utils.storage import read_binary
        with pytest.raises(ValueError, match="Invalid S3 URI"):
            read_binary("s3://bucket/")


# ── S3 client errors propagate ────────────────────────────────────────────────

def test_s3_client_error_propagates(monkeypatch):
    monkeypatch.setattr("config.settings.S3_BUCKET", "b")
    monkeypatch.setattr("config.settings.MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024)

    fake_client = MagicMock()
    fake_client.head_object.side_effect = ConnectionError("S3 unreachable")

    with patch("utils.storage._s3_client", return_value=fake_client):
        from utils.storage import read_binary
        with pytest.raises(ConnectionError, match="S3 unreachable"):
            read_binary("s3://b/file.pdf")


# ── local path traversal ──────────────────────────────────────────────────────

def test_local_path_traversal_denied(monkeypatch, tmp_path):
    monkeypatch.setattr("config.settings.MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024)
    # LOCAL_FILE_ROOT is the project root; /etc/passwd is outside it
    from utils.storage import read_binary
    with pytest.raises(ValueError, match="Path traversal denied"):
        read_binary("/etc/passwd")

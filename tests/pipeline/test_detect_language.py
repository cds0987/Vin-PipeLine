"""
Tests for language detection behaviour in RunIngestJob.

Behaviour:
  - empty text -> "vi"
  - text shorter than 50 chars -> "vi"
  - langdetect raises -> "vi"
  - English text -> "en"
  - Vietnamese text -> "vi"
"""
from __future__ import annotations

import sys
import types

from app.application.ingest.run_ingest_job import RunIngestJob


def _usecase():
    return RunIngestJob(None, None, None, None, None, None, None, None, None, None)


def test_empty_text_returns_vi():
    assert _usecase()._detect_language("") == "vi"


def test_text_below_50_chars_returns_vi():
    assert _usecase()._detect_language("short") == "vi"
    assert _usecase()._detect_language("hello world") == "vi"


def test_exactly_50_chars_passes_threshold():
    text = "a" * 50
    result = _usecase()._detect_language(text)
    assert isinstance(result, str)


def test_langdetect_import_error_returns_vi():
    long_text = "this is a long enough english sentence for language detection purposes here"
    original = sys.modules.get("langdetect")
    try:
        sys.modules["langdetect"] = None  # type: ignore
        result = _usecase()._detect_language(long_text)
        assert result == "vi"
    finally:
        if original is None:
            sys.modules.pop("langdetect", None)
        else:
            sys.modules["langdetect"] = original


def test_langdetect_exception_returns_vi(monkeypatch):
    long_text = "some long text that is definitely more than fifty characters in total length"
    fake_langdetect = types.ModuleType("langdetect")
    fake_langdetect.detect = lambda _: (_ for _ in ()).throw(Exception("langdetect error"))
    monkeypatch.setitem(sys.modules, "langdetect", fake_langdetect)
    assert _usecase()._detect_language(long_text) == "vi"


def test_english_text_detected(monkeypatch):
    fake_langdetect = types.ModuleType("langdetect")
    fake_langdetect.detect = lambda _: "en"
    monkeypatch.setitem(sys.modules, "langdetect", fake_langdetect)
    long_en = "This document describes employee benefits and company policies at VSF Corporation."
    assert _usecase()._detect_language(long_en) == "en"


def test_vi_returned_from_langdetect(monkeypatch):
    fake_langdetect = types.ModuleType("langdetect")
    fake_langdetect.detect = lambda _: "vi"
    monkeypatch.setitem(sys.modules, "langdetect", fake_langdetect)
    long_vi = "Chính sách nghỉ phép của nhân viên công ty VSF được áp dụng từ ngày ký hợp đồng."
    assert _usecase()._detect_language(long_vi) == "vi"

"""
Tests for DocumentStatus constants.

Verifies that status strings match expected values so that code using
the constants stays in sync with DB schema and business rules.
"""
from __future__ import annotations

from app.domain.documents.statuses import DocumentStatus


def test_status_values_match_expected_strings():
    assert DocumentStatus.PENDING == "pending"
    assert DocumentStatus.INDEXING == "indexing"
    assert DocumentStatus.INDEXED == "indexed"
    assert DocumentStatus.FAILED == "failed"


def test_all_set_contains_all_four_statuses():
    assert DocumentStatus.ALL == {"pending", "indexing", "indexed", "failed"}


def test_terminal_statuses():
    assert DocumentStatus.TERMINAL == {"indexed", "failed"}
    assert DocumentStatus.PENDING not in DocumentStatus.TERMINAL
    assert DocumentStatus.INDEXING not in DocumentStatus.TERMINAL


def test_retriable_statuses():
    assert DocumentStatus.RETRIABLE == {"pending", "failed"}
    assert DocumentStatus.INDEXED not in DocumentStatus.RETRIABLE
    assert DocumentStatus.INDEXING not in DocumentStatus.RETRIABLE


def test_constants_are_strings():
    for attr in ("PENDING", "INDEXING", "INDEXED", "FAILED"):
        assert isinstance(getattr(DocumentStatus, attr), str)

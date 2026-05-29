from __future__ import annotations

import importlib

clean = importlib.import_module("pipeline.02_clean")


def test_normalizes_crlf_to_lf():
    result = clean.run([(1, "line one\r\nline two\r\nline three")])
    assert result == [(1, "line one\nline two\nline three")]


def test_normalizes_cr_only_to_lf():
    result = clean.run([(1, "line one\rline two")])
    assert result == [(1, "line one\nline two")]


def test_collapses_multiple_spaces_and_tabs():
    result = clean.run([(1, "word1   word2\t\tword3")])
    assert result == [(1, "word1 word2 word3")]


def test_compresses_three_or_more_blank_lines_to_two():
    result = clean.run([(1, "paragraph one\n\n\n\n\nparagraph two")])
    assert result == [(1, "paragraph one\n\nparagraph two")]


def test_exactly_two_blank_lines_are_preserved():
    result = clean.run([(1, "a\n\nb")])
    assert result == [(1, "a\n\nb")]


def test_strips_leading_and_trailing_whitespace():
    result = clean.run([(1, "  \n  actual content  \n  ")])
    assert result == [(1, "actual content")]


def test_drops_page_that_is_empty_after_cleaning():
    result = clean.run([(1, "   \t\t  \r\n   "), (2, "real content")])
    assert result == [(2, "real content")]


def test_preserves_page_numbers_from_input():
    result = clean.run([(3, "  page three  "), (7, "page seven\r\ncontinued")])
    assert result[0][0] == 3
    assert result[1][0] == 7


def test_empty_input_returns_empty():
    assert clean.run([]) == []


def test_all_pages_empty_after_clean_returns_empty():
    assert clean.run([(1, "   "), (2, "\t\r\n"), (3, "")]) == []


def test_already_clean_text_passes_through_unchanged():
    result = clean.run([(1, "clean text here")])
    assert result == [(1, "clean text here")]


def test_mixed_crlf_and_multiple_spaces_normalized_together():
    result = clean.run([(1, "a  b\r\n\r\n\r\n\r\nc")])
    assert result == [(1, "a b\n\nc")]


def test_multiple_pages_partial_empty_drops_only_empty_ones():
    result = clean.run([(1, "good"), (2, "   "), (3, "also good")])
    assert [p for p, _ in result] == [1, 3]

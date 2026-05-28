from __future__ import annotations

import importlib

from models.ingest_job import IngestJob

parse_module = importlib.import_module("pipeline.01_parse")


def test_parse_txt_file(fake_ai_provider):
    job = IngestJob(doc_id="doc-1", file_uri="data/sample/policy.txt")
    text = parse_module.run(job, fake_ai_provider)
    assert "reimbursement policy" in text
    assert "Receipts are mandatory" in text


def test_parse_html_file(fake_ai_provider):
    job = IngestJob(doc_id="doc-2", file_uri="data/sample/handbook.html")
    text = parse_module.run(job, fake_ai_provider)
    assert "Onboarding Handbook" in text
    assert "security training" in text

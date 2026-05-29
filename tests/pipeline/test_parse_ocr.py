from __future__ import annotations

import importlib
import sys
import types


parse_module = importlib.import_module("pipeline.01_parse")


class _FakeReader:
    def __init__(self, *_args, **_kwargs) -> None:
        self.pages = [types.SimpleNamespace(extract_text=lambda: "", images=[])]


class _OCRProvider:
    def __init__(self) -> None:
        self.calls: list[bytes] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    def ocr(self, image_bytes: bytes) -> str:
        self.calls.append(image_bytes)
        return "ocr from rendered page"


def test_parse_pdf_falls_back_to_rendered_page_ocr(monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(PdfReader=_FakeReader))

    fake_document = types.SimpleNamespace(
        load_page=lambda _index: types.SimpleNamespace(
            get_pixmap=lambda **_kwargs: types.SimpleNamespace(tobytes=lambda _fmt: b"rendered-page")
        ),
        close=lambda: None,
    )
    monkeypatch.setitem(
        sys.modules,
        "fitz",
        types.SimpleNamespace(
            Matrix=lambda *_args: object(),
            open=lambda **_kwargs: fake_document,
        ),
    )

    ai_provider = _OCRProvider()

    pages = parse_module._parse_pdf(b"%PDF-1.4", ai_provider)

    assert pages == [(1, "ocr from rendered page")]
    assert ai_provider.calls == [b"rendered-page"]

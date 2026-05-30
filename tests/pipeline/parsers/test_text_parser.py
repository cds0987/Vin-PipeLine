"""
Unit tests for pipeline.parsers._text

Covers every supported text format with realistic fake MarkItDown output.
No real files, no AI provider, no network — MarkItDown is fully mocked.

Formats tested:
  .txt  .md  .html  .htm  .docx  .xlsx  .pptx  .pdf  .ipynb
  code files: .py  .js  .ts  .tsx  .json  .yaml  .yml  .csv

Each format test:
  1. Patches MarkItDown to return realistic markdown for that format
  2. Passes in dummy bytes (content doesn't matter — MarkItDown is mocked)
  3. Asserts the parser returns the expected markdown
"""
from __future__ import annotations

import sys
import types

import pytest

# ── MarkItDown mock infrastructure ──────────────────────────────────────────


class _Result:
    """Mimics markitdown.DocumentConverterResult."""
    def __init__(self, text: str | None) -> None:
        self.text_content = text


class _FakeMD:
    """Mimics markitdown.MarkItDown with a fixed conversion result."""
    def __init__(self, text: str | None) -> None:
        self._text = text

    def convert(self, path: str) -> _Result:
        return _Result(self._text)


def _patch(monkeypatch, text: str | None) -> None:
    """Inject a MarkItDown stub that always returns `text`."""
    mod = types.ModuleType("markitdown")
    _t = text  # capture in closure

    class _MD:
        def convert(self, path):
            return _Result(_t)

    mod.MarkItDown = _MD
    monkeypatch.setitem(sys.modules, "markitdown", mod)


# ── realistic fake MarkItDown outputs per format ────────────────────────────

_TXT_MD = """\
Quy định bảo mật thông tin nội bộ

Tất cả nhân viên phải tuân thủ chính sách bảo mật được ban hành.
Không chia sẻ thông tin nội bộ ra bên ngoài tổ chức.
Vi phạm có thể dẫn đến chấm dứt hợp đồng lao động.
"""

_MD_MD = """\
# Hướng dẫn sử dụng hệ thống

## Đăng nhập

Truy cập địa chỉ `https://internal.vsf.vn` và nhập tài khoản được cấp.

## Đổi mật khẩu

1. Vào **Cài đặt** → **Bảo mật**
2. Nhập mật khẩu cũ và mật khẩu mới
3. Nhấn **Lưu**
"""

_HTML_MD = """\
# Thông báo tuyển dụng

**Vị trí:** Kỹ sư phần mềm Backend

## Yêu cầu

- Kinh nghiệm 2+ năm với Python hoặc Go
- Hiểu biết về microservices và REST API
- Có kinh nghiệm với Docker và Kubernetes là lợi thế

## Quyền lợi

- Lương cạnh tranh theo năng lực
- Bảo hiểm sức khoẻ toàn diện
- 15 ngày phép/năm
"""

_DOCX_MD = """\
# Hợp đồng lao động

**Số hợp đồng:** HĐLĐ-2024-0042
**Ngày ký:** 01/06/2024

## Điều 1 — Thông tin các bên

| Bên | Thông tin |
|-----|-----------|
| Người lao động | Nguyễn Văn A |
| Người sử dụng lao động | Công ty CP VSF |

## Điều 2 — Công việc

Vị trí: Kỹ sư phần mềm cấp cao tại Phòng Công nghệ.

## Điều 3 — Thời hạn

Hợp đồng có thời hạn 12 tháng, từ 01/06/2024 đến 31/05/2025.
"""

_XLSX_MD = """\
## Sheet: Danh sách nhân viên

| Mã NV | Họ tên | Phòng ban | Chức danh | Ngày vào |
|-------|--------|-----------|-----------|----------|
| NV001 | Trần Thị B | Kỹ thuật | Senior Engineer | 2021-03-15 |
| NV002 | Lê Văn C | Kinh doanh | Sales Manager | 2020-07-01 |
| NV003 | Phạm Thị D | Nhân sự | HR Specialist | 2022-01-10 |

## Sheet: Phòng ban

| Mã PB | Tên phòng ban | Trưởng phòng |
|-------|--------------|--------------|
| PB01 | Kỹ thuật | Nguyễn Văn E |
| PB02 | Kinh doanh | Hoàng Thị F |
"""

_PPTX_MD = """\
## Slide 1: Kiến trúc hệ thống VSF Platform

Nền tảng công nghệ lõi hỗ trợ 6.000 nhân viên

## Slide 2: Các thành phần chính

- API Gateway
- Service Mesh (Istio)
- Kubernetes cluster trên GKE
- PostgreSQL + Qdrant

## Slide 3: Lộ trình 2025

1. Q1 — Hoàn thiện RAG pipeline
2. Q2 — Triển khai AI chatbot nội bộ
3. Q3 — Tích hợp dữ liệu HR
4. Q4 — Mở rộng sang các công ty con
"""

_PDF_MD = """\
# Báo cáo tài chính Q1/2024

## Tóm tắt điều hành

Doanh thu hợp nhất đạt 2.450 tỷ đồng, tăng 18% so với cùng kỳ.
Lợi nhuận sau thuế đạt 310 tỷ đồng.

## Bảng cân đối kế toán

| Chỉ tiêu | Q1/2024 | Q1/2023 | Tăng trưởng |
|----------|---------|---------|-------------|
| Doanh thu | 2.450 tỷ | 2.076 tỷ | +18% |
| EBITDA | 490 tỷ | 395 tỷ | +24% |
| Lợi nhuận | 310 tỷ | 248 tỷ | +25% |
"""

_IPYNB_MD = """\
# Phân tích dữ liệu nhân sự

## 1. Import thư viện

```python
import pandas as pd
import matplotlib.pyplot as plt
```

## 2. Tải dữ liệu

```python
df = pd.read_csv('hr_data.csv')
df.head()
```

## 3. Kết quả

Tổng số nhân viên: **6.000**
Tỷ lệ giữ chân: **87%**
"""

_PY_MD = """\
```python
def calculate_bonus(salary: float, performance_score: float) -> float:
    \"\"\"Tính thưởng dựa trên lương và điểm hiệu suất.\"\"\"
    if performance_score >= 4.5:
        return salary * 0.3
    elif performance_score >= 3.5:
        return salary * 0.15
    return 0.0
```
"""

_JS_MD = """\
```javascript
async function fetchEmployeeData(employeeId) {
  const response = await fetch(`/api/employees/${employeeId}`);
  if (!response.ok) throw new Error('Employee not found');
  return response.json();
}
```
"""

_JSON_MD = """\
```json
{
  "policy": "reimbursement",
  "version": "2024.1",
  "rules": [
    {"category": "flight", "max_amount": 5000000},
    {"category": "hotel", "max_amount": 800000}
  ]
}
```
"""

_CSV_MD = """\
| date | department | headcount | turnover_rate |
|------|-----------|-----------|---------------|
| 2024-01 | Engineering | 320 | 0.03 |
| 2024-01 | Sales | 480 | 0.05 |
| 2024-01 | HR | 85 | 0.02 |
"""

_YAML_MD = """\
```yaml
service: rag-pipeline
version: "1.0"
environment:
  AI_PROVIDER: openai
  EMBED_MODEL: text-embedding-3-small
  EMBEDDING_DIM: 1536
  VECTOR_STORE: qdrant
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
    cpu: "500m"
```
"""

_TS_MD = """\
```typescript
interface Employee {
  id: string;
  fullName: string;
  department: string;
  salary: number;
}

async function getEmployee(id: string): Promise<Employee> {
  const response = await fetch(`/api/employees/${id}`);
  if (!response.ok) throw new Error(`Employee ${id} not found`);
  return response.json() as Promise<Employee>;
}
```
"""

_TSX_MD = """\
```tsx
import React from 'react';

interface SearchResultProps {
  caption: string;
  score: number;
  sourceUri: string;
}

export const SearchResult: React.FC<SearchResultProps> = ({
  caption, score, sourceUri
}) => (
  <div className="result-card">
    <p>{caption}</p>
    <span>Score: {score.toFixed(2)}</span>
    <a href={sourceUri}>Xem tài liệu gốc</a>
  </div>
);
```
"""


# ── format-specific tests ────────────────────────────────────────────────────

def test_txt_plain_text(monkeypatch):
    _patch(monkeypatch, _TXT_MD)
    from pipeline.parsers import _text
    result = _text.run(b"dummy txt bytes", ".txt")
    assert "bảo mật thông tin" in result
    assert "Vi phạm" in result


def test_md_preserves_markdown_structure(monkeypatch):
    _patch(monkeypatch, _MD_MD)
    from pipeline.parsers import _text
    result = _text.run(b"# already markdown", ".md")
    assert result.startswith("# Hướng dẫn")
    assert "## Đăng nhập" in result
    assert "`https://internal.vsf.vn`" in result


def test_html_headings_and_lists(monkeypatch):
    fake_html = b"<h1>Thong bao</h1><ul><li>Python</li></ul>"
    _patch(monkeypatch, _HTML_MD)
    from pipeline.parsers import _text
    result = _text.run(fake_html, ".html")
    assert "# Thông báo tuyển dụng" in result
    assert "- Kinh nghiệm 2+" in result


def test_htm_same_as_html(monkeypatch):
    _patch(monkeypatch, _HTML_MD)
    from pipeline.parsers import _text
    result = _text.run(b"<p>content</p>", ".htm")
    assert "Thông báo tuyển dụng" in result


def test_docx_contract_with_table(monkeypatch):
    _patch(monkeypatch, _DOCX_MD)
    from pipeline.parsers import _text
    result = _text.run(b"docx binary content", ".docx")
    assert "# Hợp đồng lao động" in result
    assert "| Người lao động | Nguyễn Văn A |" in result
    assert "## Điều 3" in result


def test_xlsx_tables_from_sheets(monkeypatch):
    _patch(monkeypatch, _XLSX_MD)
    from pipeline.parsers import _text
    result = _text.run(b"xlsx binary", ".xlsx")
    assert "## Sheet: Danh sách nhân viên" in result
    assert "| NV001 |" in result
    assert "## Sheet: Phòng ban" in result


def test_pptx_slides_as_sections(monkeypatch):
    _patch(monkeypatch, _PPTX_MD)
    from pipeline.parsers import _text
    result = _text.run(b"pptx binary", ".pptx")
    assert "## Slide 1:" in result
    assert "## Slide 3:" in result
    assert "Q1 — Hoàn thiện RAG pipeline" in result


def test_pdf_text_layer_with_tables(monkeypatch):
    _patch(monkeypatch, _PDF_MD)
    from pipeline.parsers import _text
    result = _text.run(b"%PDF-1.4 content", ".pdf")
    assert "# Báo cáo tài chính" in result
    assert "+18%" in result
    assert "| EBITDA |" in result


def test_ipynb_notebook_with_code_blocks(monkeypatch):
    _patch(monkeypatch, _IPYNB_MD)
    from pipeline.parsers import _text
    result = _text.run(b'{"cells": []}', ".ipynb")
    assert "# Phân tích dữ liệu nhân sự" in result
    assert "```python" in result
    assert "pd.read_csv" in result


def test_py_code_file(monkeypatch):
    _patch(monkeypatch, _PY_MD)
    from pipeline.parsers import _text
    result = _text.run(b"def calculate_bonus(): pass", ".py")
    assert "calculate_bonus" in result
    assert "```python" in result


def test_js_code_file(monkeypatch):
    _patch(monkeypatch, _JS_MD)
    from pipeline.parsers import _text
    result = _text.run(b"async function fetchEmployeeData() {}", ".js")
    assert "fetchEmployeeData" in result


def test_json_config_file(monkeypatch):
    _patch(monkeypatch, _JSON_MD)
    from pipeline.parsers import _text
    result = _text.run(b'{"policy": "reimbursement"}', ".json")
    assert "reimbursement" in result
    assert "5000000" in result


def test_csv_data_file(monkeypatch):
    _patch(monkeypatch, _CSV_MD)
    from pipeline.parsers import _text
    result = _text.run(b"date,department,headcount", ".csv")
    assert "| 2024-01 |" in result
    assert "turnover_rate" in result


def test_yaml_config_file(monkeypatch):
    _patch(monkeypatch, _YAML_MD)
    from pipeline.parsers import _text
    result = _text.run(b"service: rag-pipeline", ".yaml")
    assert "rag-pipeline" in result
    assert "EMBEDDING_DIM" in result
    assert "```yaml" in result


def test_yml_alias_same_as_yaml(monkeypatch):
    _patch(monkeypatch, _YAML_MD)
    from pipeline.parsers import _text
    result = _text.run(b"service: rag-pipeline", ".yml")
    assert "rag-pipeline" in result


def test_ts_typescript_file(monkeypatch):
    _patch(monkeypatch, _TS_MD)
    from pipeline.parsers import _text
    result = _text.run(b"interface Employee {}", ".ts")
    assert "interface Employee" in result
    assert "Promise<Employee>" in result
    assert "```typescript" in result


def test_tsx_react_component(monkeypatch):
    _patch(monkeypatch, _TSX_MD)
    from pipeline.parsers import _text
    result = _text.run(b"export const SearchResult", ".tsx")
    assert "SearchResult" in result
    assert "SearchResultProps" in result
    assert "```tsx" in result


# ── edge cases ───────────────────────────────────────────────────────────────

def test_empty_file_returns_empty_string(monkeypatch):
    _patch(monkeypatch, "")
    from pipeline.parsers import _text
    for suffix in [".txt", ".docx", ".pdf", ".md", ".xlsx", ".pptx", ".html"]:
        assert _text.run(b"", suffix) == ""


def test_whitespace_only_content_returns_empty(monkeypatch):
    _patch(monkeypatch, "   \n\n\t  \n  ")
    from pipeline.parsers import _text
    assert _text.run(b"   ", ".txt") == ""


def test_markitdown_returns_none_gives_empty_string(monkeypatch):
    _patch(monkeypatch, None)
    from pipeline.parsers import _text
    assert _text.run(b"data", ".pdf") == ""


def test_output_is_stripped(monkeypatch):
    _patch(monkeypatch, "\n\n# Title\n\nContent\n\n")
    from pipeline.parsers import _text
    result = _text.run(b"x", ".md")
    assert result == "# Title\n\nContent"
    assert not result.startswith("\n")
    assert not result.endswith("\n")


def test_vietnamese_content_preserved(monkeypatch):
    vietnamese = "# Chính sách nghỉ phép\n\nNhân viên được nghỉ 15 ngày/năm."
    _patch(monkeypatch, vietnamese)
    from pipeline.parsers import _text
    result = _text.run("chính sách nghỉ phép".encode("utf-8"), ".txt")
    assert "Chính sách nghỉ phép" in result
    assert "15 ngày/năm" in result


def test_large_document_returned_in_full(monkeypatch):
    large = "\n\n".join(f"## Section {i}\n\n" + "Nội dung section. " * 50
                        for i in range(1, 51))
    _patch(monkeypatch, large)
    from pipeline.parsers import _text
    result = _text.run(b"large doc", ".docx")
    assert "## Section 1" in result
    assert "## Section 50" in result
    assert len(result) > 10_000


def test_special_characters_preserved(monkeypatch):
    special = "# Title\n\nPrice: $1,000 — Discount: 10% & more\n\n<b>not html</b>"
    _patch(monkeypatch, special)
    from pipeline.parsers import _text
    result = _text.run(b"data", ".txt")
    assert "$1,000" in result
    assert "<b>not html</b>" in result


# ── suffix normalisation ─────────────────────────────────────────────────────

@pytest.mark.parametrize("suffix", [
    ".PDF", ".DOCX", ".TXT", ".MD", ".HTML", ".XLSX", ".PPTX", ".IPYNB",
    ".YAML", ".YML", ".TS", ".TSX", ".CSV", ".JSON", ".PY", ".JS",
])
def test_uppercase_suffix_handled(monkeypatch, suffix):
    _patch(monkeypatch, "content")
    from pipeline.parsers import _text
    result = _text.run(b"data", suffix)
    assert result == "content"


# ── tempfile content integrity ───────────────────────────────────────────────


def test_input_bytes_written_to_tempfile(monkeypatch):
    """Bytes passed to run() must be what MarkItDown actually reads."""
    import os
    import tempfile as _tf

    expected_bytes = b"VSF internal document content \xc3\xa0\xc3\xa1"  # UTF-8 Vietnamese
    bytes_on_disk: list[bytes] = []

    _real = _tf.NamedTemporaryFile

    class _CapturingTemp:
        def __init__(self, suffix, delete):
            self._inner = _real(suffix=suffix, delete=delete)

        def __enter__(self):
            return self._inner.__enter__()

        def __exit__(self, *args):
            # Read what was written before the file is closed/deleted.
            self._inner.flush()
            self._inner.seek(0)
            bytes_on_disk.append(self._inner.read())
            return self._inner.__exit__(*args)

        # Proxy write so _text.py can call f.write() normally.
        def write(self, data):
            return self._inner.write(data)

        @property
        def name(self):
            return self._inner.name

    monkeypatch.setattr(_tf, "NamedTemporaryFile", _CapturingTemp)
    _patch(monkeypatch, "result")

    from pipeline.parsers import _text
    _text.run(expected_bytes, ".txt")

    assert bytes_on_disk, "tempfile context was never exited"
    assert bytes_on_disk[0] == expected_bytes, (
        f"expected {expected_bytes!r}, got {bytes_on_disk[0]!r}"
    )


def test_different_byte_inputs_each_written_correctly(monkeypatch):
    """Each run() call writes its own distinct bytes — no cross-contamination."""
    import tempfile as _tf

    _real = _tf.NamedTemporaryFile
    written: list[bytes] = []

    class _CapturingTemp:
        def __init__(self, suffix, delete):
            self._inner = _real(suffix=suffix, delete=delete)

        def __enter__(self):
            return self._inner.__enter__()

        def __exit__(self, *args):
            self._inner.flush()
            self._inner.seek(0)
            written.append(self._inner.read())
            return self._inner.__exit__(*args)

        def write(self, data):
            return self._inner.write(data)

        @property
        def name(self):
            return self._inner.name

    monkeypatch.setattr(_tf, "NamedTemporaryFile", _CapturingTemp)
    _patch(monkeypatch, "result")

    from pipeline.parsers import _text
    inputs = [b"document one", b"document two", b"document three"]
    for data in inputs:
        _text.run(data, ".txt")

    assert written == inputs


# ── tempfile cleanup ─────────────────────────────────────────────────────────

def test_tempfile_deleted_after_conversion(monkeypatch):
    """Temp file must not remain on disk after run() returns."""
    import os
    import tempfile as _tf

    # Capture the REAL function before monkeypatch replaces it.
    _real = _tf.NamedTemporaryFile
    created: list[str] = []

    class _SpyTemp:
        def __init__(self, suffix, delete):
            self._real = _real(suffix=suffix, delete=delete)
            created.append(self._real.name)

        def __enter__(self):
            return self._real.__enter__()

        def __exit__(self, *args):
            return self._real.__exit__(*args)

    monkeypatch.setattr(_tf, "NamedTemporaryFile", _SpyTemp)
    _patch(monkeypatch, "ok")

    from pipeline.parsers import _text
    _text.run(b"data", ".txt")

    assert created, "no tempfile was created"
    assert not os.path.exists(created[0]), "tempfile was not deleted"


def test_tempfile_suffix_matches_input_suffix(monkeypatch):
    import tempfile as _tf

    _real = _tf.NamedTemporaryFile
    seen: list[str] = []

    class _SpySuffix:
        def __init__(self, suffix, delete):
            seen.append(suffix)
            self._real = _real(suffix=suffix, delete=delete)

        def __enter__(self): return self._real.__enter__()
        def __exit__(self, *a): return self._real.__exit__(*a)

    monkeypatch.setattr(_tf, "NamedTemporaryFile", _SpySuffix)
    _patch(monkeypatch, "ok")

    from pipeline.parsers import _text
    for suffix in [".docx", ".pdf", ".xlsx", ".pptx", ".ipynb"]:
        seen.clear()
        _text.run(b"data", suffix)
        assert seen[0] == suffix

# Architecture

## Kiến trúc đang áp dụng

Runtime của service đi theo hướng `Markdown -> Section -> Caption -> Search`. Chunk 512 token không còn là retrieval unit.

Luồng tổng quát:

```text
S3 / local source
  ->
IngestJob
  ->
parse -> save markdown -> split sections -> caption -> embed -> index
  ->
Vector store + metadata store
  ->
/search
  ->
section-centric response
```

## Cấu trúc module

```text
app/
  domain/          ← model và rule nghiệp vụ, không phụ thuộc SDK
  application/     ← use cases
  ports/           ← contract giữa application và infrastructure
  infrastructure/  ← implementation cụ thể (SDK, DB, storage)
  bootstrap/       ← composition root duy nhất

api/               ← FastAPI endpoints (validate request, gọi use case, map response)
utils/             ← backward-compat re-exports; new code không import trực tiếp
models/            ← backward-compat alias (ChunkResult = SectionRecord)
pipeline/          ← thin wrappers cũ; logic thật đã nằm trong app/
retrieval/         ← thin wrapper cũ; logic thật là SearchSections use case
```

## `app/domain`

Model nghiệp vụ cốt lõi — không phụ thuộc FastAPI, SQLAlchemy, SDK nào:

| Model | Mô tả |
|---|---|
| `IngestJob` | Mô tả file cần xử lý: `doc_id`, `file_uri`, `document_type`, `language` |
| `MarkdownDocument` | Kết quả parse: `markdown_content`, `markdown_s3_uri`, `source_uri`, `parser_version` |
| `SectionRecord` | Section đầy đủ: `section_id`, `doc_id`, `section_content`, `caption`, `heading`, `heading_path`, `section_order`, `embedding`, `markdown_s3_uri`, `source_s3_uri` |
| `DocumentRecord` | Metadata document trong DB: status, `parser_version`, `caption_model`, `embedding_model`, timestamps |
| `SectionSearchResult` | Response search: fields SectionRecord + `score`, `document_name` |

Business rule: `app/domain/ingestion/policies.py` — `is_stale_indexing`.

## `app/application`

Use cases — orchestrate, không chứa SDK logic:

| File | Use case |
|---|---|
| `ingest/run_ingest_job.py` | `RunIngestJob` — read → parse → store md → split → caption → embed → index |
| `ingest/index_sections.py` | `DocumentIndexService` — ghi sections vào index + cập nhật DocumentRecord |
| `search/search_sections.py` | `SearchSections` — embed query + search + trả `SectionSearchResult` |
| `scan/scan_documents.py` | `ScanDocuments` — gọi scanner, trả danh sách `IngestJob` |
| `status/get_document_status.py` | `GetDocumentStatus` — trả `DocumentStatusResult` từ repository |

## `app/ports`

Contract giữa application và infrastructure. Application chỉ được phép phụ thuộc vào ports, không được import trực tiếp infra:

| File | Protocols |
|---|---|
| `parsing.py` | `DocumentParser` |
| `storage.py` | `BinaryReader`, `MarkdownStore` |
| `sectioning.py` | `SectionSplitter`, `SectionCaptioner` |
| `ai.py` | `EmbeddingProvider`, `SectionEmbedder`, `CaptionProvider` |
| `vector_index.py` | `SectionIndex` |
| `repositories.py` | `DocumentRepository`, `IngestClaimRepository`, `JobLogRepository` |
| `scanning.py` | `SourceScanner` |

## `app/infrastructure`

Implementation cụ thể cho từng port:

| Folder | Implementations |
|---|---|
| `parser/` | `RouterDocumentParser` → gọi `pipeline/parsers/` |
| `sectioning/` | `HeadingSectionSplitter` |
| `ai/` | `AISectionCaptioner`, `AISectionEmbedder` |
| `storage/` | `StorageBinaryReader`, `ArtifactMarkdownStore` |
| `vector/` | `VectorStoreSectionIndex` (adapter), `QdrantStore`, `InMemoryVectorStore` |
| `repositories/` | `MetadataStoreRepository` (adapter), `SQLMetadataStore`, `FileMetadataStore`, `InMemoryMetadataStore` |
| `scanning/` | `S3SourceScanner` |

## `app/bootstrap`

`container.py` là composition root duy nhất:

- Đọc environment để chọn implementation (Qdrant vs memory, Postgres vs file...)
- Build tất cả infrastructure objects
- Wire dependency vào use cases
- Trả `Container` chỉ expose use cases + `degraded_reasons` + `system_info`
- `api/main.py` không được biết implementation cụ thể nào đang dùng

## Parser layer

```text
pipeline/parsers/
  __init__.py    ← entry point duy nhất: run(file_bytes, suffix, ai_provider)
  _text.py       ← text-like formats (.txt, .md, .html, .ipynb...)
  _visual.py     ← visual/mixed formats (.pdf, .docx, .png...)
```

Được gọi bởi `RouterDocumentParser` trong `app/infrastructure/parser/router.py`.

## Dependency direction

```
api/
  ↓
app/application/
  ↓
app/ports/  ←  app/infrastructure/
  ↓
app/domain/
```

**Không được phép:**
- `app/application/` import `boto3`, `openai`, `qdrant_client`, `sqlalchemy`
- `app/domain/` import FastAPI, SQLAlchemy, bất kỳ provider nào
- `api/main.py` tự build dependency hay truy cập implementation details của container

## Contract trả về

`SectionSearchResult` — response của `/search`:

```json
{
  "section_id": "doc_123_section_0007",
  "document_id": "doc_123",
  "document_name": "travel_policy.pdf",
  "caption": "Quy định về mức hoàn tiền tối đa...",
  "section_content": "## Hoàn tiền vé máy bay\n...\n",
  "heading_path": ["Chính sách công tác", "Hoàn tiền vé máy bay"],
  "markdown_s3_uri": "s3://bucket/rag-derived/markdown/doc_123.md",
  "source_s3_uri": "s3://bucket/raw/hr/travel_policy.pdf",
  "score": 0.91
}
```

`SectionRecord` — data contract trung gian qua pipeline:

- `section_id`, `doc_id`, `section_content`, `caption`, `embedding`
- `heading` — heading text của section (leaf của `heading_path`)
- `heading_path` — danh sách heading từ root đến section hiện tại
- `section_order` — thứ tự 0-based trong document
- `markdown_s3_uri`, `source_s3_uri`

## Backward compat (temporary)

Các thứ còn tồn tại để không gãy tests và legacy code; sẽ bị xóa sau migration hoàn tất:

- `models/ingest_job.py` — `ChunkResult = SectionRecord`, re-export domain models
- `utils/stores.py` — re-export `QdrantStore`, `InMemoryVectorStore`, `SQLMetadataStore`...
- `pipeline/run.py`, `pipeline/01_parse.py`... — thin wrappers

Xem `LEGACY.md` để biết đầy đủ.

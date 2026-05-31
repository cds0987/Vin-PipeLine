# Pipeline Runtime

## Mục tiêu hiện tại

Pipeline runtime đã được chuyển theo hướng `Markdown -> Section -> Caption -> Search`.

Mục tiêu của flow mới:

- chuẩn hóa mọi tài liệu về Markdown
- lưu Markdown thành artifact có URI ổn định
- chia tài liệu thành các section có nghĩa
- sinh caption cho từng section
- embed caption để phục vụ semantic retrieval
- trả về full section cùng `markdown_s3_uri` và `source_s3_uri`

## Luồng ingest

```text
Source file
  ->
Parse to Markdown
  ->
Clean Markdown
  ->
Save Markdown artifact
  ->
Split Markdown into sections
  ->
Generate caption for each section
  ->
Embed captions
  ->
Index section records
  ->
Update metadata / job status
```

## Luồng search

```text
Query
  ->
Embed query
  ->
Search caption vectors
  ->
Return section results
```

Mỗi kết quả search là một section-centric result:

```json
{
  "section_id": "doc_123_section_0007",
  "document_id": "doc_123",
  "document_name": "travel_policy.pdf",
  "caption": "Quy định về mức hoàn tiền tối đa cho vé máy bay công tác...",
  "section_content": "## Hoàn tiền vé máy bay\n...\n",
  "heading_path": ["Chính sách công tác", "Hoàn tiền vé máy bay"],
  "markdown_s3_uri": "s3://bucket/rag-derived/markdown/doc_123.md",
  "source_s3_uri": "s3://bucket/raw/hr/travel_policy.pdf",
  "score": 0.91
}
```

## Use cases (runtime core)

| Use case | File | Mô tả |
|---|---|---|
| `RunIngestJob` | [app/application/ingest/run_ingest_job.py](app/application/ingest/run_ingest_job.py) | Orchestrate toàn bộ pipeline ingest |
| `DocumentIndexService` | [app/application/ingest/index_sections.py](app/application/ingest/index_sections.py) | Ghi sections vào index, cập nhật metadata |
| `SearchSections` | [app/application/search/search_sections.py](app/application/search/search_sections.py) | Embed query, search vector, trả section results |
| `ScanDocuments` | [app/application/scan/scan_documents.py](app/application/scan/scan_documents.py) | Quét S3 để sinh danh sách IngestJob |
| `GetDocumentStatus` | [app/application/status/get_document_status.py](app/application/status/get_document_status.py) | Trả trạng thái và metadata của một document |

## Ports (contract giữa application và infrastructure)

| Port | File | Trách nhiệm |
|---|---|---|
| `DocumentParser` | `app/ports/parsing.py` | `(IngestJob, bytes) → MarkdownDocument` |
| `BinaryReader` | `app/ports/storage.py` | Đọc file bytes từ URI |
| `MarkdownStore` | `app/ports/storage.py` | Lưu và đọc Markdown artifact |
| `SectionSplitter` | `app/ports/sectioning.py` | `MarkdownDocument → list[SectionRecord]` |
| `SectionCaptioner` | `app/ports/sectioning.py` | Sinh caption cho từng section |
| `SectionEmbedder` | `app/ports/ai.py` | Embed caption, gắn vector vào section |
| `EmbeddingProvider` | `app/ports/ai.py` | `list[str] → list[list[float]]` |
| `SectionIndex` | `app/ports/vector_index.py` | Upsert / search / delete sections trong vector store |
| `DocumentRepository` | `app/ports/repositories.py` | CRUD document metadata |
| `IngestClaimRepository` | `app/ports/repositories.py` | Claim ingest job (concurrency control) |
| `JobLogRepository` | `app/ports/repositories.py` | Ghi job log |
| `SourceScanner` | `app/ports/scanning.py` | Quét nguồn tài liệu |

## Data contracts giữa các bước

| Model | Mô tả |
|---|---|
| `IngestJob` | Thông tin nguồn file cần xử lý |
| `MarkdownDocument` | Kết quả parse: `markdown_content`, `markdown_s3_uri`, `source_uri` |
| `SectionRecord` | Section hoàn chỉnh: `section_id`, `doc_id`, `section_content`, `caption`, `heading`, `heading_path`, `section_order`, `markdown_s3_uri`, `source_s3_uri`, `embedding` |
| `SectionSearchResult` | Response search: fields trên + `score`, `document_name` |
| `DocumentRecord` | Metadata document trong DB: status, parser_version, caption_model, embedding_model... |

## Entry points

**Runtime core:**
- [app/bootstrap/container.py](app/bootstrap/container.py) — composition root duy nhất, wiring mọi dependency
- [api/main.py](api/main.py) — FastAPI endpoints: `/search`, `/scan`, `/status/{doc_id}`, `/health`

**Legacy wrappers (thin, chỉ gọi sang `app/`):**
- `pipeline/run.py` — gọi `RunIngestJob`
- `pipeline/parsers/__init__.py` — entry point parser thống nhất, được gọi bởi `RouterDocumentParser`

## Artifact trung gian

Markdown artifact được lưu bởi [app/infrastructure/storage/markdown_store.py](app/infrastructure/storage/markdown_store.py) (`ArtifactMarkdownStore`).

Storage có thể chạy theo 3 mức:

1. **Optimal** — bucket hoặc prefix riêng cho derived Markdown (production)
2. **Acceptable** — chung bucket nhưng prefix riêng (`MARKDOWN_S3_PREFIX`)
3. **Temporary / Dev** — local filesystem hoặc MinIO

Key lưu: `{MARKDOWN_S3_PREFIX}/{doc_id}.md`

## Kiến trúc sạch

Pipeline đi theo dependency direction:

```
api/ → app/application/ → app/ports/ ← app/infrastructure/
                        ↑
                   app/domain/
```

- `app/domain/` không phụ thuộc vào bất kỳ framework hay SDK nào
- `app/application/` chỉ phụ thuộc vào `app/ports/` và `app/domain/`
- `app/infrastructure/` implement các ports, được phép dùng SDK cụ thể
- `app/bootstrap/container.py` là nơi duy nhất chọn implementation theo environment

## API endpoints

| Method | Path | Mô tả |
|---|---|---|
| `POST` | `/search` | Semantic search — `query`, `top_k` |
| `POST` | `/scan` | Trigger scan S3 — `bucket`, `prefix` (optional) |
| `GET` | `/status/{doc_id}` | Trạng thái và metadata document |
| `GET` | `/health` | Service health + degraded reasons |

### `/status/{doc_id}` response

```json
{
  "doc_id": "...",
  "status": "indexed",
  "file_path": "s3://...",
  "source_s3_uri": "s3://...",
  "markdown_s3_uri": "s3://...",
  "file_type": "pdf",
  "section_count": 12,
  "parser_version": "pipeline.parsers.v1",
  "caption_model": "heuristic",
  "embedding_model": "text-embedding-3-small",
  "uploaded_at": "2026-01-01T00:00:00Z",
  "processed_at": "2026-01-01T00:01:00Z"
}
```

## Env vars quan trọng

| Var | Mặc định | Ý nghĩa |
|---|---|---|
| `AI_PROVIDER` | `auto` | `openai`, `openrouter`, `mock`, `auto` |
| `AI_API_KEY` | — | API key cho AI provider |
| `EMBED_MODEL` | `text-embedding-3-small` | Model embedding |
| `CAPTION_MODEL` | `heuristic` | Model/strategy caption |
| `EMBEDDING_DIM` | `1536` | Dimension vector |
| `VECTOR_STORE` | `qdrant` | `qdrant` hoặc `memory` |
| `METADATA_STORE` | `postgres` | `postgres`, `file`, `memory` |
| `S3_BUCKET` | `rag-pipeline-local` | Bucket chứa raw source |
| `MARKDOWN_BUCKET` | (= S3_BUCKET) | Bucket lưu Markdown artifact |
| `MARKDOWN_S3_PREFIX` | `rag-derived/markdown` | Prefix cho Markdown artifact |
| `USE_S3` | `false` | Bật S3 thật (tắt = local filesystem) |
| `SCAN_INTERVAL_SECONDS` | `300` | Interval scanner; 0 = disable |
| `SEARCH_SCORE_THRESHOLD` | `0.5` | Minimum cosine similarity; 0.0 = disable |
| `CAPTION_MAX_CONCURRENCY` | `5` | Số caption call đồng thời tối đa toàn system (`asyncio.Semaphore`) |
| `EMBED_BATCH_WINDOW_MS` | `5` | BatchEmbedder: chờ tối đa bao lâu trước khi flush (production nên đặt `50`–`100`) |
| `EMBED_MAX_BATCH_SIZE` | `32` | BatchEmbedder: flush ngay khi queue đạt size này |
| `EMBED_CACHE_SIZE` | `4096` | BatchEmbedder: số vector cache tối đa (LRU theo content hash) |

> Pipeline ingest chạy async: `RunIngestJob.execute` là coroutine, caption song song qua `Semaphore`, embedding gom cross-job qua **BatchEmbedder** (singleton trong container). Chi tiết: [notes/BATCH_EMBEDDER.md](./notes/BATCH_EMBEDDER.md). Trạng thái async refactor: [STATUS.md](./STATUS.md).

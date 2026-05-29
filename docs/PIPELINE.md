# Pipeline — Implementation Reference

Tài liệu này mô tả chi tiết implementation: từng bước pipeline, API contracts, database schema, env vars. Để hiểu tại sao system thiết kế thế này → đọc `ARCHITECTURE.md`. Rules cứng → `AGENTS.md`.

## Luồng end-to-end

```text
S3 bucket
    │
    ▼
S3 scanner (poll theo SCAN_INTERVAL_SECONDS)
    │  phát hiện file mới / thay đổi / failed / stale
    ▼
IngestJob
    │
    ▼
pipeline.run(job)
    │
    ├─> 01_parse
    ├─> 02_clean
    ├─> 03_chunk
    ├─> 04_embed
    └─> 05_index
              │
    ┌─────────┴─────────┐
    ▼                   ▼
Vector store       Metadata store
              │
              ▼
    RetrievalService
              │
              ▼
        POST /search  ──> caller
```

## Lớp kiến trúc

1. **S3 scanner**: nguồn duy nhất đưa tài liệu vào
2. **Ingestion pipeline**: `01_parse` → `02_clean` → `03_chunk` → `04_embed` → `05_index`
3. **Storage layer**: vector store + metadata store
4. **Serving layer**: FastAPI — `search`, `scan`, `status`, `health`

## S3 scanner

`adapters/s3_adapter.py` quét bucket theo `SCAN_PREFIX`.

Scanner tạo `IngestJob` khi:

- file chưa có trong metadata store
- file đang `failed` hoặc `pending`
- file `indexing` nhưng đã stale (vượt `STALE_INDEXING_SECONDS`)
- `s3_last_modified` trên S3 mới hơn bản đã lưu

Scanner bỏ qua:

- file suffix không được hỗ trợ
- file đang indexing và chưa stale
- file đã indexed và không thay đổi

`/scan` trong REST API trigger cùng logic này theo yêu cầu thủ công — không phải luồng vào độc lập.

## 5 bước pipeline

### 1. Parse

`pipeline/01_parse.py`

Input: `IngestJob` + `file_bytes: bytes`
Output: `list[tuple[int, str]]`

Boundary:

- `01_parse.py` chỉ biết `bytes + suffix -> pages`
- IO đọc file nằm ở `pipeline/run.py` qua `read_binary(job.file_uri)`
- parse stage không biết file đến từ local path, S3 hay backend storage nào khác

Định dạng hỗ trợ:

- `.pdf`
- `.docx`
- `.txt`
- `.md`
- `.html`, `.htm`
- `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tiff`

Chi tiết:

- PDF: ưu tiên text layer qua `pypdf`
- trang PDF rỗng: fallback OCR bằng vision model
- image files: OCR trực tiếp qua `AIProvider.ocr()`

### 2. Clean

`pipeline/02_clean.py`

Input: `list[tuple[int, str]]`
Output: `list[tuple[int, str]]`

Xử lý chính:

- chuẩn hóa line endings
- collapse khoảng trắng dư
- giảm số dòng trống liên tiếp
- loại trang rỗng sau khi clean

### 3. Chunk

`pipeline/03_chunk.py`

Input: clean pages + `IngestJob`
Output: `list[ChunkResult]`

Mặc định:

- `CHUNK_SIZE=512`
- `CHUNK_OVERLAP=64`

Chunk metadata bao gồm:

- `chunk_index`
- `chunk_strategy`
- `language`
- `document_type`
- `token_start`
- `token_end`

Chunk id format: `{doc_id}_chunk_{index:04d}`

### 4. Embed

`pipeline/04_embed.py`

Input: `list[ChunkResult]`
Output: `list[ChunkResult]` đã có `embedding`

Runtime:

- gọi `AIProvider.embed()`
- xử lý theo batch
- ghi `embedding_model` vào metadata từng chunk

### 5. Index

`pipeline/05_index.py`

Input: chunks + job + stores
Output:

```json
{
  "doc_id": "doc_123",
  "status": "indexed",
  "chunk_count": 42
}
```

Flow chính:

1. xóa vector cũ theo `doc_id`
2. cập nhật document status sang `indexing`
3. upsert metadata document
4. ghi `s3_uri` vào metadata của mỗi chunk
5. upsert chunks vào vector store
6. update `processed_at`, `total_chunks`, `status=indexed`
7. record một row mới trong `ingestion_jobs`

Nếu lỗi:

- record `ingestion_jobs` với `status=failed`
- update document status thành `failed`
- lỗi được re-raise lên orchestrator
- S3 scanner sẽ retry document này ở chu kỳ scan tiếp theo

## Orchestrator

`pipeline/run.py` là entry point chuẩn, được gọi duy nhất từ S3 scanner.

Nó chịu trách nhiệm:

- build dependencies nếu caller không inject
- đọc file bytes qua `read_binary(job.file_uri)` trước khi gọi parse — `read_binary` enforce `MAX_FILE_SIZE_BYTES` trước khi đọc (head request với S3, `stat()` với local)
- `try_claim_ingest()` để tránh double-run cùng `doc_id`
- deadline guard theo `SCAN_JOB_TIMEOUT_SECONDS`
- fail-fast nếu parse/chunk sinh nội dung rỗng
- detect `language` từ nội dung sau bước `clean`

Nếu document đang `indexing` và chưa stale, pipeline trả:

```json
{
  "doc_id": "doc_123",
  "status": "skipped",
  "chunk_count": 0
}
```

## Retrieval flow

`retrieval/service.py` — luồng ra duy nhất.

Flow:

1. nhận query text từ `POST /search`
2. embed query qua `AIProvider.embed([query])`
3. fetch `top_k * 3` candidates từ `VectorStore.search()` khi threshold > 0 (đủ buffer sau khi filter)
4. filter theo `SEARCH_SCORE_THRESHOLD`
5. slice `[:top_k]` và trả về caller — caller luôn nhận đúng số lượng yêu cầu

Service có cache query embedding dạng LRU đơn giản trong memory process.

## REST API

### `POST /search` — luồng ra

Request:

```json
{
  "query": "travel reimbursement",
  "top_k": 5
}
```

Response:

```json
{
  "request_id": "uuid",
  "results": [
    {
      "chunk_id": "doc_1_chunk_0000",
      "content": "....",
      "score": 0.82,
      "s3_uri": "s3://bucket/path/file.pdf",
      "page_start": 1,
      "page_end": 1,
      "section": null,
      "doc_id": "doc_1"
    }
  ]
}
```

Validation:

- `query` không được blank
- `query` có `max_length = SEARCH_QUERY_MAX_LENGTH`
- `top_k` trong khoảng `1..50`

### `POST /scan` — operational

Trigger thủ công một chu kỳ S3 scanner. Cùng logic với scanner tự động.

Request:

```json
{
  "bucket": "rag-pipeline-local",
  "prefix": "raw/"
}
```

Response:

```json
{
  "status": "scan started",
  "queued": 12
}
```

Nếu đang có scan khác chạy: trả `409`.

### `GET /status/{doc_id}` — operational

Response:

```json
{
  "doc_id": "doc_1",
  "status": "indexed",
  "file_path": "s3://bucket/file.pdf",
  "file_type": "pdf",
  "total_chunks": 42,
  "uploaded_at": "2026-05-29T10:00:00+00:00",
  "processed_at": "2026-05-29T10:00:05+00:00"
}
```

### `GET /health` — operational

Response khi khỏe:

```json
{
  "status": "ok",
  "vector_store": "QdrantStore",
  "metadata_store": "SQLMetadataStore",
  "ai_provider": "OpenAIProvider",
  "scanner": "enabled",
  "degraded_reasons": []
}
```

Response khi fallback/degraded:

```json
{
  "status": "degraded",
  "vector_store": "InMemoryVectorStore",
  "metadata_store": "FileMetadataStore",
  "ai_provider": "MockAIProvider",
  "scanner": "disabled",
  "degraded_reasons": [
    "QdrantStore unavailable: ...",
    "SQLMetadataStore unavailable: ..."
  ]
}
```

## Storage layer

### VectorStore contract

```python
class VectorStore(Protocol):
    def upsert(self, chunks: list[ChunkResult]) -> None: ...
    def search(self, vector: list[float], top_k: int, filters: dict | None = None) -> list[ChunkResult]: ...
    def delete(self, doc_id: str) -> None: ...
```

Implementations:

- `QdrantStore`
- `InMemoryVectorStore`

### MetadataStore contract

```python
class MetadataStore(Protocol):
    def upsert(self, doc: DocumentRecord) -> None: ...
    def update_status(self, doc_id: str, status: str) -> None: ...
    def get_document(self, doc_id: str) -> DocumentRecord | None: ...
    def get_by_file_path(self, file_path: str) -> DocumentRecord | None: ...
    def get_by_file_paths(self, file_paths: list[str]) -> dict[str, DocumentRecord]: ...
    def upsert_chunks(self, chunks: list[ChunkResult]) -> None: ...
    def try_claim_ingest(self, job: IngestJob) -> bool: ...
    def record_job(...) -> None: ...
    def update_processed(...) -> None: ...
```

Implementations:

- `SQLMetadataStore`
- `FileMetadataStore`
- `InMemoryMetadataStore`

## Database schema

### `documents`

| Column | Nguồn |
|---|---|
| `id` | MD5 hash của S3 URI — từ scanner |
| `file_path` | S3 URI — từ scanner |
| `file_name` | typed field trên `IngestJob`, set từ scanner |
| `file_type` | file extension — từ scanner |
| `document_type` | first path segment sau SCAN_PREFIX — từ scanner |
| `title` | `file_name` — set bởi `05_index.py` |
| `language` | detect từ nội dung document — set bởi `run.py` sau `clean` |
| `status` | pipeline quản lý (`pending` → `indexing` → `indexed` / `failed`) |
| `total_chunks` | pipeline tính sau khi chunk |
| `s3_last_modified` | `obj["LastModified"]` — từ scanner |
| `uploaded_at` | thời điểm pipeline bắt đầu xử lý lần đầu |
| `processed_at` | thời điểm index hoàn thành |
| `updated_at` | pipeline update mỗi khi ghi |

Không có field nào phụ thuộc vào metadata do người dùng tự gắn hoặc external service.

### `ingestion_jobs`

- `id`
- `doc_id`
- `status`
- `chunk_count`
- `embedding_model`
- `duration_seconds`
- `error_message`
- `started_at`
- `finished_at`

## Runtime config

- AI: `AI_PROVIDER`, `AI_BASE_URL`, `AI_API_KEY`, `EMBED_MODEL`, `VISION_MODEL`, `EMBEDDING_DIM`
- chunking: `CHUNK_SIZE`, `CHUNK_OVERLAP`
- vector store: `VECTOR_STORE`, `QDRANT_HOST`, `QDRANT_PORT`, `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION`
- metadata store: `METADATA_STORE`, `DATABASE_URL`
- S3: `USE_S3`, `S3_BUCKET`, `S3_ENDPOINT`, `SCAN_INTERVAL_SECONDS`, `SCAN_PREFIX`, `SCAN_MAX_WORKERS`, `SCAN_JOB_TIMEOUT_SECONDS`
- retrieval: `SEARCH_SCORE_THRESHOLD`, `SEARCH_QUERY_MAX_LENGTH`, `SEARCH_QUERY_CACHE_SIZE`

## Build fallbacks

- `build_ai_provider()` trả `(provider, warning)`
- `build_vector_store()` trả `(store, warning)`
- `build_metadata_store()` trả `(store, warning)`
- `api/main.py` unpack warnings này vào `degraded_reasons` cho `/health`

## Nguyên tắc cứng

- Chỉ 2 luồng qua ranh giới: S3 scanner vào, API ra.
- Pipeline chỉ biết `IngestJob`, `ChunkResult`, `AIProvider`, `VectorStore`, `MetadataStore`.
- Không đặt SDK-specific code vào `pipeline/`.
- Mọi thay đổi runtime đi qua env vars trước khi sửa core flow.
- `ARCHITECTURE.md` và file này phải được cập nhật mỗi khi thay đổi contract API, data model hoặc database schema.

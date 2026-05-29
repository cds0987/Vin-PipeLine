# Architecture — DE Vector Search Engine

## System diagram

```text
┌──────────────────────────────────────┐
│              BOUNDARY VÀO            │
│                                      │
│  S3 bucket                           │
│  └─> S3 scanner (poll)               │
│       └─> IngestJob                  │
└──────────────────┬───────────────────┘
                   │
                   ▼
       parse → clean → chunk → embed → index
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
     Vector store       Metadata store
   (Qdrant / memory)  (Postgres / file / memory)
                   │
┌──────────────────┘
│              BOUNDARY RA             │
│                                      │
│  REST API                            │
│  POST /search → embed query          │
│               → vector search        │
│               → kết quả về caller    │
└──────────────────────────────────────┘
```

## Phạm vi

Service làm đúng 2 việc:

1. **Ingestion**: S3 scanner phát hiện file → pipeline 5 bước xử lý → lưu vào stores
2. **Retrieval**: caller gọi `/search` → embed query → vector search → trả kết quả

Không có API nhận tài liệu từ caller. Không có event bus. Nguồn tài liệu duy nhất là S3.

## Lớp kiến trúc và vai trò

### Pipeline core — `pipeline/`

Chỉ biết 5 interface:

```
IngestJob | ChunkResult | AIProvider | VectorStore | MetadataStore
```

Không biết: SDK cụ thể của OpenAI/Qdrant/Postgres, chi tiết HTTP API, chi tiết adapter.

Invariant: nếu một thay đổi khiến `pipeline/` phải import boto3, psycopg2, hay httpx → thiết kế sai chỗ.

### Adapter layer — `adapters/`

Adapter hấp thụ thay đổi ở rìa hệ thống. Production adapter duy nhất:

- `S3Scanner` (`adapters/s3_adapter.py`): S3 object listing → `IngestJob[]`

`FileAdapter` là dev/test tool — không phải luồng production.

Khi upstream đổi nguồn input, sửa adapter trước, không sửa pipeline.

### Store layer — `utils/stores.py`

Tách "lưu gì" khỏi "lưu ở đâu":

| Interface | Production | Fallback | Dev |
|---|---|---|---|
| `VectorStore` | `QdrantStore` | `InMemoryVectorStore` | `InMemoryVectorStore` |
| `MetadataStore` | `SQLMetadataStore` | `FileMetadataStore` | `InMemoryMetadataStore` |

Qdrant collection mặc định: `documents`. `doc_id` indexed dưới payload để xóa theo tài liệu.

Ba bảng PostgreSQL: `documents`, `document_chunks`, `ingestion_jobs`.

### Serving layer — `api/`

FastAPI app. Các endpoint:

| Endpoint | Vai trò |
|---|---|
| `POST /search` | **Luồng ra** — embed query, vector search, trả kết quả |
| `POST /scan` | Operational — trigger thủ công S3 scanner (cùng logic tự động) |
| `GET /status/{doc_id}` | Operational — trạng thái ingest |
| `GET /health` | Operational — tình trạng stores và provider |

`/scan` không phải luồng vào thứ hai — nó chỉ trigger scanner theo yêu cầu.

## Core contracts

### `IngestJob`

```python
class IngestJob(BaseModel):
    doc_id: str                          # MD5 hash của S3 URI
    file_uri: str                        # s3://bucket/key
    language: str = "vi"                 # detect từ content bởi pipeline/run.py
    document_type: str = "general"       # first path segment sau SCAN_PREFIX
    s3_last_modified: datetime | None = None
    file_name: str | None = None         # typed field từ scanner
    metadata: dict = {}                  # extension point cho adapter-specific data
```

### `ChunkResult`

```python
class ChunkResult(BaseModel):
    chunk_id: str        # {doc_id}_chunk_{index:04d}
    doc_id: str
    content: str
    embedding: list[float]
    page_start: int | None = None
    page_end: int | None = None
    section: str | None = None
    metadata: dict = {}  # {"s3_uri": "...", "embedding_model": "..."}
```

## Bốn bất biến kiến trúc

### 1. Một entry point ingest chuẩn

`pipeline.run(job, ...)` là đường duy nhất. Scanner tạo `IngestJob`, orchestrator gọi pipeline — không có shortcut khác.

Orchestrator chịu IO file. Parse stage chỉ nhận bytes đã được đọc sẵn.

### 2. Runtime đổi qua env vars

Đổi AI endpoint, model, Qdrant host, metadata store mode → config trước khi sửa code.

### 3. Testable mà không cần full infra

Mọi flow chính phải test được với `MockAIProvider` + `InMemoryVectorStore` + `InMemoryMetadataStore`. Nếu một thay đổi buộc test phụ thuộc vào real infra → dấu hiệu thiết kế sai.

### 4. Fallback phải nhìn thấy được

Fallback hữu ích cho dev/test nhưng không được im lặng. `/health` phải báo `degraded` với `degraded_reasons` cụ thể. Build warnings phải được giữ lại.

Builder contracts hiện tại:

- `build_ai_provider() -> tuple[AIProvider, str | None]`
- `build_vector_store() -> tuple[VectorStore, str | None]`
- `build_metadata_store() -> tuple[MetadataStore, str | None]`

## Hướng dẫn khi thêm tính năng mới

### Thêm định dạng file

Sửa `pipeline/01_parse.py`. Thêm suffix vào `_SUPPORTED_SUFFIXES` trong `adapters/s3_adapter.py`. Test tương ứng trong `tests/pipeline/`.

### Thêm vector store mới

Implement `VectorStore` protocol, nối vào `build_vector_store()` trong `utils/stores.py`.

### Thêm metadata backend mới

Implement `MetadataStore` protocol, nối vào `build_metadata_store()` trong `utils/stores.py`.

### Thêm nguồn tài liệu mới (ngoài S3)

Đây là thay đổi kiến trúc, không phải feature thông thường:

1. Cập nhật `ARCHITECTURE.md` và `PIPELINE.md` trước — thiết kế trên docs
2. Map nguồn mới về `IngestJob`
3. Gọi `pipeline.run()`
4. Đảm bảo không vi phạm nguyên tắc "chỉ 2 luồng qua ranh giới"

## Checklist review thiết kế

Trước khi merge thay đổi lớn:

1. Thay đổi có phá vỡ `IngestJob` hoặc `ChunkResult` không?
2. Có vi phạm nguyên tắc "chỉ 2 luồng" không?
3. `pipeline/` có đang biết quá nhiều về infra không?
4. Local test có còn chạy được với mock/in-memory không?
5. `degraded`/fallback behavior có phản ánh qua `/health` không?
6. `PIPELINE.md` đã cập nhật chưa?

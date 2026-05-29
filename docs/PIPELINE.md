# Vin-PipeLine — Tài liệu Kiến trúc & Pipeline

## Tổng quan

Vin-PipeLine là hệ thống **Document Ingestion & Vector Search** được xây dựng theo mô hình RAG (Retrieval-Augmented Generation). Hệ thống nhận tài liệu từ nhiều nguồn, xử lý qua pipeline 5 bước, lưu vector vào Qdrant và metadata vào PostgreSQL, sau đó phục vụ tìm kiếm ngữ nghĩa qua REST API.

---

## Kiến trúc hệ thống

```
┌─────────────────────────────────────────────────────────────────┐
│                        INGESTION SOURCES                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  Kafka Topic │  │  S3 Scanner  │  │  REST API /scan      │  │
│  │  DocumentUp- │  │  (background │  │  (manual trigger)    │  │
│  │  loaded      │  │   polling)   │  │                      │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
└─────────┼─────────────────┼───────────────────────┼─────────────┘
          │                 │                       │
          └─────────────────┴───────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────┐
│                     INGESTION PIPELINE (run.py)                   │
│                                                                   │
│  01_parse ──► 02_clean ──► 03_chunk ──► 04_embed ──► 05_index    │
│                                                                   │
└──────────────────────────────┬────────────────────────────────────┘
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
      ┌─────────────────┐            ┌──────────────────┐
      │  Qdrant          │            │  PostgreSQL       │
      │  (Vector Store)  │            │  (Metadata Store) │
      └────────┬────────┘            └────────┬─────────┘
               └───────────────┬──────────────┘
                               ▼
                   ┌───────────────────────┐
                   │  REST API /search     │
                   │  (RetrievalService)   │
                   └───────────────────────┘
```

---

## Pipeline Ingestion — 5 Bước

### Bước 1 · Parse (`pipeline/01_parse.py`)

Đọc file từ URI (local hoặc S3) và trích xuất text thô thành danh sách `(page_number, text)`.

| Định dạng | Thư viện | Ghi chú |
|-----------|----------|---------|
| `.pdf` | `pypdf` + `fitz` (PyMuPDF) | Text-layer trước; fallback OCR qua vision model nếu trang trống |
| `.docx` | `python-docx` | Ghép tất cả paragraph |
| `.txt`, `.md` | built-in | UTF-8 decode |
| `.html`, `.htm` | `html.parser` | Strip tags, giữ text nodes |
| `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tiff` | AIProvider.ocr() | Gọi vision model (GPT-4o mặc định) |

**Input:** `IngestJob` (doc_id, file_uri, language, document_type)
**Output:** `list[tuple[int, str]]` — danh sách (page_num, text)

**OCR fallback chain cho PDF:**
1. `pypdf` extract text
2. Nếu trang trống → render page thành PNG bằng PyMuPDF → gửi lên vision model
3. Nếu PyMuPDF không có → OCR từng ảnh nhúng trong trang

---

### Bước 2 · Clean (`pipeline/02_clean.py`)

Chuẩn hóa text, loại bỏ nhiễu whitespace.

Các phép biến đổi (theo thứ tự):
1. `\r\n` và `\r` → `\n`
2. Nhiều space/tab liên tiếp → 1 space
3. Hơn 2 dòng trống liên tiếp → 1 dòng trống
4. `.strip()` toàn bộ
5. Drop trang nếu sau khi clean text rỗng

**Input:** `list[tuple[int, str]]`
**Output:** `list[tuple[int, str]]` — đã lọc trang rỗng

---

### Bước 3 · Chunk (`pipeline/03_chunk.py`)

Chia text thành các đoạn nhỏ (chunk) theo cửa sổ trượt (sliding window) ở mức **BPE token**.

**Cấu hình:**

| Tham số | Biến env | Mặc định |
|---------|----------|----------|
| Kích thước chunk | `CHUNK_SIZE` | 512 token |
| Overlap giữa các chunk | `CHUNK_OVERLAP` | 64 token |

**Thuật toán:**
- Tokenizer: `tiktoken` với model `text-embedding-3-small` (fallback về word-split nếu thiếu thư viện)
- Build token→page map để biết mỗi chunk thuộc trang nào
- Mỗi chunk bước `step = chunk_size - overlap` token
- Gán `page_start` / `page_end` từ token map

**Chunk ID format:** `{doc_id}_chunk_{index:04d}`

**Metadata mỗi chunk:**
```json
{
  "chunk_index": 0,
  "chunk_strategy": "sliding_window",
  "language": "vi",
  "document_type": "general",
  "token_start": 0,
  "token_end": 512
}
```

**Input:** `list[tuple[int, str]]`, `IngestJob`
**Output:** `list[ChunkResult]`

---

### Bước 4 · Embed (`pipeline/04_embed.py`)

Gọi embedding API để vector hóa nội dung từng chunk.

- Xử lý theo batch (mặc định `batch_size=32`) để tránh quá tải API
- Ghi `chunk.embedding: list[float]` và `metadata["embedding_model"]`

**Model mặc định:** `text-embedding-3-small` (OpenAI, dim=1536)

**Input:** `list[ChunkResult]`
**Output:** `list[ChunkResult]` — đã có `embedding` field

---

### Bước 5 · Index (`pipeline/05_index.py`)

Ghi dữ liệu vào hai store và cập nhật trạng thái job.

**Quy trình:**
1. `vector_store.delete(doc_id)` — xóa vector cũ (đảm bảo idempotent)
2. `metadata_store.update_status(doc_id, "indexing")`
3. Upsert `DocumentRecord` vào PostgreSQL (`documents` table)
4. Stamp `s3_uri` vào metadata mỗi chunk
5. `vector_store.upsert(chunks)` → Qdrant
6. `metadata_store.upsert_chunks(chunks)` → PostgreSQL (`document_chunks` table)
7. `metadata_store.update_status(doc_id, "indexed")`
8. `metadata_store.record_job(...)` → PostgreSQL (`ingestion_jobs` table)

**Output:**
```json
{
  "doc_id": "abc123",
  "status": "indexed",
  "chunk_count": 42,
  "embedding_model": "text-embedding-3-small",
  "duration_seconds": 3.14
}
```

---

### Orchestrator (`pipeline/run.py`)

Điều phối toàn bộ pipeline, với:

- **Deadline guard:** kiểm tra `time.perf_counter()` trước mỗi bước; ném `TimeoutError` nếu vượt `SCAN_JOB_TIMEOUT_SECONDS`
- **Error handling:** mọi exception đều được catch, ghi `status="failed"` vào metadata store, rethrow
- **Guard rỗng:** nếu chunk list rỗng sau bước 3 → raise `ValueError` (PDF scan không có OCR)
- **Lazy init:** `ai_provider`, `vector_store`, `metadata_store` được build tự động nếu không inject

---

## Nguồn dữ liệu đầu vào

### Kafka Consumer (`streaming/kafka_consumer.py`)

Lắng nghe topic `DocumentUploaded`, xử lý từng event:

```
Event JSON → KafkaAdapter.map() → IngestJob → pipeline.run()
```

- **Retry:** tối đa `CONSUMER_MAX_RETRIES` lần (mặc định 3), sleep tăng dần giữa các lần
- **DLQ:** sau khi hết retry → gửi event lỗi tới topic `DocumentUploaded.DLQ` + ghi file JSON vào `data/dlq/`
- **Commit:** offset chỉ commit sau khi xử lý thành công

**Kafka Topics:**

| Topic | Mục đích |
|-------|---------|
| `DocumentUploaded` | Event tài liệu mới được upload |
| `EmbeddingDone` | Thông báo indexing thành công |
| `IndexingFailed` | Thông báo indexing thất bại |
| `DocumentUploaded.DLQ` | Dead Letter Queue |
| `PermissionUpdated` | Cập nhật quyền truy cập |

---

### S3 Scanner (`adapters/s3_adapter.py`)

Quét S3 bucket theo lịch hoặc theo yêu cầu để phát hiện file mới/thay đổi.

**Logic phân loại:**

| Trạng thái file | Hành động |
|-----------------|----------|
| Chưa có trong DB | Tạo job mới |
| Status = `indexing` | Skip (đang xử lý) |
| Status = `failed` hoặc `pending` | Retry |
| `s3_last_modified` mới hơn DB | Re-ingest |
| Đã indexed, không thay đổi | Skip |

- **doc_id** = `MD5(s3_uri)` — stable theo path, không phụ thuộc nội dung
- Định dạng được hỗ trợ: `.pdf`, `.docx`, `.txt`, `.md`, `.html`, `.htm`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tiff`

---

## REST API (`api/main.py`)

FastAPI application, khởi động với `lifespan` context.

### Endpoints

#### `POST /search`
Tìm kiếm ngữ nghĩa.

```json
// Request
{ "query": "quy trình phê duyệt hợp đồng", "top_k": 5 }

// Response
{
  "request_id": "uuid",
  "results": [
    {
      "chunk_id": "abc_chunk_0001",
      "content": "...",
      "score": 0.87,
      "s3_uri": "s3://bucket/path/file.pdf",
      "page_start": 3,
      "page_end": 3,
      "doc_id": "abc123"
    }
  ]
}
```

Score threshold: `SEARCH_SCORE_THRESHOLD` (mặc định 0.5, set 0.0 để tắt filter).

#### `POST /scan`
Trigger quét S3 thủ công (chạy background).

```json
// Request
{ "bucket": "my-bucket", "prefix": "raw/" }

// Response
{ "status": "scan started", "queued": 12 }
```

Trả `409` nếu đang có scan cycle chạy.

#### `GET /status/{doc_id}`
Kiểm tra trạng thái xử lý của một tài liệu.

```json
{
  "doc_id": "abc123",
  "status": "indexed",
  "file_path": "s3://bucket/file.pdf",
  "file_type": "pdf",
  "total_chunks": 42,
  "uploaded_at": "2026-05-29T10:00:00Z",
  "processed_at": "2026-05-29T10:00:05Z"
}
```

Trạng thái: `pending` → `indexing` → `indexed` | `failed`

#### `GET /health`
Health check.

```json
{
  "status": "ok",
  "vector_store": "qdrant",
  "ai_provider": "OpenAIProvider",
  "scanner": "enabled"
}
```

---

## Retrieval Service (`retrieval/service.py`)

```
query string
    │
    ▼
AIProvider.embed([query])  →  query_vector: list[float]
    │
    ▼
VectorStore.search(query_vector, top_k)
    │
    ▼
Filter by score >= SEARCH_SCORE_THRESHOLD
    │
    ▼
list[dict]  →  API response
```

---

## Data Stores

### Vector Store — Qdrant

| Item | Giá trị |
|------|---------|
| Collection | `QDRANT_COLLECTION` (mặc định `documents`) |
| Distance | Cosine similarity |
| Embedding dim | 1536 (text-embedding-3-small) |
| Point ID | `UUID5(NAMESPACE_DNS, chunk_id)` |
| Payload index | `doc_id` (keyword) — dùng để delete theo doc |

**Fallback:** Nếu Qdrant không kết nối được → `InMemoryVectorStore` (cosine similarity thuần Python, không persistent).

### Metadata Store — PostgreSQL

Ba bảng chính:

**`documents`** — trạng thái và metadata của mỗi tài liệu:
```
id (PK) | file_path | file_name | file_type | document_type | language
status | total_chunks | s3_last_modified | uploaded_at | processed_at | updated_at
```

**`document_chunks`** — bản ghi mỗi chunk (không lưu embedding):
```
chunk_id (PK) | doc_id | chunk_index | content | page_start | page_end | section | token_count | created_at
```

**`ingestion_jobs`** — lịch sử mỗi lần chạy pipeline:
```
id (PK) | doc_id | status | chunk_count | embedding_model | duration_seconds | error_message | started_at | finished_at
```

**Fallback chain:** `SQLMetadataStore` → `FileMetadataStore` (JSON file) → `InMemoryMetadataStore`

Schema migration quản lý bằng **Alembic** (`migrations/`).

---

## AI Provider (`utils/ai_provider.py`)

| Provider | Kích hoạt | Khả năng |
|----------|-----------|---------|
| `OpenAIProvider` | `AI_PROVIDER=openai` hoặc `auto` + có API key | embed + OCR (vision) |
| `MockAIProvider` | `AI_PROVIDER=mock` hoặc `auto` + không có API key | SHA-256 deterministic embedding, OCR trả placeholder |

**Auto-select logic:**
- Có `AI_API_KEY` → `OpenAIProvider`
- Không có key → `MockAIProvider` (phù hợp dev/test)

---

## Cấu hình (`config/settings.py`)

Tất cả cấu hình đọc từ file `.env` qua `pydantic-settings`.

### AI

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `AI_PROVIDER` | `auto` | `auto` / `openai` / `mock` |
| `AI_API_KEY` | — | API key OpenAI hoặc compatible |
| `AI_BASE_URL` | OpenAI official | Base URL cho OpenAI-compatible API |
| `EMBED_MODEL` | `text-embedding-3-small` | Model embedding |
| `VISION_MODEL` | `gpt-4o` | Model OCR/vision |
| `EMBEDDING_DIM` | `1536` | Số chiều vector |
| `AI_REQUEST_TIMEOUT_SECONDS` | `60.0` | Timeout gọi AI API |

### Chunking

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `CHUNK_SIZE` | `512` | Số token mỗi chunk |
| `CHUNK_OVERLAP` | `64` | Số token overlap giữa 2 chunk liên tiếp |

### Vector Store

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `VECTOR_STORE` | `qdrant` | `qdrant` / `memory` |
| `QDRANT_HOST` | `qdrant` | Host Qdrant |
| `QDRANT_PORT` | `6333` | Port Qdrant |
| `QDRANT_URL` | — | Full URL (ưu tiên hơn host+port) |
| `QDRANT_COLLECTION` | `documents` | Tên collection |

### Metadata Store

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `METADATA_STORE` | `postgres` | `postgres` / `file` / `memory` |
| `DATABASE_URL` | `postgresql://rag:rag@postgres:5432/ragdb` | PostgreSQL connection string |

### S3

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `USE_S3` | `false` | Bật S3 mode |
| `S3_BUCKET` | `rag-pipeline-local` | Bucket mặc định |
| `S3_ENDPOINT` | `http://minio:9000` | Endpoint (MinIO hoặc AWS) |
| `AWS_ACCESS_KEY_ID` | — | Access key |
| `AWS_SECRET_ACCESS_KEY` | — | Secret key |
| `SCAN_INTERVAL_SECONDS` | `300` | Chu kỳ S3 scan (0 = tắt) |
| `SCAN_PREFIX` | `` | Key prefix để quét |
| `SCAN_MAX_WORKERS` | `4` | Số worker song song khi scan |
| `SCAN_JOB_TIMEOUT_SECONDS` | `900` | Timeout mỗi job (0 = tắt) |

### Kafka

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `KAFKA_BOOTSTRAP` | `kafka:9092` | Bootstrap servers |
| `TOPIC_INGEST` | `DocumentUploaded` | Topic nhận event |
| `TOPIC_DONE` | `EmbeddingDone` | Topic thông báo xong |
| `TOPIC_FAILED` | `IndexingFailed` | Topic thông báo lỗi |
| `TOPIC_DLQ` | `DocumentUploaded.DLQ` | Dead Letter Queue |
| `CONSUMER_GROUP_ID` | `de-ingestion-service` | Consumer group |
| `CONSUMER_MAX_RETRIES` | `3` | Số lần retry trước khi vào DLQ |

### Retrieval

| Biến | Mặc định | Mô tả |
|------|----------|-------|
| `SEARCH_SCORE_THRESHOLD` | `0.5` | Ngưỡng cosine similarity tối thiểu (0.0 = tắt) |

---

## Cấu trúc thư mục

```
Vin-PipeLine/
├── pipeline/
│   ├── 01_parse.py       # Bước 1: Trích xuất text từ file
│   ├── 02_clean.py       # Bước 2: Chuẩn hóa text
│   ├── 03_chunk.py       # Bước 3: Chia chunk theo BPE token
│   ├── 04_embed.py       # Bước 4: Vector hóa
│   ├── 05_index.py       # Bước 5: Ghi vào store
│   └── run.py            # Orchestrator
├── api/
│   └── main.py           # FastAPI app (search, scan, status, health)
├── retrieval/
│   └── service.py        # RetrievalService (embed query → vector search)
├── streaming/
│   └── kafka_consumer.py # Kafka consumer loop
├── adapters/
│   ├── s3_adapter.py     # S3Scanner (phát hiện file mới/thay đổi)
│   ├── kafka_adapter.py  # Map Kafka event → IngestJob
│   └── file_adapter.py   # Local file adapter
├── models/
│   └── ingest_job.py     # IngestJob, ChunkResult, DocumentRecord
├── utils/
│   ├── ai_provider.py    # OpenAIProvider, MockAIProvider
│   ├── stores.py         # VectorStore, MetadataStore + implementations
│   ├── storage.py        # read_binary, write_dlq_file
│   ├── notifier.py       # Gửi event ra Kafka
│   ├── validator.py      # Validation helpers
│   └── mapper.py         # Mapping utilities
├── db/
│   └── schema.py         # SQLAlchemy table definitions (source of truth)
├── config/
│   └── settings.py       # Pydantic settings (đọc .env)
├── migrations/           # Alembic migrations
│   ├── env.py
│   └── versions/
├── dags/
│   └── pipeline_dag.py   # Airflow DAG (nếu dùng)
└── tests/                # Unit & integration tests
```

---

## Flow dữ liệu hoàn chỉnh

```
File (PDF/DOCX/TXT/HTML/Image)
        │
        │ S3 URI hoặc local path
        ▼
┌───────────────┐
│ 01_parse.py   │  pypdf / docx / html.parser / OCR (vision model)
│               │──► list[(page_num, raw_text)]
└───────────────┘
        │
        ▼
┌───────────────┐
│ 02_clean.py   │  normalize whitespace, drop empty pages
│               │──► list[(page_num, clean_text)]
└───────────────┘
        │
        ▼
┌───────────────┐
│ 03_chunk.py   │  tiktoken BPE, sliding window 512/64
│               │──► list[ChunkResult(chunk_id, content, page_start, page_end)]
└───────────────┘
        │
        ▼
┌───────────────┐
│ 04_embed.py   │  OpenAI text-embedding-3-small, batch=32
│               │──► list[ChunkResult(+ embedding: list[float])]
└───────────────┘
        │
        ▼
┌───────────────┐
│ 05_index.py   │  upsert Qdrant + PostgreSQL
│               │──► { doc_id, status, chunk_count, duration_seconds }
└───────────────┘
        │
        ▼
   ┌─────────┐      ┌─────────────┐
   │ Qdrant  │      │  PostgreSQL │
   │ vectors │      │  metadata   │
   └────┬────┘      └──────┬──────┘
        └──────┬───────────┘
               ▼
    POST /search  →  RetrievalService
        │
        ▼
    Embed query → cosine search → filter by threshold → JSON response
```

---

## Xử lý lỗi & Idempotency

- **Idempotent re-ingest:** `05_index` xóa vector cũ trước khi upsert mới → chạy lại cùng `doc_id` luôn an toàn
- **S3 re-ingest:** phát hiện qua `s3_last_modified` mới hơn giá trị đã lưu trong DB
- **Timeout per job:** `SCAN_JOB_TIMEOUT_SECONDS` kiểm tra ở đầu mỗi bước pipeline
- **Kafka DLQ:** sau `CONSUMER_MAX_RETRIES` lần thất bại → lưu vào `DocumentUploaded.DLQ` + file JSON tại `data/dlq/`
- **Store fallback:** Qdrant → InMemory; PostgreSQL → FileStore → InMemory
- **Scan concurrency guard:** `threading.Lock` đảm bảo không có 2 scan cycle chạy đồng thời

# Onboarding — DE Ingestion Service

> Tài liệu này giúp dev mới bắt đầu làm việc trong vòng **30 phút**, không cần đợi BE hay SA.

---

## 1. Service này làm gì?

Nhận tài liệu thô (PDF / DOCX / TXT / HTML / Image), xử lý qua pipeline 5 bước, lưu vào Qdrant + PostgreSQL, và expose REST API để retrieval có filter permission.

```
BE publish Kafka event
        ↓
DE Service (black box)
  parse → clean → chunk → embed → index
        ↓
Qdrant (vector) + PostgreSQL (metadata + permission)
        ↑
BE gọi POST /retrieve-context → nhận contexts[] đã filter
        ↓
BE build prompt → gọi LLM → trả lời user
```

---

## 2. Prerequisites

| Tool | Version | Ghi chú |
|------|---------|---------|
| Python | 3.11+ | Dùng 3.11 cho khớp CI |
| Git | bất kỳ | |
| Docker Desktop | bất kỳ | Chỉ cần nếu chạy full stack |
| VS Code / PyCharm | bất kỳ | |

Không cần cài Kafka, PostgreSQL, hay Qdrant locally — test chạy với in-memory store.

---

## 3. Quick Start (5 phút)

```bash
# 1. Clone
git clone https://github.com/cds0987/Vin-PipeLine.git
cd Vin-PipeLine

# 2. Tạo virtual env và cài deps
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt

# 3. Copy env file
copy .env.example .env           # Windows
# cp .env.example .env           # macOS/Linux

# 4. Chạy tests (không cần Docker, không cần API key)
pytest -q
# → 17 passed  (~7s do tiktoken load encoding lần đầu)
```

Nếu 17 tests pass — môi trường đã sẵn sàng.

---

## 4. Cấu trúc thư mục

```
Vin-PipeLine/
│
├── api/                    REST API (FastAPI)
│   └── main.py             POST /ingest, POST /retrieve-context, GET /health
│
├── pipeline/               5 bước xử lý — KHÔNG import SDK bên ngoài
│   ├── 01_parse.py         file_uri → raw text (PDF/DOCX/TXT/HTML/Image)
│   ├── 02_clean.py         text → normalized text
│   ├── 03_chunk.py         text → chunks[] tiktoken BPE sliding window
│   ├── 04_embed.py         chunks[] → embeddings qua AIProvider
│   ├── 05_index.py         chunks[] → Qdrant + PostgreSQL (documents + document_chunks + ingestion_jobs)
│   └── run.py              orchestrator — gọi tuần tự 5 bước
│
├── retrieval/
│   └── service.py          vector search + permission filter
│
├── adapters/               Input adapters — lớp duy nhất thay đổi khi input đổi
│   ├── file_adapter.py     file local → IngestJob (test không cần Kafka)
│   └── kafka_adapter.py    Kafka event → IngestJob
│
├── streaming/
│   └── kafka_consumer.py   Consume DocumentUploaded → retry 3x → DLQ
│
├── models/
│   ├── ingest_job.py       IngestJob, ChunkResult, PermissionModel, DocumentRecord
│   └── events.py           DocumentUploaded, EmbeddingDone, IndexingFailed
│
├── utils/
│   ├── ai_provider.py      AIProvider Protocol + OpenAIProvider + MockAIProvider
│   ├── stores.py           QdrantStore, InMemoryVectorStore, SQLMetadataStore, ...
│   │                       Tables: documents, document_permissions, document_chunks, ingestion_jobs
│   ├── storage.py          read_binary() — S3 hoặc local
│   ├── notifier.py         Kafka publish helper
│   ├── validator.py        validate Kafka payload → DLQ nếu fail
│   └── mapper.py           DocumentUploaded → IngestJob
│
├── config/
│   └── settings.py         Tất cả config đọc từ env vars
│
├── tests/                  17 unit tests + 4 integration tests
├── docs/                   Tài liệu kiến trúc và design
├── docker-compose.yml      Full stack local (Qdrant + Postgres + Kafka + MinIO)
├── .env.example            Template env vars
└── .env                    Credentials thật — KHÔNG commit (đã gitignore)
```

---

## 5. Chạy local — không cần Docker

Dùng cho dev hàng ngày: tests nhanh, không cần external service.

```bash
# Unit tests (mock AI, in-memory stores)
pytest -q

# Chạy pipeline thủ công với file local
python -c "
from adapters.file_adapter import FileAdapter
from pipeline.run import run
job = FileAdapter().map('data/sample/policy.txt')
print(run(job))
"
# → {'doc_id': '...', 'status': 'indexed', 'chunk_count': 12, ...}

# Chạy API local (mock mode, không cần Qdrant thật)
AI_PROVIDER=mock VECTOR_STORE=memory METADATA_STORE=memory \
  uvicorn api.main:app --reload --port 8000
```

---

## 6. Chạy local — full stack với Docker

```bash
# Copy và điền .env (Qdrant Cloud hoặc để trống dùng local Qdrant)
cp .env.example .env

# Khởi động toàn bộ stack
docker compose up -d postgres qdrant

# Chạy API trỏ vào Qdrant local
VECTOR_STORE=qdrant QDRANT_HOST=localhost QDRANT_PORT=6333 \
  uvicorn api.main:app --reload --port 8000

# Test API
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"doc_id":"doc-1","file_uri":"data/sample/policy.txt","permission":{"visibility":"public"}}'

curl http://localhost:8000/health
```

---

## 7. Chạy với Qdrant Cloud

Điền vào `.env`:

```env
VECTOR_STORE=qdrant
QDRANT_URL=https://<cluster-id>.us-east-1-1.aws.cloud.qdrant.io
QDRANT_API_KEY=<api-key>
QDRANT_COLLECTION=documents
```

Không set `QDRANT_URL` (hoặc để trống) → tự fallback về `QDRANT_HOST:QDRANT_PORT`.

---

## 8. Tests

### Unit tests (chạy mọi lúc, không cần external service)

```bash
pytest -q                    # 17 tests, ~7s (tiktoken BPE encoding)
pytest -q tests/test_api.py  # chỉ API tests
pytest -q -k "retrieval"     # chỉ tests có từ "retrieval"
```

### Integration tests (cần Qdrant Cloud)

```bash
# Set env trước
export VECTOR_STORE=qdrant
export QDRANT_URL=https://...
export QDRANT_API_KEY=...
export QDRANT_COLLECTION=ci-integration-test
export EMBEDDING_DIM=32

pytest -m integration -v     # 4 tests kết nối Qdrant Cloud thật
```

### Tổng quan test coverage hiện tại

| File | Luồng test |
|------|-----------|
| `test_api.py` | GET /health, POST /ingest, POST /retrieve-context |
| `test_parse.py` | Parse .txt, .html |
| `test_chunk.py` | Sliding window chunking |
| `test_kafka_adapter.py` | Map event hợp lệ, event lỗi → DLQ |
| `test_kafka_consumer.py` | Retry 3x, DLQ routing, transient failure recovery |
| `test_pipeline.py` | End-to-end: file → index → verify |
| `test_retrieval.py` | Permission filter: public / private / org+role+user |
| `test_qdrant_integration.py` | Upsert, search, idempotent, delete (Qdrant Cloud) |

---

## 9. Thêm tính năng mới

### Thêm loại file mới (ví dụ: `.pptx`)

Chỉ sửa 1 file — `pipeline/01_parse.py`:

```python
# Thêm vào cuối hàm run()
if suffix == ".pptx":
    return _parse_pptx(file_bytes)

# Thêm hàm parser
def _parse_pptx(file_bytes: bytes) -> str:
    from pptx import Presentation
    import io
    prs = Presentation(io.BytesIO(file_bytes))
    return "\n".join(
        shape.text for slide in prs.slides
        for shape in slide.shapes if hasattr(shape, "text")
    )
```

Thêm `python-pptx` vào `requirements.txt`. Không đổi file nào khác.

---

### Đổi AI provider (OpenAI → Ollama)

Chỉ đổi `.env`, không đổi code:

```env
AI_PROVIDER=auto
AI_BASE_URL=http://localhost:11434/v1
AI_API_KEY=ollama
EMBED_MODEL=nomic-embed-text
VISION_MODEL=llava
```

---

### Đổi Vector DB (Qdrant → Milvus)

1. Tạo class `MilvusStore` trong `utils/stores.py` implement 3 method: `upsert`, `search`, `delete`
   - Lưu ý: `upsert_chunks()` và `record_job()` thuộc `MetadataStore`, không phải `VectorStore`
2. Thêm case trong `build_vector_store()`:
   ```python
   if settings.VECTOR_STORE == "milvus":
       return MilvusStore()
   ```
3. Set `VECTOR_STORE=milvus` trong `.env`

Pipeline không đổi gì.

---

### Đổi Metadata DB (PostgreSQL → MongoDB)

Tương tự — tạo `MongoMetadataStore`, thêm case trong `build_metadata_store()`, đổi env var.

---

## 10. CI/CD

Push lên `main` tự trigger 3 jobs:

| Job | Mô tả | Fail conditions |
|-----|-------|----------------|
| `pytest` | 17 unit tests, mock AI, in-memory stores | Test fail |
| `docker-test` | Build Docker image + chạy pytest trong container | Build fail hoặc test fail |
| `qdrant-integration` | 4 integration tests với Qdrant Cloud thật | Kết nối fail, logic sai |

`qdrant-integration` chỉ chạy với push/PR từ cùng repo (secrets không available ở fork).

---

## 11. Quy tắc bắt buộc

```
✅ Pipeline chỉ nhận IngestJob, chỉ trả ChunkResult
✅ Mọi tác vụ AI đều qua AIProvider — không import openai trong pipeline/
✅ Mọi store đều qua VectorStore / MetadataStore interface
✅ Config thay đổi → chỉ đổi env vars, không đổi code
✅ DLQ cho mọi lỗi — không drop event, không raise exception thoát consumer
✅ Pipeline idempotent — gọi lại cùng doc_id không sinh chunk trùng

❌ Không import chromadb / qdrant_client / psycopg2 trong pipeline/
❌ Không hardcode URL, model name, credential trong code
❌ Không commit file .env
❌ Không để API trả chunk chưa filter permission
```

---

## 12. Troubleshooting

**`pytest` báo import error khi chạy lần đầu**
```bash
pip install -r requirements.txt   # đảm bảo đã cài đủ
```

**`QdrantStore` fail khi kết nối Cloud**
```bash
# Kiểm tra QDRANT_URL và QDRANT_API_KEY đã set chưa
python -c "from config import settings; print(settings.QDRANT_URL)"
```

**`Index required but not found for doc_id`**
— Collection cũ tạo trước khi có payload index. Xóa collection và tạo lại:
```python
from utils.stores import QdrantStore
# QdrantStore.__init__ sẽ tự tạo index khi khởi tạo
store = QdrantStore()  # collection mới có index
```

**Tests chậm hoặc hang**
— Một số test có thể cố kết nối Qdrant thật nếu `VECTOR_STORE=qdrant` trong env.
Đảm bảo chạy unit tests với:
```bash
VECTOR_STORE=memory METADATA_STORE=memory pytest -q
```
hoặc xóa `VECTOR_STORE` khỏi shell env trước khi chạy.

**`datetime.utcnow()` deprecation warning**
— Đã fix trong toàn bộ codebase. Nếu thấy trong output, warning đến từ thư viện bên thứ ba (pydantic internals), không phải từ code của service.

**Pipeline báo lỗi `Parse produced empty text`**
— File là PDF scan (ảnh, không có text layer). Parser `pypdf` trả về empty string. Cần đảm bảo `AI_PROVIDER` và `AI_API_KEY` được set để OCR fallback hoạt động, hoặc convert PDF sang ảnh rồi ingest dưới dạng `.png`/`.jpg`.

**`ingestion_jobs` table không có row sau khi chạy**
— Đang dùng `FileMetadataStore` hoặc `InMemoryMetadataStore` (test mode). Hai store này có `record_job()` là no-op. Chỉ `SQLMetadataStore` ghi vào PostgreSQL thật. Set `METADATA_STORE=postgres` và `docker compose up postgres` để test đầy đủ.

---

## 13. Liên hệ & tài liệu thêm

| Tài liệu | Nội dung |
|---------|---------|
| `docs/overview.md` | Kiến trúc chi tiết, contract API, Kafka schema, permission algorithm |
| `docs/de_onboard_design_mindset.md` | Tư duy Ports & Adapters, tại sao thiết kế vậy |
| `docs/migration.md` | Lịch sử migrate từ e-commerce pipeline, build order từng phase |
| `docs/agent_prompt.md` | Trạng thái hoàn thành từng file, cách chạy nhanh |

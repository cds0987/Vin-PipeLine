# migration.md — E-commerce Pipeline → RAG Document Pipeline

## Mục tiêu

Thay thế hoàn toàn e-commerce analytics pipeline bằng RAG document ingestion & retrieval pipeline.  
Giữ lại những gì có thể tái sử dụng, xóa những gì không còn phù hợp.

---

## So sánh 2 pipeline

| | Pipeline cũ | Pipeline mới |
|---|---|---|
| Input | `events.parquet` (rows) | PDF / DOCX / TXT (documents) |
| Trigger | S3 file landing → Airflow | Kafka `DocumentUploaded` |
| Xử lý | PySpark: clean → aggregate | Python: parse → chunk → embed |
| Output | Gold tables + Feature table | Vector DB + Metadata DB + Permission Store |
| Serving | FastAPI GET /gold/revenue | FastAPI POST /retrieve-context |
| Compute | PySpark (distributed) | Python thường — không cần Spark |
| ML | XGBoost | Embedding model (text-embedding-3-small) |

---

## Những gì GIỮ LẠI

| File / Component | Lý do giữ | Thay đổi cần làm |
|---|---|---|
| `utils/notifier.py` | Kafka publish logic giống hệt | Đổi topic names |
| `utils/storage.py` | Đọc file từ S3 | Đổi `read parquet` → `read binary` |
| `docker-compose.yml` | MinIO + Kafka + Airflow base | Thêm PostgreSQL + Qdrant |
| `docker/Dockerfile.spark` | Base Python + Java image | Bỏ PySpark, giữ Python |
| `dags/pipeline_dag.py` | Airflow DAG pattern | Đổi trigger: S3Sensor → KafkaSensor |
| `streaming/kafka_consumer.py` | Kafka consume → process | Đổi logic xử lý |
| `config/settings.py` | `get_path()`, S3 config | Bỏ SPARK_CONFIG, thêm DB config |

---

## Những gì XÓA

```
pipeline/01_bronze.py        ← xóa
pipeline/02_silver.py        ← xóa
pipeline/03_gold.py          ← xóa
pipeline/04_features.py      ← xóa
pipeline/05_run_all.py       ← viết lại hoàn toàn
pipeline/transforms.py       ← xóa
config/schema.py             ← xóa (thay bằng models/ingest_job.py)
utils/quality_checks.py      ← xóa (thay bằng utils/validator.py)
utils/spark_session.py       ← xóa (không còn PySpark)
streaming/producer.py        ← xóa (không còn giả lập events.parquet)
tests/test_silver.py         ← xóa
tests/test_gold.py           ← xóa
scripts/download_dataset.py  ← xóa
data/bronze/ silver/ gold/ features/  ← xóa
```

---

## Structure mới hoàn chỉnh

```
rag-pipeline/
├── config/
│   └── settings.py              # S3, Kafka, DB, embedding config
│
├── models/
│   ├── ingest_job.py            # IngestJob, PermissionModel (Pydantic)
│   └── events.py                # DocumentUploaded, EmbeddingDone, IndexingFailed
│
├── utils/
│   ├── storage.py               # read_file(s3_uri) → bytes  [TÁI SỬ DỤNG]
│   ├── notifier.py              # notify(event, payload)     [TÁI SỬ DỤNG]
│   ├── validator.py             # validate(event) → IngestJob | DLQ
│   └── mapper.py                # DocumentUploaded → IngestJob
│
├── pipeline/
│   ├── 01_parse.py              # file_uri → raw text (PDF/DOCX/TXT/HTML/Image)
│   ├── 02_clean.py              # raw text → normalized text
│   ├── 03_chunk.py              # text → chunks[] (sliding window)
│   ├── 04_embed.py              # chunks[] → vectors[]
│   ├── 05_index.py              # write VectorDB + MetadataDB + PermissionStore
│   └── run.py                   # run(job: IngestJob) → dict
│
├── retrieval/
│   └── service.py               # permission_filter() + vector_search()
│
├── api/
│   └── main.py                  # POST /retrieve-context, GET /health
│
├── dags/
│   └── pipeline_dag.py          # Kafka DocumentUploaded → pipeline.run()
│
├── streaming/
│   └── kafka_consumer.py        # consume DocumentUploaded → validate → run
│
├── tests/
│   ├── conftest.py
│   ├── test_parse.py
│   ├── test_chunk.py
│   ├── test_embed.py
│   └── test_retrieval.py
│
├── data/
│   └── sample/                  # 20 file PDF/DOCX/TXT test local
│
├── docker/
│   ├── Dockerfile.api
│   └── Dockerfile.test
│
├── docker-compose.yml           # MinIO + Kafka + Airflow + PostgreSQL + Qdrant
└── requirements.txt
```

---

## config/settings.py (mới)

```python
import os
from pathlib import Path

# S3 / MinIO
S3_BUCKET        = os.getenv("S3_BUCKET", "rag-pipeline-local")
USE_S3           = os.getenv("USE_S3", "false").lower() == "true"
_S3_BASE         = f"s3://{S3_BUCKET}"
_LOCAL_BASE      = Path(__file__).resolve().parent.parent / "data"

def get_path(layer: str) -> str:
    paths = {
        "raw":  (str(_LOCAL_BASE / "raw"), f"{_S3_BASE}/raw"),
        "dlq":  (str(_LOCAL_BASE / "dlq"), f"{_S3_BASE}/dlq"),
    }
    local, s3 = paths[layer]
    return s3 if USE_S3 else local

# Kafka
KAFKA_BOOTSTRAP  = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
TOPIC_INGEST     = "DocumentUploaded"
TOPIC_DONE       = "EmbeddingDone"
TOPIC_FAILED     = "IndexingFailed"
TOPIC_PERMISSION = "PermissionUpdated"
TOPIC_DLQ        = "DocumentUploaded.DLQ"

# Metadata DB (PostgreSQL)
DB_URL           = os.getenv("DATABASE_URL", "postgresql://rag:rag@postgres:5432/ragdb")

# Vector DB (Qdrant — local Docker hoặc Qdrant Cloud)
VECTOR_STORE     = os.getenv("VECTOR_STORE",    "qdrant")
QDRANT_HOST      = os.getenv("QDRANT_HOST",     "qdrant")
QDRANT_PORT      = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_URL       = os.getenv("QDRANT_URL")       # Cloud override
QDRANT_API_KEY   = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "documents")

# Embedding
EMBEDDING_MODEL  = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM    = 1536
CHUNK_SIZE       = 512
CHUNK_OVERLAP    = 64
```

---

## models/ingest_job.py (mới)

```python
from pydantic import BaseModel
from typing import List, Optional

class PermissionModel(BaseModel):
    visibility: str = "private"       # private | org | public
    allowed_roles: List[str] = []
    allowed_users: List[str] = []
    owner_id: Optional[str] = None
    org_id: Optional[str] = None

class IngestJob(BaseModel):
    doc_id: str
    file_uri: str                      # s3:// URI
    language: str = "vi"
    document_type: str = "general"
    permission: Optional[PermissionModel] = None
    metadata: dict = {}
```

---

## utils/validator.py + mapper.py (mới)

```python
# validator.py — Layer 1: validate Kafka payload, gửi DLQ nếu fail
from models.events import DocumentEvent
from utils.notifier import notify

def validate(raw: dict) -> DocumentEvent | None:
    try:
        return DocumentEvent(**raw)
    except Exception as e:
        notify("DocumentUploaded.DLQ", {"raw": raw, "reason": str(e)})
        return None

# mapper.py — Layer 2: DocumentEvent → IngestJob (điểm duy nhất cần sửa khi schema thay đổi)
from models.events import DocumentEvent
from models.ingest_job import IngestJob

def map_event_to_job(event: DocumentEvent) -> IngestJob:
    return IngestJob(
        doc_id=event.doc_id,
        file_uri=event.s3_uri,
        language=event.metadata.get("language", "vi"),
        document_type=event.metadata.get("document_type", "general"),
        permission=event.permission,
        metadata=event.metadata,
    )
```

---

## pipeline/ — interface mới (deep module, mỗi step expose run())

```python
# 01_parse.py
def run(job: IngestJob) -> str:
    """file_uri → raw text. Ẩn: PDF/DOCX/TXT/HTML/Image parsing, OCR fallback."""

# 02_clean.py
def run(text: str) -> str:
    """raw text → normalized text. Ẩn: CRLF normalization, collapse whitespace/newlines."""

# 03_chunk.py
def run(text: str, job: IngestJob) -> list[ChunkResult]:
    """text → chunks[]. Ẩn: sliding window (CHUNK_SIZE=512 tokens, CHUNK_OVERLAP=64), metadata per chunk."""

# 04_embed.py
def run(chunks: list[ChunkResult]) -> list[ChunkResult]:
    """chunks → chunks với embedding[]. Ẩn: AIProvider.embed(), batching."""

# 05_index.py
def run(chunks: list[ChunkResult], job: IngestJob) -> dict:
    """Ghi VectorDB + MetadataDB + PermissionStore. Trả stats."""

# run.py — orchestrate, caller chỉ cần gọi 1 hàm
def run(job: IngestJob) -> dict:
    text   = parse.run(job)
    text   = clean.run(text)
    chunks = chunk.run(text, job)
    chunks = embed.run(chunks)
    stats  = index.run(chunks, job)
    notify("EmbeddingDone", {"doc_id": job.doc_id, "chunk_count": stats["chunks"]})
    return stats
```

---

## docker-compose.yml — thêm PostgreSQL + Qdrant

```yaml
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: rag
      POSTGRES_PASSWORD: rag
      POSTGRES_DB: ragdb
    ports: ["5432:5432"]
    volumes: [postgres_data:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "rag"]
      interval: 10s
      retries: 5

  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333"]
    volumes: [qdrant_data:/qdrant/storage]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]
      interval: 10s
      retries: 5
```

---

## requirements.txt (mới)

```
# API & validation
fastapi==0.111.0
uvicorn[standard]==0.30.1
pydantic==2.7.0

# Document parsing
pypdf>=4.0.0
python-docx==1.1.0
pytesseract==0.3.10        # OCR fallback

# Embedding & Vector DB
openai==1.30.0
qdrant-client>=1.9.0

# Storage & messaging
boto3==1.34.131
kafka-python==2.0.2

# Database
sqlalchemy==2.0.30
psycopg2-binary==2.9.9
alembic==1.13.1            # DB migration

# Testing
pytest==8.2.2
pytest-asyncio==0.23.7
```

---

## Build order

> Nguyên tắc: có deliverable chạy được cuối mỗi phase. Không đợi Kafka hay BE — dùng FileAdapter từ Day 1.

```
Phase 1 — Pipeline core (tuần 1)
  Day 1:  config/settings.py + models/ (IngestJob, ChunkResult, PermissionModel, events)
  Day 2:  utils/ai_provider.py (AIProvider Protocol + OpenAIProvider — hỗ trợ base_url)
  Day 3:  utils/storage.py (adapt read binary) + utils/validator.py + utils/mapper.py
  Day 4:  pipeline/01_parse.py (PDF/DOCX/TXT) + pipeline/02_clean.py (normalize)
  Day 5:  pipeline/03_chunk.py (sliding window, CHUNK_SIZE=512 tokens, CHUNK_OVERLAP=64)
  Day 6:  pipeline/04_embed.py (dùng AIProvider — test với Ollama local, không cần cloud)
  Day 7:  docker-compose up (Qdrant + PostgreSQL) → pipeline/05_index.py
  Day 8:  pipeline/run.py + FileAdapter → test end-to-end 20 file thật
          Deliverable ✅: pipeline chạy hoàn chỉnh, Vector DB có data thật

Phase 2 — Kafka consumer (tuần 2)
  Day 9:  docker-compose thêm MinIO + Kafka
  Day 10: streaming/kafka_consumer.py (consume → validate → map → run)
  Day 11: Dead Letter Queue + retry logic (3x → DLQ topic)
  Day 12: test với mock DocumentUploaded event tự publish
          Deliverable ✅: consumer xử lý được event, DLQ hoạt động

Phase 3 — Retrieval API (tuần 3)
  Day 13: retrieval/service.py (vector search + permission filter)
  Day 14: api/main.py POST /ingest + POST /retrieve-context + GET /health
  Day 15: test permission filter đúng, đo latency < 500ms
  Day 16: Swagger doc + integration test
          Deliverable ✅: API test được bằng Postman, latency đạt ngưỡng

Phase 4 — Production ready
  Day 17: infra/terraform/ (S3 + MSK + RDS + Qdrant Cloud)
  Day 18: ✅ QdrantStore đã là vector store mặc định (local + cloud, đổi env var)
  Day 19: Dead letter replay script + monitor + alert DLQ
  Day 20: README + push GitHub
```

---

## Quy tắc cứng

```
✅ Pipeline chỉ nhận IngestJob, chỉ trả ChunkResult — contract bất biến
✅ Mọi tác vụ AI đều qua AIProvider interface — không import openai SDK trong pipeline/
✅ Mọi store đều qua VectorStore / MetadataStore interface — không import DB SDK trong pipeline/
✅ Config thay đổi AI server / model / DB → chỉ đổi env vars, không đổi code
✅ FileAdapter cho phép test pipeline từ Day 1 — không cần Kafka, không cần BE
✅ DLQ cho mọi lỗi — không drop tài liệu
✅ Pipeline idempotent — ingest lại cùng doc_id không sinh chunk trùng
✅ Retrieval Service tự filter permission trước khi trả contexts[]

❌ Không import openai / chromadb / psycopg2 trực tiếp trong pipeline/
❌ Không hardcode model name hay AI_BASE_URL trong pipeline code
❌ Không để API trả chunk rồi caller mới filter permission
❌ Không đợi BE hay SA xong mới bắt đầu — build với FileAdapter từ Day 1
```

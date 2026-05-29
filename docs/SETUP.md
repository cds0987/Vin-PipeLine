# Setup — Chạy Local & Test

## Prerequisites

- Python `3.11` — target CI
- Docker Desktop — nếu muốn chạy full stack
- Git

## Quick start (mock mode, không cần infra)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m pytest -q
```

## Chạy API mock mode

Không cần Qdrant thật, không cần Postgres:

```powershell
$env:AI_PROVIDER="mock"
$env:VECTOR_STORE="memory"
$env:METADATA_STORE="memory"
$env:USE_S3="false"
uvicorn api.main:app --reload --port 8000
```

Kiểm tra:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

## Chạy full stack local

Khởi động infrastructure:

```powershell
docker compose up -d postgres qdrant minio
```

MinIO là S3-compatible storage dùng cho local test và local scanner flow.

Chạy API với S3 scanner bật:

```powershell
$env:AI_PROVIDER="mock"
$env:VECTOR_STORE="qdrant"
$env:QDRANT_HOST="localhost"
$env:QDRANT_PORT="6333"
$env:METADATA_STORE="postgres"
$env:DATABASE_URL="postgresql://rag:rag@localhost:5432/ragdb"
$env:USE_S3="true"
$env:S3_BUCKET="rag-pipeline-local"
$env:S3_ENDPOINT="http://localhost:9000"
$env:AWS_ACCESS_KEY_ID="minioadmin"
$env:AWS_SECRET_ACCESS_KEY="minioadmin"
uvicorn api.main:app --reload --port 8000
```

## Chạy test

Tests chạy trong Docker — không cần cài Python hay dependencies local.

### Dùng tasks.ps1 (khuyến nghị)

```powershell
.\tasks.ps1 test              # full suite
.\tasks.ps1 test-pipeline     # chỉ pipeline tests
.\tasks.ps1 test-api          # chỉ API + workflow tests
.\tasks.ps1 test-adapters     # chỉ adapter tests
.\tasks.ps1 test-stores       # chỉ store tests
.\tasks.ps1 test-retrieval    # chỉ retrieval tests
.\tasks.ps1 build-test        # rebuild Docker image khi đổi requirements.txt
```

### Trực tiếp qua Docker

```powershell
docker compose build test
docker compose run --rm test                                   # full suite
docker compose run --rm test pytest tests/pipeline -q         # theo domain
```

### Qdrant integration (cần cluster thật)

```powershell
$env:AI_PROVIDER="mock"
$env:METADATA_STORE="memory"
$env:USE_S3="false"
$env:VECTOR_STORE="qdrant"
$env:QDRANT_URL="https://<cluster>.cloud.qdrant.io"
$env:QDRANT_API_KEY="<api-key>"
$env:QDRANT_COLLECTION="ci-integration-test"
$env:EMBEDDING_DIM="32"
python -m pytest -m integration -v
```

### S3 local integration với MinIO

Khởi động MinIO:

```powershell
docker compose up -d minio
```

Chạy adapter integration test từ image test:

```powershell
docker compose build test
docker run --rm --network e-commerceevents_default e-commerceevents-test:latest `
  sh -lc "pytest tests/adapters/test_s3_scanner_minio_integration.py -q -m integration"
```

Test này verify `S3Scanner` với MinIO thật:

- list object từ bucket local
- map `file_name`
- derive `document_type` từ path sau `SCAN_PREFIX`
- giữ `s3_last_modified` từ object metadata

### Smoke test qua tasks.ps1

```powershell
.\tasks.ps1 smoke     # chạy 1 file qua toàn pipeline trong Docker, không cần infra
```

## Dev smoke: chạy pipeline bằng FileAdapter

`FileAdapter` bypass S3 scanner — chỉ dùng cho dev/test, không phải production flow.

```powershell
@'
from adapters.file_adapter import FileAdapter
from pipeline.run import run
from utils.ai_provider import MockAIProvider
from utils.stores import InMemoryMetadataStore, InMemoryVectorStore

job = FileAdapter().map("data/sample/policy.txt", doc_id="dev-doc")
result = run(
    job,
    ai_provider=MockAIProvider(),
    vector_store=InMemoryVectorStore(),
    metadata_store=InMemoryMetadataStore(),
)
print(result)
'@ | python -
```

## Search qua API

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/search `
  -ContentType "application/json" `
  -Body '{"query":"policy","top_k":3}'
```

## Cấu trúc repo

```text
api/          FastAPI app — /search, /scan, /status, /health
pipeline/     5 bước ingestion (01_parse → 05_index) + orchestrator run.py
retrieval/    RetrievalService — embed query + vector search
adapters/     S3Scanner (production), FileAdapter (dev/test)
models/       IngestJob, ChunkResult, DocumentRecord
utils/        AIProvider, VectorStore, MetadataStore implementations
db/           SQLAlchemy schema — source of truth cho PostgreSQL
migrations/   Alembic migrations
tests/        Test suite theo domain
docs/         Tài liệu hệ thống
```

## Những hiểu nhầm phổ biến

- Tài liệu vào hệ thống chỉ qua S3 — không có API nhận document từ caller.
- `FileAdapter` không phải luồng vào thứ hai — nó chỉ là dev tool.
- API đúng là `POST /search`, không phải `/retrieve-context` (endpoint cũ đã bỏ).
- Schema PostgreSQL: `documents`, `document_chunks`, `ingestion_jobs` — không có `document_permissions`.

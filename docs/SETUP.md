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
python -m pytest -m qdrant -v
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
  sh -lc "pytest tests/adapters/test_s3_scanner_minio_integration.py -q -m minio"
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

## Deployment — GKE (production)

Chi tiết đầy đủ → `docs/GKE.md`. Phần dưới là tóm tắt nhanh.

Cluster: `vin-pipeline`, zone `asia-southeast1-a`, project `vintravel-chatbot`.  
API external IP: `136.110.29.1` (LoadBalancer).

### Kiểm tra trạng thái

```bash
kubectl get pods
kubectl get services
```

### Test nhanh trên production

```powershell
# Health check
Invoke-RestMethod http://136.110.29.1/health

# Search
Invoke-RestMethod -Uri "http://136.110.29.1/search" -Method POST `
  -ContentType "application/json" -Body '{"query": "test", "top_k": 5}'
```

### Xem log API

```bash
kubectl logs deployment/vin-pipeline-api --tail=100 -f
```

### Port-forward để debug nội bộ

```bash
# Qdrant REST
kubectl port-forward qdrant-0 6333:6333 &

# Postgres
kubectl port-forward postgres-0 5432:5432 &
```

### Khi có S3 credentials từ team khác

```powershell
gh secret set AWS_ACCESS_KEY_ID --body "<key>"
gh secret set AWS_SECRET_ACCESS_KEY --body "<secret>"
gh secret set S3_ENDPOINT --body "<url>"
gh secret set S3_BUCKET --body "<bucket>"
```

Sau đó đổi `USE_S3: "true"` trong `k8s/base/configmap.yaml` và push lên main — CI sẽ tự deploy.

### Khi đổi AI provider

Hiện tại GKE dùng OpenRouter. Để đổi provider hoặc key:

1. `gh secret set AI_API_KEY --body "sk-<new-key>"`
2. Sửa `k8s/base/configmap.yaml`: `AI_BASE_URL`, `EMBED_MODEL`, `VISION_MODEL` theo format provider mới
3. Nếu đổi `EMBEDDING_DIM`: collection Qdrant mới tự tạo (tên encode dimension — không cần xóa thủ công)
4. Push lên main → CI tự deploy

### CI/CD — 5 jobs

| Job | Trigger | Việc làm |
|---|---|---|
| `pytest` | mọi push | Unit tests với mock/in-memory, không cần infra |
| `docker-test` | mọi push | Full stack trong Docker Compose (Qdrant + MinIO) |
| `qdrant-integration` | push (không phải fork PR) | Tests với Qdrant Cloud thật (`-m qdrant`) |
| `minio-integration` | push (không phải fork PR) | Tests với MinIO Docker (`-m minio`) |
| `deploy` | push lên `main` sau khi `pytest` + `docker-test` pass | Build image → Artifact Registry → kubectl apply → rollout |

## Những hiểu nhầm phổ biến

- Tài liệu vào hệ thống chỉ qua S3 — không có API nhận document từ caller.
- `FileAdapter` không phải luồng vào thứ hai — nó chỉ là dev tool.
- API đúng là `POST /search`, không phải `/retrieve-context` (endpoint cũ đã bỏ).
- Schema PostgreSQL: `documents`, `document_chunks`, `ingestion_jobs` — không có `document_permissions`.

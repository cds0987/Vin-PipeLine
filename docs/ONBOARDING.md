# Onboarding — DE Vector Search Engine

Tài liệu này dành cho developer mới tham gia project. Đọc theo thứ tự từ trên xuống — mất khoảng 30 phút.

---

## 1. System này làm gì (5 phút)

Một Python service độc lập với 2 nhiệm vụ duy nhất:

**Vào:** Tự động quét S3 bucket → parse tài liệu (PDF/DOCX/HTML/TXT/image) → chunk → embed thành vector → lưu vào Qdrant + Postgres.

**Ra:** Caller gọi `POST /search` → embed query → tìm vector gần nhất → trả kết quả có score, source, page.

```
S3 bucket ──> Scanner ──> Pipeline ──> Qdrant
                                  └──> Postgres
                                          ↑
                     POST /search ────────┘
```

Không có gì khác. Không có event bus, không có API nhận document từ caller, không có authentication.

---

## 2. Trạng thái production hiện tại

| Thành phần | Trạng thái |
|---|---|
| GKE cluster | Running — `vin-pipeline`, `asia-southeast1-a` |
| API | `http://136.110.29.1` — `/health` OK |
| Qdrant | 1 replica trong GKE |
| Postgres | 1 replica trong GKE |
| S3 Scanner | Tắt (`USE_S3=false`) — chờ credentials từ team khác |
| AI Provider | Mock — embedding 32 chiều, không có semantic |

---

## 3. Setup local (15 phút)

### 3.1 Clone và cài dependencies

```powershell
git clone https://github.com/cds0987/Vin-PipeLine.git
cd Vin-PipeLine

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

### 3.2 Chạy test để verify

```powershell
pytest -q
```

Tất cả pass = môi trường OK. Test chạy với mock/in-memory, không cần infra.

### 3.3 Chạy API local

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

---

## 4. Kết nối vào GKE (10 phút)

### 4.1 Cài tools (một lần)

```powershell
# Google Cloud SDK
winget install Google.CloudSDK

# Mở terminal mới
gcloud components install gke-gcloud-auth-plugin
gcloud auth login
```

### 4.2 Kết nối cluster

```powershell
gcloud container clusters get-credentials vin-pipeline `
  --zone asia-southeast1-a `
  --project vintravel-chatbot
```

### 4.3 Verify

```powershell
kubectl get pods
```

Kết quả mong đợi:
```
postgres-0           1/1  Running
qdrant-0             1/1  Running
vin-pipeline-api-*   1/1  Running  (2 pods)
```

Sau bước này, có thể xem log production từ local bất kỳ lúc nào:

```powershell
kubectl logs -f deployment/vin-pipeline-api
```

---

## 5. Cấu trúc codebase

```
api/          FastAPI — /search, /scan, /status, /health
pipeline/     5 bước ingestion: 01_parse → 02_clean → 03_chunk → 04_embed → 05_index
              run.py — orchestrator, entry point duy nhất
retrieval/    RetrievalService — embed query + vector search
adapters/     S3Scanner (production), FileAdapter (dev/test only)
models/       IngestJob, ChunkResult, DocumentRecord
utils/        AIProvider, VectorStore, MetadataStore — implementations + builders
db/           SQLAlchemy schema — source of truth cho PostgreSQL
migrations/   Alembic migrations
k8s/          Kubernetes manifests — configmap, statefulsets, deployment
scripts/      bootstrap-cluster.sh — one-time GKE setup
tests/        Test suite theo domain
docs/         Tài liệu hệ thống
```

### Nguyên tắc quan trọng nhất

`pipeline/` chỉ được import 5 interface — không được import SDK cụ thể (boto3, psycopg2, httpx, qdrant-client) vào đây. Mọi thay đổi runtime đi qua env vars.

---

## 6. Luồng làm việc hàng ngày

### Thay đổi code

```powershell
# Sửa code
# Chạy test
pytest -q

# Commit + push → CI tự chạy
git add <files>
git commit -m "mô tả"
git push
```

CI sẽ tự động:
- Chạy pytest
- Nếu có thay đổi app code → build Docker image + deploy lên GKE
- Nếu chỉ thay đổi k8s/ → apply config + rollout restart
- Nếu chỉ thay đổi docs/tests → không deploy gì

### Xem kết quả CI

```powershell
gh run list --limit 5
gh run view <run-id>
```

### Xem log sau deploy

```powershell
kubectl logs -f deployment/vin-pipeline-api
```

### Test API production

```powershell
Invoke-RestMethod http://136.110.29.1/health

Invoke-RestMethod -Uri "http://136.110.29.1/search" `
  -Method POST -ContentType "application/json" `
  -Body '{"query": "test", "top_k": 5}'
```

---

## 7. Những thứ OFF-LIMITS

Đừng đụng vào:

| Thứ | Lý do |
|---|---|
| `streaming/kafka_consumer.py` | Dead code — Kafka đã bỏ |
| `tests/streaming/` | Dead tests |
| `POST /retrieve-context` | Endpoint cũ — dùng `POST /search` |
| Hardcode URL/key trong code | Dùng env vars |
| Import boto3/psycopg2 vào `pipeline/` | Vi phạm interface boundary |

---

## 8. Tài liệu tham khảo

| Cần biết | File |
|---|---|
| Rules đầy đủ, off-limits, Definition of Done | `docs/AGENTS.md` |
| Kiến trúc + design decisions | `docs/ARCHITECTURE.md` |
| Chi tiết pipeline, API contract, DB schema, env vars | `docs/PIPELINE.md` |
| Setup local, Docker, test commands | `docs/SETUP.md` |
| CI/CD — jobs, triggers, secrets, debug | `docs/CICD.md` |
| GKE — vận hành, log, debug production | `docs/GKE.md` |
| Production risks + hardening backlog | `docs/RISKS.md` |
| Test structure + coverage backlog | `docs/TESTS.md` |
| Code cũ không dùng làm reference | `docs/LEGACY.md` |

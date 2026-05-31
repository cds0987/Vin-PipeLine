# Operations — CI/CD, GKE, Deploy & Debug

> **Type:** reference (sống) · **Last verified:** 2026-05-31
>
> Tất cả việc vận hành production ở một chỗ: setup, CI/CD, deploy, debug, observability. Chạy local + test → [SETUP.md](./SETUP.md). Kiến trúc → [ARCHITECTURE.md](./ARCHITECTURE.md). Trạng thái dự án → [STATUS.md](./STATUS.md).

## Thông tin cluster

| Thông số | Giá trị |
|---|---|
| Project | `vintravel-chatbot` |
| Cluster | `vin-pipeline` |
| Zone | `asia-southeast1-a` |
| API External IP | `136.110.29.1` (LoadBalancer) |
| Node type | `e2-standard-2` × 3 |
| Artifact Registry | `asia-southeast1-docker.pkg.dev/vintravel-chatbot/vin-pipeline/api` |

## Trạng thái hiện tại (2026-05-31)

| Thứ | Trạng thái |
|---|---|
| API | Running, `/health` OK, 2 replicas |
| AI Provider | `OpenAIProvider` via OpenRouter — **semantic search thật** (không còn mock) |
| Qdrant | 1 replica, `EMBEDDING_DIM=1536`, collection encode dimension (`documents_1536`) |
| Postgres | Running, schema migrated (initContainer tự chạy alembic) |
| S3 Scanner | **Tắt** (`USE_S3=false`), chờ credentials từ team khác → chưa index document nào |
| Secret management | Tự động qua CI từ GitHub Secrets |

---

## Setup một lần (local → GKE)

```powershell
# 1. Google Cloud SDK + GKE auth plugin
winget install Google.CloudSDK
gcloud components install gke-gcloud-auth-plugin   # mở terminal mới trước khi chạy
gcloud auth login

# 2. Kết nối cluster
gcloud container clusters get-credentials vin-pipeline `
  --zone asia-southeast1-a --project vintravel-chatbot

# 3. GitHub CLI
winget install GitHub.cli
gh auth login

# 4. Verify
kubectl get pods
gh secret list
```

Sau bước này `kubectl` hoạt động từ local — không cần Cloud Shell.

---

## CI/CD — 5 jobs

```
git push lên main
        ├── changes            detect file thay đổi (dorny/paths-filter)
        ├── pytest             luôn chạy — unit tests mock/in-memory
        ├── docker-test        chỉ khi app/** đổi — full stack Docker (Qdrant + MinIO)
        ├── qdrant-integration tests Qdrant Cloud thật (-m qdrant)
        ├── minio-integration  tests MinIO Docker (-m minio)
        └── deploy             chỉ push main + pytest+docker-test pass + có thay đổi
                ├── Auth GCP (Workload Identity — không dùng JSON key)
                ├── Get GKE credentials
                ├── Apply k8s secret từ GitHub Secrets (tự động)
                ├── [app đổi] Build image → push Artifact Registry
                ├── kubectl apply -k k8s/overlays/production/ (kustomize)
                └── kubectl rollout status (chờ pods healthy)
```

### Trigger matrix

| File thay đổi | docker-test | deploy |
|---|---|---|
| `docs/`, `tests/`, `scripts/` | ⏭ skip | ⏭ skip |
| `k8s/**` | ⏭ skip | ✅ apply + restart |
| `api/`, `pipeline/`, `app/`, `docker/`, `requirements.txt`... | ✅ chạy | ✅ build + rollout |

**Không deploy thủ công** — mọi thay đổi đi qua CI khi push lên `main`.

---

## Quy trình hàng ngày

```powershell
# Push & theo dõi CI
git add <files>; git commit -m "mô tả"; git push
gh run list --limit 5      # CI đang chạy
gh run view <run-id>       # job nào pass/fail

# Trạng thái cluster
kubectl get pods           # mong đợi: postgres-0, qdrant-0, vin-pipeline-api-* (2 pods) đều 1/1 Running
kubectl get pods -o wide   # + IP + node
kubectl get services       # External IP
kubectl top pods           # CPU/RAM thực tế

# Log
kubectl logs -f deployment/vin-pipeline-api                          # realtime
kubectl logs deployment/vin-pipeline-api --tail=50                   # 50 dòng cuối
kubectl logs deployment/vin-pipeline-api | Select-String "ERROR"     # chỉ lỗi
kubectl logs -f qdrant-0 ; kubectl logs -f postgres-0

# Test API production
Invoke-RestMethod http://136.110.29.1/health
Invoke-RestMethod -Uri "http://136.110.29.1/search" -Method POST `
  -ContentType "application/json" -Body '{"query": "test", "top_k": 5}'
```

---

## Thay đổi config

### Env var thường (không nhạy cảm)

Sửa `k8s/base/configmap.yaml` → push → CI tự apply + rollout restart. Bảng env var đầy đủ → [PIPELINE.md](./PIPELINE.md).

### Secret (key, password, credentials)

```powershell
gh secret set <SECRET_NAME> --body "<value>"   # CI tự apply vào cluster khi deploy
```

| Secret | Trạng thái | Dùng cho |
|---|---|---|
| `DATABASE_URL` | Set | Postgres production |
| `QDRANT_API_KEY` | Set | Qdrant Cloud (CI integration test) |
| `AI_API_KEY` | **Set** — OpenRouter key | Embed + vision qua OpenRouter |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Set (chờ dùng) | S3 thật khi bật scanner |
| `S3_ENDPOINT` / `S3_BUCKET` | Set (chờ dùng) | S3 thật khi bật scanner |

Apply secret ngay không cần push:

```powershell
$env:USE_GKE_GCLOUD_AUTH_PLUGIN = "True"
$key = (Get-Content .env | Select-String "^AI_API_KEY=").Line.Split("=",2)[1].Trim()
kubectl create secret generic vin-pipeline-secret `
  --from-literal=AI_API_KEY="$key" --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/vin-pipeline-api
```

### Bật S3 khi có credentials

```powershell
gh secret set AWS_ACCESS_KEY_ID --body "<key>"
gh secret set AWS_SECRET_ACCESS_KEY --body "<secret>"
gh secret set S3_ENDPOINT --body "<url>"
gh secret set S3_BUCKET --body "<bucket>"
# Sửa k8s/base/configmap.yaml: USE_S3: "true" → push → CI tự deploy
```

### Đổi AI provider / base URL

```powershell
gh secret set AI_API_KEY --body "sk-<new-key>"
# Sửa k8s/base/configmap.yaml:
#   AI_BASE_URL: ""                          # trống = OpenAI mặc định; hoặc URL provider khác
#   EMBED_MODEL: "text-embedding-3-small"    # tên model theo format provider
#   VISION_MODEL: "gpt-4o"
#   EMBEDDING_DIM: "1536"
# Đổi EMBEDDING_DIM: collection Qdrant mới TỰ TẠO (tên encode dimension, vd documents_1536)
#   → không cần xóa thủ công trừ khi muốn dọn data cũ
git add k8s/base/configmap.yaml; git commit -m "Switch AI provider"; git push
```

---

## Debug thường gặp

| Triệu chứng | Cách xử lý |
|---|---|
| **CrashLoopBackOff** | `kubectl describe pod <p>` (xem Events) + `kubectl logs <p> --previous`. Thường: secret sai/thiếu, DB chưa sẵn sàng (tăng `initialDelaySeconds`), OOM (tăng `resources.limits.memory`) |
| **Pending** | `kubectl describe pod <p>` — thường insufficient resources |
| **ImagePullBackOff** | `kubectl describe pod <p>` — kiểm tra GKE node SA có `roles/artifactregistry.reader` |
| **Search trả 500 (dimension mismatch)** | Hiếm gặp vì collection encode dimension. Xem cách xử lý bên dưới |
| **Secret sai/thiếu** | `kubectl describe pod <p>` tìm "secret not found"; `gh secret set <NAME>`; push k8s/ change để CI apply |

Dimension mismatch:

```powershell
kubectl logs deployment/vin-pipeline-api | Select-String "dimension|mismatch"
kubectl port-forward qdrant-0 6333:6333
# Terminal khác — xóa đúng tên collection (có hậu tố dimension):
Invoke-RestMethod -Uri "http://localhost:6333/collections/documents_1536" -Method DELETE
kubectl rollout restart deployment/vin-pipeline-api
```

Deploy timeout → rollback: `kubectl rollout undo deployment/vin-pipeline-api`

---

## Deep ops

```powershell
# Port-forward
kubectl port-forward qdrant-0 6333:6333                       # → http://localhost:6333
kubectl port-forward postgres-0 5432:5432                     # → postgresql://rag:rag@localhost:5432/ragdb
kubectl port-forward deployment/vin-pipeline-api 8000:8000    # bypass LoadBalancer

# Exec vào container
kubectl exec -it deployment/vin-pipeline-api -- /bin/sh
kubectl exec -it postgres-0 -- psql -U rag -d ragdb
kubectl exec -it qdrant-0 -- wget -qO- http://localhost:6333/collections

# Rollout & scaling
kubectl rollout status deployment/vin-pipeline-api
kubectl rollout undo deployment/vin-pipeline-api
kubectl scale deployment/vin-pipeline-api --replicas=3
kubectl rollout restart deployment/vin-pipeline-api    # restart không downtime
```

### Tạo lại cluster từ đầu

```bash
chmod +x scripts/bootstrap-cluster.sh
./scripts/bootstrap-cluster.sh
```

Script tự: kết nối kubectl → grant Artifact Registry reader cho node SA → setup Workload Identity Federation cho GitHub Actions → tạo Artifact Registry repo → tạo `vin-pipeline-secret` (hỏi từng giá trị). Sau đó push bất kỳ commit lên main → CI deploy toàn bộ.

---

## Observability & Logging

Mục tiêu: truy được lineage đầy đủ của một tài liệu và một kết quả search.

`source_s3_uri → markdown_s3_uri → section_id → caption → vector → search result`

**Field log nên luôn mang theo:** `job_id`, `doc_id`, `section_id`, `request_id`, `source_s3_uri`, `markdown_s3_uri`, `parser_version`, `caption_model`, `embedding_model`.

**Event tối thiểu** — ingest: `ingest.parse.completed`, `ingest.markdown.saved`, `ingest.sections.split`, `ingest.captions.embedded`, `ingest.failed`. Search: `search.requested`, `search.completed`.

**Còn thiếu (backlog → [RISKS.md](./RISKS.md)):** structured logging đồng nhất mọi module, metrics (số section / thời gian caption / index / search latency), correlation ID xuyên suốt scanner → API, expose `BatchEmbedder.stats()` qua `/health`|`/metrics`.

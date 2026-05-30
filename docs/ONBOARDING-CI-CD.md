# Onboarding — CI/CD & GKE

---

## Setup một lần (local → GKE)

```powershell
# 1. Google Cloud SDK
winget install Google.CloudSDK

# 2. Mở terminal mới
gcloud components install gke-gcloud-auth-plugin
gcloud auth login

# 3. Kết nối cluster
gcloud container clusters get-credentials vin-pipeline `
  --zone asia-southeast1-a --project vintravel-chatbot

# 4. GitHub CLI
winget install GitHub.cli
gh auth login

# 5. Verify
kubectl get pods
gh secret list
```

---

## Luồng ingest hiện tại (sau refactor)

Pipeline đã chuyển sang clean architecture (`app/`). Luồng mới:

```
S3 bucket
    │
    ▼
Scanner → IngestJob
    │
    ▼
parse (MarkItDown + AI vision)
    │  → MarkdownDocument
    ▼
lưu markdown lên S3  (MARKDOWN_S3_PREFIX)
    │
    ▼
split sections  (HeadingSectionSplitter — tách theo heading)
    │
    ▼
caption sections  (CAPTION_MODEL: heuristic | ai)
    │
    ▼
embed sections  (AIProvider)
    │
    ▼
index  → Qdrant (vector) + Postgres (metadata)
```

Luồng ra không đổi: `POST /search` → embed query → Qdrant → trả kết quả.

### Env vars quan trọng

| Var | Ý nghĩa | Hiện tại (GKE) |
|---|---|---|
| `AI_PROVIDER` | `mock` / `auto` | `auto` |
| `AI_BASE_URL` | base URL của AI provider | `https://openrouter.ai/api/v1` |
| `EMBED_MODEL` | model dùng embed | `openai/text-embedding-3-small` |
| `VISION_MODEL` | model dùng caption ảnh | `openai/gpt-4o-mini` |
| `VECTOR_STORE` | `qdrant` / `memory` | `qdrant` |
| `METADATA_STORE` | `postgres` / `memory` | `postgres` |
| `USE_S3` | bật/tắt S3 scanner | `false` |
| `MARKDOWN_S3_PREFIX` | nơi lưu markdown sau parse | `rag-derived/markdown` |
| `CAPTION_MODEL` | cách generate caption | `heuristic` |
| `PARSER_VERSION` | version parser | `pipeline.parsers.v1` |
| `EMBEDDING_DIM` | dimension vector | `1536` |

---

## CI/CD — 5 jobs

```
git push lên main
        │
        ├── changes           detect file thay đổi (dorny/paths-filter)
        ├── pytest            luôn chạy
        ├── docker-test       chỉ khi app/** thay đổi
        ├── qdrant-integration
        ├── minio-integration
        │
        └── deploy  (chỉ push main + pytest pass + có thay đổi)
                ├── Authenticate GCP (Workload Identity — không dùng JSON key)
                ├── setup-gcloud + install gke-gcloud-auth-plugin
                ├── Get GKE credentials
                ├── Apply k8s secret từ GitHub Secrets  ← tự động, không cần tay
                ├── [app thay đổi] Build image → push Artifact Registry
                ├── kubectl apply -k k8s/overlays/production/  (kustomize)
                └── kubectl rollout status (chờ tất cả pods healthy)
```

### Trigger matrix

| File thay đổi | docker-test | deploy |
|---|---|---|
| `docs/`, `tests/`, `scripts/` | ⏭ skip | ⏭ skip |
| `k8s/**` | ⏭ skip | ✅ apply + restart |
| `api/`, `pipeline/`, `app/`, `docker/`, `requirements.txt`... | ✅ chạy | ✅ build + rollout |

---

## Quy trình làm việc hàng ngày

### Push và theo dõi CI

```powershell
git add <files>
git commit -m "mô tả"
git push

gh run list --limit 5          # xem CI đang chạy
gh run view <run-id>           # job nào pass/fail
gh workflow run CI             # trigger thủ công nếu cần
```

### Xem log production

```powershell
# API realtime
kubectl logs -f deployment/vin-pipeline-api

# Chỉ lỗi
kubectl logs deployment/vin-pipeline-api | Select-String "ERROR"

# Qdrant / Postgres
kubectl logs -f qdrant-0
kubectl logs -f postgres-0
```

### Kiểm tra cluster

```powershell
kubectl get pods
kubectl get services
kubectl top pods        # CPU/RAM thực tế
```

### Test API production

```powershell
Invoke-RestMethod http://136.110.29.1/health

Invoke-RestMethod -Uri "http://136.110.29.1/search" `
  -Method POST -ContentType "application/json" `
  -Body '{"query": "test", "top_k": 5}'
```

---

## Thay đổi config

### Env var thường (không nhạy cảm)

Sửa `k8s/base/configmap.yaml` → push → CI tự apply + rollout restart.

### Secret (key, password, credentials)

```powershell
# Cập nhật GitHub Secret
gh secret set <SECRET_NAME> --body "<value>"

# CI tự apply secret vào cluster khi deploy
# Không cần vào Cloud Shell
```

### Secrets hiện có

| Secret | Trạng thái | Dùng cho |
|---|---|---|
| `DATABASE_URL` | Set | Kết nối Postgres production |
| `QDRANT_API_KEY` | Set | Qdrant Cloud (CI integration test) |
| `AI_API_KEY` | **Set** — OpenRouter key | Embed + vision qua OpenRouter |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Set (chờ dùng) | S3 thật khi bật scanner |
| `S3_ENDPOINT` / `S3_BUCKET` | Set (chờ dùng) | S3 thật khi bật scanner |

### Sync AI_API_KEY từ .env local lên GitHub

```powershell
# Lấy key từ .env rồi set
$key = (Get-Content .env | Select-String "^AI_API_KEY=").Line.Split("=",2)[1].Trim()
gh secret set AI_API_KEY --body $key
```

CI tự apply secret vào cluster trong lần deploy tiếp theo. Để apply ngay không cần push:

```powershell
$env:USE_GKE_GCLOUD_AUTH_PLUGIN = "True"
kubectl create secret generic vin-pipeline-secret `
  --from-literal=AI_API_KEY="$key" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/vin-pipeline-api
```

### Bật S3 khi có credentials

```powershell
gh secret set AWS_ACCESS_KEY_ID --body "<key>"
gh secret set AWS_SECRET_ACCESS_KEY --body "<secret>"
gh secret set S3_ENDPOINT --body "<url>"
gh secret set S3_BUCKET --body "<bucket>"
# Sửa k8s/base/configmap.yaml: USE_S3: "true" → push
```

### Đổi AI provider / base URL

```powershell
# Cập nhật key nếu đổi provider
gh secret set AI_API_KEY --body "sk-<new-key>"

# Sửa k8s/base/configmap.yaml:
#   AI_BASE_URL: ""                        # trống = OpenAI; hoặc URL provider khác
#   EMBED_MODEL: "text-embedding-3-small"  # tên model theo format provider
#   VISION_MODEL: "gpt-4o"
# QUAN TRỌNG nếu đổi EMBEDDING_DIM: collection Qdrant tự tạo mới (tên encode dimension)
# Không cần xóa thủ công trừ khi muốn dọn data cũ
git add k8s/base/configmap.yaml && git commit -m "..." && git push
```

---

## Debug production

### Pod CrashLoopBackOff

```powershell
kubectl describe pod <pod-name>     # xem Events — nguyên nhân
kubectl logs <pod-name> --previous  # log trước crash
```

### Deploy timeout / rollback

```powershell
kubectl rollout undo deployment/vin-pipeline-api
kubectl get pods   # verify rollback xong
```

### Search trả 500 (dimension mismatch)

Ít xảy ra — collection name encode dimension (`documents_1536`) nên đổi `EMBEDDING_DIM` tự tạo collection mới. Nếu vẫn gặp:

```powershell
kubectl logs deployment/vin-pipeline-api | Select-String "dimension|mismatch"
kubectl port-forward qdrant-0 6333:6333
# Terminal khác — xóa đúng tên collection (có hậu tố dimension):
Invoke-RestMethod -Uri "http://localhost:6333/collections/documents_1536" -Method DELETE
kubectl rollout restart deployment/vin-pipeline-api
```

### Secret sai/thiếu

```powershell
kubectl describe pod <pod-name>   # tìm "secret not found" trong Events
gh secret set <NAME> --body "<correct-value>"
# Push bất kỳ k8s/ change để trigger CI apply secret
```

---

## Thông tin cluster

| | |
|---|---|
| Project | `vintravel-chatbot` |
| Cluster | `vin-pipeline` |
| Zone | `asia-southeast1-a` |
| API | `http://136.110.29.1` |
| Artifact Registry | `asia-southeast1-docker.pkg.dev/vintravel-chatbot/vin-pipeline/api` |

Chi tiết GKE (port-forward, exec, scale, rollout...) → `docs/GKE.md`

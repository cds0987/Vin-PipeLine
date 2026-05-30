# GKE — Vận hành & Debug

Tài liệu này mô tả quy trình làm việc hàng ngày với GKE cluster `vin-pipeline`. Để hiểu kiến trúc tổng thể → `ARCHITECTURE.md`. CI/CD flow → `SETUP.md`.

## Thông tin cluster

| Thông số | Giá trị |
|---|---|
| Project | `vintravel-chatbot` |
| Cluster | `vin-pipeline` |
| Zone | `asia-southeast1-a` |
| API External IP | `136.110.29.1` |
| Node type | `e2-standard-2` x3 |

## Prerequisites — cài một lần

```powershell
# 1. Google Cloud SDK
winget install Google.CloudSDK

# 2. Mở terminal mới, cài GKE auth plugin
gcloud components install gke-gcloud-auth-plugin

# 3. Login
gcloud auth login

# 4. Kết nối cluster
gcloud container clusters get-credentials vin-pipeline `
  --zone asia-southeast1-a `
  --project vintravel-chatbot

# 5. Verify
kubectl get pods
```

Sau bước này, `kubectl` hoạt động bình thường từ local — không cần Cloud Shell nữa.

---

## Quy trình làm việc hàng ngày

### 1. Kiểm tra trạng thái

```powershell
# Tất cả pods
kubectl get pods

# Pods + IP + node
kubectl get pods -o wide

# Services (xem External IP)
kubectl get services
```

Trạng thái mong đợi:

```
postgres-0           1/1  Running  0
qdrant-0             1/1  Running  0
vin-pipeline-api-*   1/1  Running  0  (2 pods)
```

### 2. Xem log

```powershell
# Log API realtime (follow)
kubectl logs -f deployment/vin-pipeline-api

# Log 50 dòng cuối
kubectl logs deployment/vin-pipeline-api --tail=50

# Log pod cụ thể
kubectl logs -f <pod-name>

# Chỉ lấy lỗi
kubectl logs deployment/vin-pipeline-api | Select-String "ERROR"

# Log Qdrant
kubectl logs -f qdrant-0

# Log Postgres
kubectl logs -f postgres-0
```

### 3. Test nhanh API

```powershell
# Health check
Invoke-RestMethod http://136.110.29.1/health

# Search
Invoke-RestMethod -Uri "http://136.110.29.1/search" `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"query": "test", "top_k": 5}'
```

### 4. Deploy thay đổi

**Không deploy thủ công.** Mọi thay đổi đi qua CI:

```powershell
git add .
git commit -m "mô tả thay đổi"
git push   # CI tự build → push image → kubectl apply → rollout
```

CI deploy chỉ chạy khi push lên `main` và `pytest` + `docker-test` pass.

---

## Thay đổi config thường gặp

### Bật S3 khi có credentials

```powershell
# 1. Update GitHub Secrets
gh secret set AWS_ACCESS_KEY_ID --body "<key>"
gh secret set AWS_SECRET_ACCESS_KEY --body "<secret>"
gh secret set S3_ENDPOINT --body "<url>"
gh secret set S3_BUCKET --body "<bucket>"

# 2. Sửa configmap
# k8s/configmap.yaml: USE_S3: "true"

# 3. Push → CI tự deploy
git add k8s/configmap.yaml
git commit -m "Enable S3 scanner"
git push
```

### Đổi AI provider (khi có OpenAI key)

```powershell
# 1. Update secret
gh secret set AI_API_KEY --body "sk-<real-key>"

# 2. Sửa configmap
# k8s/configmap.yaml:
#   AI_PROVIDER: "auto"
#   EMBEDDING_DIM: "1536"

# 3. Xóa Qdrant collection cũ (bắt buộc — dimension thay đổi)
kubectl port-forward qdrant-0 6333:6333
# Mở terminal khác:
Invoke-RestMethod -Uri "http://localhost:6333/collections/documents" -Method DELETE

# 4. Push
git add k8s/configmap.yaml
git commit -m "Switch to OpenAI provider"
git push
```

---

## Debug thường gặp

### Pod CrashLoopBackOff

```powershell
# Xem lý do crash
kubectl describe pod <pod-name>

# Xem log trước khi crash
kubectl logs <pod-name> --previous
```

Nguyên nhân phổ biến:
- Secret sai/thiếu → xem `kubectl describe pod` ở phần `Events`
- DB chưa sẵn sàng → tăng `initialDelaySeconds` trong readinessProbe
- OOM → tăng `resources.limits.memory`

### Pod Pending

```powershell
kubectl describe pod <pod-name>
# Xem phần Events — thường là insufficientresources
```

### ImagePullBackOff

```powershell
kubectl describe pod <pod-name>
# Kiểm tra GKE node SA có roles/artifactregistry.reader không
```

### Dimension mismatch (search trả 500)

```powershell
# Xem log để confirm lỗi
kubectl logs deployment/vin-pipeline-api | Select-String "dimension"

# Xóa collection
kubectl port-forward qdrant-0 6333:6333
Invoke-RestMethod -Uri "http://localhost:6333/collections/documents" -Method DELETE

# Rollout lại để tạo collection mới
kubectl rollout restart deployment/vin-pipeline-api
```

---

## Port-forward — truy cập service nội bộ

```powershell
# Qdrant REST API
kubectl port-forward qdrant-0 6333:6333
# → http://localhost:6333

# Postgres
kubectl port-forward postgres-0 5432:5432
# → postgresql://rag:rag@localhost:5432/ragdb

# API (bypass LoadBalancer)
kubectl port-forward deployment/vin-pipeline-api 8000:8000
# → http://localhost:8000
```

## Exec vào container

```powershell
# Shell trong API pod
kubectl exec -it deployment/vin-pipeline-api -- /bin/sh

# Chạy lệnh trong Postgres
kubectl exec -it postgres-0 -- psql -U rag -d ragdb

# Xem collections trong Qdrant (qua curl)
kubectl exec -it qdrant-0 -- wget -qO- http://localhost:6333/collections
```

---

## Rollout & scaling

```powershell
# Xem trạng thái rollout
kubectl rollout status deployment/vin-pipeline-api

# Rollback về version trước
kubectl rollout undo deployment/vin-pipeline-api

# Scale API (tăng/giảm pods)
kubectl scale deployment/vin-pipeline-api --replicas=3

# Restart tất cả API pods (không downtime)
kubectl rollout restart deployment/vin-pipeline-api
```

---

## Khi cần tạo lại cluster

Chạy script bootstrap một lần:

```bash
chmod +x scripts/bootstrap-cluster.sh
./scripts/bootstrap-cluster.sh
```

Script này tự động:
1. Kết nối kubectl vào cluster mới
2. Grant Artifact Registry reader cho GKE node SA
3. Setup Workload Identity Federation cho GitHub Actions
4. Tạo Artifact Registry repository
5. Tạo `vin-pipeline-secret` (hỏi từng giá trị)

Sau đó push bất kỳ commit nào lên main → CI tự deploy toàn bộ.

---

## Trạng thái hiện tại (2026-05-30)

| Thứ | Trạng thái |
|---|---|
| API | Running, `/health` OK |
| Qdrant | 1 replica, `EMBEDDING_DIM=32` (MockAI) |
| Postgres | Running, schema migrated |
| S3 Scanner | Tắt (`USE_S3=false`), chờ credentials từ team khác |
| AI Provider | Mock — không có semantic search thật |
| Secret management | Tự động qua CI từ GitHub Secrets |

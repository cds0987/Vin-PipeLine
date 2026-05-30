# CI/CD — Reference

Tài liệu này mô tả toàn bộ CI/CD pipeline: 5 jobs, trigger logic, secrets management, và cách debug khi có sự cố.

---

## Tổng quan

```
git push lên GitHub
        │
        ▼
   changes job        ← detect file nào thay đổi
   (dorny/paths-filter)
        │
        ├──────────────────────────────────────┐
        ▼                                      ▼
   pytest (luôn chạy)              integration jobs
   docker-test (nếu app thay đổi)  qdrant-integration
                                   minio-integration
        │
        ▼ (chỉ push lên main + pytest pass)
   deploy
        ├── Apply k8s secret từ GitHub Secrets
        ├── kubectl apply manifests
        ├── [nếu app thay đổi] Build image → push → rollout
        └── [nếu chỉ k8s thay đổi] rollout restart
```

---

## 5 Jobs

### `changes`

Chạy đầu tiên, detect file thay đổi. Trả 2 output:

| Output | `true` khi |
|---|---|
| `app` | `api/`, `pipeline/`, `retrieval/`, `adapters/`, `utils/`, `models/`, `db/`, `migrations/`, `docker/`, `requirements.txt` |
| `k8s` | `k8s/**` |

Nếu chỉ thay đổi `docs/`, `tests/`, `scripts/` → cả 2 output đều `false` → deploy skip.

---

### `pytest`

**Luôn chạy** trên mọi push và pull request.

- Môi trường: `AI_PROVIDER=mock`, `VECTOR_STORE=memory`, `METADATA_STORE=memory`
- Không cần infra — chạy hoàn toàn với mock/in-memory
- Command: `pytest -q`
- Thất bại ở đây → block deploy

---

### `docker-test`

**Chỉ chạy khi `app=true`.**

- Build và chạy full stack qua Docker Compose (Qdrant + MinIO + API)
- Command: `docker compose run --rm test`
- Test qdrant và minio markers trong môi trường Docker
- Thất bại ở đây → block deploy

---

### `qdrant-integration`

Chạy độc lập, không block deploy.

- Kết nối Qdrant Cloud thật
- Command: `pytest -m qdrant -v`
- Cần secret `QDRANT_API_KEY`
- Không chạy trên fork pull requests

---

### `minio-integration`

Chạy độc lập, không block deploy.

- Spin up MinIO Docker container
- Command: `pytest -m minio -v`
- Không cần secret
- Không chạy trên fork pull requests

---

### `deploy`

**Chỉ chạy khi:**
- Push lên `main` (không phải PR)
- `pytest` pass
- `docker-test` pass hoặc skip
- `app=true` HOẶC `k8s=true`

**Các bước:**

```
1. Authenticate GCP (Workload Identity Federation — không dùng JSON key)
2. [nếu app=true] Build Docker image → push lên Artifact Registry
3. Get GKE credentials
4. Apply k8s secret từ GitHub Secrets (idempotent)
5. kubectl apply configmap + statefulsets + deployment
6. [nếu app=true] kubectl set image + rollout status
7. [nếu chỉ k8s=true] kubectl rollout restart
```

---

## Trigger matrix

| Thay đổi | pytest | docker-test | deploy |
|---|---|---|---|
| `docs/**` only | ✅ | ⏭ skip | ⏭ skip |
| `tests/**` only | ✅ | ⏭ skip | ⏭ skip |
| `k8s/**` only | ✅ | ⏭ skip | ✅ apply + restart |
| `api/**` hoặc `pipeline/**`... | ✅ | ✅ | ✅ build + rollout |

---

## Secrets

Tất cả secrets lưu tại **GitHub → Settings → Secrets → Actions**.

| Secret | Dùng ở job | Giá trị hiện tại |
|---|---|---|
| `DATABASE_URL` | deploy | `postgresql://rag:rag@postgres:5432/ragdb` |
| `QDRANT_API_KEY` | deploy + qdrant-integration | Key của Qdrant Cloud |
| `AI_API_KEY` | deploy | `sk-placeholder` (chờ OpenAI) |
| `AWS_ACCESS_KEY_ID` | deploy | placeholder (chờ S3 team) |
| `AWS_SECRET_ACCESS_KEY` | deploy | placeholder (chờ S3 team) |
| `S3_ENDPOINT` | deploy | placeholder (chờ S3 team) |
| `S3_BUCKET` | deploy | placeholder (chờ S3 team) |

Cập nhật secret:

```powershell
gh secret set <SECRET_NAME> --body "<value>"
```

CI sẽ tự apply secret vào GKE ở bước `Apply k8s secret` của deploy job — không cần vào Cloud Shell.

---

## GCP Authentication

Deploy job dùng **Workload Identity Federation** — không có JSON key file.

```yaml
- uses: google-github-actions/auth@v2
  with:
    workload_identity_provider: projects/289299478169/locations/global/
      workloadIdentityPools/github-pool/providers/github-provider
    service_account: github-actions@vintravel-chatbot.iam.gserviceaccount.com
```

GitHub Actions tự lấy short-lived token từ Google — an toàn hơn JSON key, không cần rotate.

---

## Artifact Registry

Image được push lên:
```
asia-southeast1-docker.pkg.dev/vintravel-chatbot/vin-pipeline/api:<sha>
asia-southeast1-docker.pkg.dev/vintravel-chatbot/vin-pipeline/api:latest
```

Mỗi deploy tag bằng `github.sha` (40 char commit hash) + `latest`. Có thể rollback về SHA cụ thể.

---

## Debug CI failed

### Xem log job bị fail

```powershell
# List runs gần nhất
gh run list --limit 5

# Xem chi tiết run
gh run view <run-id>

# Xem log từng job
gh run view <run-id> --log
```

### Trigger lại deploy thủ công

```powershell
# Trigger workflow dispatch (chạy lại toàn bộ CI)
gh workflow run CI
```

### Deploy thất bại ở rollout

```powershell
# Xem trạng thái pods
kubectl get pods

# Xem log pod mới
kubectl logs <pod-name> --previous   # log trước khi crash

# Rollback về image trước
kubectl rollout undo deployment/vin-pipeline-api
```

### Secret sai/thiếu gây CrashLoopBackOff

```powershell
# Xem event của pod
kubectl describe pod <pod-name>
# Tìm dòng "Error: secret ... not found" hoặc "invalid value"

# Cập nhật secret
gh secret set <SECRET_NAME> --body "<new-value>"
# Push bất kỳ thay đổi k8s/ để trigger deploy + apply secret mới
```

---

## Thêm env var mới

### Env var không nhạy cảm (URL, config)

1. Thêm vào `k8s/configmap.yaml`
2. Thêm vào `config/settings.py`
3. Thêm vào `.env.example`
4. Cập nhật `docs/PIPELINE.md` phần Runtime config
5. Push → CI deploy

### Env var nhạy cảm (key, password, token)

1. Thêm secret vào GitHub: `gh secret set <NAME> --body "<value>"`
2. Thêm `--from-literal=<NAME>=${{ secrets.<NAME> }}` vào bước `Apply k8s secret` trong `ci.yml`
3. Thêm vào `k8s/secret.yaml` (template, không có giá trị thật)
4. Thêm vào `config/settings.py`
5. Push → CI apply secret + deploy

---

## Concurrency

```yaml
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
```

Nếu đang có CI chạy cho branch `main` và push commit mới → CI cũ bị cancel, CI mới bắt đầu. Không có 2 deploy chạy song song cho cùng branch.

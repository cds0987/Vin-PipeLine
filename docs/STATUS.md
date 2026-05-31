# STATUS — Trạng thái dự án

> **Type:** reference (sống) · **Last verified:** 2026-05-31
>
> Đây là **file duy nhất** trả lời "dự án đang ở đâu". Cập nhật file này mỗi khi trạng thái đổi — đừng tạo doc mới cho việc đang dở.
>
> - Phân tích rủi ro production đầy đủ → [RISKS.md](./RISKS.md)
> - Backlog coverage test chi tiết → [TESTS.md](./TESTS.md)
> - Plan/assessment đã đóng băng → [notes/](./notes/)

Quy ước mức: 🔴 P0 chặn merge/production · 🟠 P1 lệch design / gap quan trọng · 🟡 P2 chất lượng/coverage.

---

## 1. Đang làm dở (WIP — chưa commit)

Async refactor + BatchEmbedder đang trong working tree, **chưa commit**: 15 file sửa + `utils/batch_embedder.py` + các note trong `docs/notes/`.

| Hạng mục | Trạng thái |
|---|---|
| AI layer async (captioner song song qua `gather`+`Semaphore`) | ✅ xong, có test |
| `RunIngestJob.execute` async | ✅ xong (nhưng I/O bọc `to_thread` — xem #3) |
| BatchEmbedder (singleton + cache + `flush_and_close`) | ✅ wired trong container + lifespan |
| API/dispatcher/scanner async | ✅ xong |
| I/O layer thật sự async (aioboto3/asyncpg/AsyncQdrantClient) | ❌ chưa làm |

🔴 **P0 — commit ngay:** toàn bộ thay đổi trên đang treo, dễ mất. Commit theo nhóm: settings → batch_embedder → ai layer → application → api → tests → docs.

## 2. Deployment state (GKE production) — 2026-05-31

Vận hành chi tiết → [OPERATIONS.md](./OPERATIONS.md).

- AI: **OpenRouter thật** (`OpenAIProvider`), `EMBEDDING_DIM=1536` — semantic search thật, **không còn mock**. Collection Qdrant encode dimension (`documents_1536`); đổi dim → collection mới tự tạo (không cần xóa thủ công).
- `USE_S3=false` → scanner chưa chạy, **chưa index document nào**. Chờ S3 credentials từ team khác.
- Qdrant 1 replica, không replication → mất data nếu pod crash.

## 3. Backlog ưu tiên

### 🔴 P0
- [ ] Commit WIP async + BatchEmbedder (mục #1)
- [ ] `pytest` mặc định không xanh sạch: thiếu `boto3`/`sqlalchemy`/`PIL` gây lỗi collection + 22 error + 5 fail (core suite vẫn 432 passed). Skip có điều kiện (`importorskip`) hoặc ghi rõ dep vào `requirements.txt`/`SETUP.md`.

### 🟠 P1
- [ ] **Async "nửa vời"**: [run_ingest_job.py](../app/application/ingest/run_ingest_job.py) bọc toàn bộ I/O (read/claim/markdown/index/log) trong `asyncio.to_thread()` — đúng thứ [notes/ASYNC_REFACTOR.md](./notes/ASYNC_REFACTOR.md) nói muốn tránh. Layer I/O chưa có aioboto3/asyncpg/AsyncQdrantClient. → Chốt: hoàn tất migrate, hay cập nhật design doc chấp nhận `to_thread`-backed.
- [ ] `normalize()` chạy blocking trên event loop ([run_ingest_job.py:69](../app/application/ingest/run_ingest_job.py#L69)).
- [ ] BatchEmbedder cache không persist qua restart + `stats()` chưa hook vào `/health`|`/metrics`.
- [ ] Compatibility layer `utils.*` còn trên runtime chính ([container.py](../app/bootstrap/container.py)) — MOSA gap lớn nhất. `BatchEmbedder` cũng nên dời từ `utils/` sang `app/infrastructure/`.
- [ ] Hardening production P1 ([RISKS.md](./RISKS.md)): file size guard, retention `ingestion_jobs`, fallback trả `503` thay vì `200 degraded`, delete+upsert vector atomic.

### 🟡 P2
- [ ] `tests/api/test_health.py` chưa tồn tại; chưa có test cho async dispatcher mới (queue đầy, `409`, exception trong `create_task`). Chi tiết: [TESTS.md](./TESTS.md).
- [ ] Tách concurrency limit theo loại việc (OCR/caption/embed); execution state `retry_scheduled`/dead-letter; event-driven trigger. Chi tiết: [notes/ASYNC_PROCESSING_OPTIMIZATION.md](./notes/ASYNC_PROCESSING_OPTIMIZATION.md).
- [ ] Domain core còn phụ thuộc Pydantic (chỉ làm khi portability thành yêu cầu cứng).

---

## Bảng tra nhanh

| # | Vấn đề | Mức |
|---|---|---|
| 1 | Commit WIP async + BatchEmbedder | 🔴 |
| 2 | `pytest` cần dep optional mới xanh | 🔴 |
| 3 | Async nửa vời, lệch design doc | 🟠 |
| 4 | `normalize()` block event loop | 🟠 |
| 5 | BatchEmbedder cache không persist + chưa expose stats | 🟠 |
| 6 | `utils.*` còn trên runtime chính | 🟠 |
| 7 | Hardening production P1 | 🟠 |
| 8 | S3 chưa bật trên prod → chưa index document nào | 🟠 |
| 9 | Coverage gap (`/health`, async dispatcher) | 🟡 |
| 10 | Async architecture trung hạn | 🟡 |
| 11 | Domain phụ thuộc Pydantic | 🟡 |

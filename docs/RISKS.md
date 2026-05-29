# Risks — Production Analysis

## Tóm tắt rủi ro

| Mức độ | Vấn đề | File |
|---|---|---|
| Critical | đọc cả file vào RAM — OOM với tài liệu lớn | `utils/storage.py`, `pipeline/01_parse.py` |
| Critical | delete + upsert vector không atomic | `pipeline/05_index.py` |
| Critical | fallback store/provider thay đổi behavior nhưng service vẫn chạy | `utils/stores.py`, `utils/ai_provider.py` |
| High | OCR PDF rất đắt và chậm | `pipeline/01_parse.py` |
| High | `/search` latency dính chặt vào embedding latency | `retrieval/service.py` |
| High | scanner giữ coordination lock toàn chu kỳ scan | `api/main.py` |
| High | `ingestion_jobs` tăng không giới hạn | `db/schema.py` |
| Medium | fallback tokenizer lệch ngữ nghĩa token | `pipeline/03_chunk.py` |
| Medium | thiếu structured metrics/observability | toàn hệ thống |

## Ingestion bottlenecks

**OCR** — khi PDF không có text layer, mỗi trang phải render → OCR qua vision model. Latency cao, cost tăng nhanh, dễ chạm `SCAN_JOB_TIMEOUT_SECONDS`.

**Query embedding** — `POST /search` phải embed query trực tuyến. P95 search ≈ P95 embedding latency.

**Scanner scale** — `list_objects_v2` phải đối chiếu toàn bộ bucket với metadata store. Khi bucket/prefix lớn, đây là điểm nghẽn trước cả pipeline ingest.

## Data consistency risks

**Delete + upsert không atomic** — `05_index` xóa vector cũ rồi upsert vector mới. Crash giữa chừng: metadata đã đổi, vector mất hoặc dở dang.

**Qdrant và PostgreSQL không có transaction chung** — crash sau khi write một bên tạo trạng thái lệch. Chỉ re-ingest mới sửa được.

**Stale indexing** — `STALE_INDEXING_SECONDS` giảm nguy cơ stuck job nhưng không xử lý triệt để complex failure chain.

## Resource risks

**Memory** — load toàn bộ file bytes + render PDF page + giữ token/page map cho tài liệu lớn. Không có file size guard hiện tại.

**DB growth** — `ingestion_jobs` record mỗi lần ingest/retry/re-index. Không có retention policy → phình không giới hạn.

## Fallback risks

**AI provider fallback** — nếu `AI_PROVIDER=auto` và không có API key, service dùng `MockAIProvider`. Embedding mất semantic hoàn toàn. Nguy hiểm nếu xảy ra ngoài ý muốn trong production.

**Vector store fallback** — Qdrant unavailable → service rơi về `InMemoryVectorStore`. Dữ liệu index trong thời gian đó không bền vững.

**Metadata store fallback** — PostgreSQL unavailable → rơi sang `FileMetadataStore`. Behavior khác xa production.

Mọi fallback đều lộ qua `/health` → `degraded_reasons`. Nhưng service vẫn chạy — caller không biết kết quả đang kém chất lượng.

## API risks

**`/search`** — không có rate limiting. Kết quả thay đổi theo `SEARCH_SCORE_THRESHOLD`.

**`/scan`** — lock tránh concurrent scan là đúng cho correctness nhưng gây head-of-line blocking khi scan lớn.

**`/health`** — có `degraded` + `degraded_reasons`, nhưng chưa phải active deep probe. Không có metrics export.

## Observability gap

Hiện thiếu:

- structured JSON logs
- metrics (Prometheus/OpenTelemetry) cho ingest duration, fail rate, fallback rate
- tracing theo `doc_id`/`request_id` xuyên suốt pipeline
- dashboard

## GKE deployment risks (hiện tại)

**MockAIProvider trong production** — `AI_PROVIDER=mock`, `EMBEDDING_DIM=32`. Embedding không có semantic. Khi đổi sang OpenAI phải xóa Qdrant collection trước — nếu không, dimension mismatch gây 500.

**S3 chưa có** — `USE_S3=false`, scanner không chạy. Không có document nào được index. Chờ credentials từ team khác.

**Qdrant single replica** — chạy 1 replica thay vì 3 (thiếu node resources trên e2-standard-2). Không có replication, mất data nếu pod crash. Cần scale nodes lên e2-standard-4 và tăng replicas khi sẵn sàng production.

**Secret không được quản lý trong git** — `vin-pipeline-secret` được tạo thủ công trên cluster. Nếu cluster bị xóa hoặc secret bị xóa, phải tạo lại thủ công.

**EMBEDDING_DIM phải khớp với collection** — nếu thay đổi dimension mà không xóa collection, Qdrant trả 500. Đây là nguyên nhân của sự cố đã gặp (1536 → 32).

## Hardening backlog

**Ưu tiên 1** — blocking cho production scale:

- [ ] giới hạn file size trước khi load/parse
- [ ] retention policy cho `ingestion_jobs`
- [ ] active probes hoặc startup validation cho stores/provider
- [ ] visibility rõ hơn cho degraded/fallback mode (trả `503` thay vì `200 degraded`)

**Ưu tiên 2**:

- [ ] retry có backoff/jitter cho AI calls
- [ ] structured logging gắn `doc_id`
- [ ] metrics cho ingest success/fail, OCR usage, search latency

**Ưu tiên 3**:

- [ ] tối ưu scanner listing khi bucket lớn
- [ ] migration strategy cho embedding model dimension change
- [ ] atomicity/batch consistency cho index path

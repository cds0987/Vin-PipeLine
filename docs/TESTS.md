# Tests — Structure & Coverage Backlog

## pytest markers

| Marker | Ý nghĩa | Chạy trong CI |
|---|---|---|
| *(không có)* | Unit tests — chỉ dùng mock/in-memory | `pytest` job + `docker-test` job |
| `qdrant` | Integration với Qdrant thật (Cloud hoặc local) | `qdrant-integration` job |
| `minio` | Integration với MinIO thật | `minio-integration` job |

`addopts` trong `pytest.ini` mặc định loại trừ cả 3: `not integration and not qdrant and not minio`.

Chạy thủ công integration tests:

```bash
pytest -m qdrant -v   # cần QDRANT_URL + QDRANT_API_KEY
pytest -m minio -v    # cần MINIO_TEST_ENDPOINT
```

## Test scaffolding

### `tests/factories.py`

Factory functions để tạo domain objects với default hợp lý — không cần điền tay tất cả fields:

```python
from tests.factories import make_ingest_job, make_chunk_result, make_chunk_list, make_document_record

job   = make_ingest_job(doc_id="x", file_uri="s3://b/a.pdf")
chunk = make_chunk_result(doc_id="x", index=0, content="hello")
chunks = make_chunk_list(doc_id="x", count=5)
doc   = make_document_record(doc_id="x", status="indexed")
```

### Domain conftest files

Mỗi test domain có `conftest.py` riêng với fixtures cục bộ — không cần hiểu toàn hệ thống:

| File | Fixtures |
|---|---|
| `tests/conftest.py` | `fake_ai_provider`, `vector_store`, `metadata_store`, `api_client` |
| `tests/pipeline/conftest.py` | `txt_job`, `md_job`, `html_job`, `minimal_pages`, `multi_page_pages` |
| `tests/api/conftest.py` | `indexed_api_client` (api_client với data sẵn) |
| `tests/adapters/conftest.py` | `s3_obj()`, `run_scan()` helpers, `empty_store` |

### Chạy test cục bộ theo domain

```powershell
.\tasks.ps1 test-pipeline   # chỉ tests/pipeline/
.\tasks.ps1 test-api        # chỉ tests/api/ + tests/general/
.\tasks.ps1 test-adapters   # chỉ tests/adapters/
```

---

## Tổ chức test suite

Test suite có 2 lớp:

**`tests/general/`** — smoke workflows xuyên nhiều thành phần. Happy path end-to-end. Chỉ đặt test ở đây khi nó chạm từ 3 layer trở lên.

**Domain folders** — test behavior chi tiết từng thành phần:

| Folder | Covers |
|---|---|
| `tests/api/` | Validation, request boundaries, coordination behavior |
| `tests/adapters/` | S3 scan logic, file detection, mapping rules |
| `tests/pipeline/` | Parse, clean, chunk, embed, index, orchestration edge cases |
| `tests/retrieval/` | Search thresholding, query cache behavior |
| `tests/stores/` | In-memory stores, Qdrant integration |
| `tests/utils/` | AI provider, storage helpers, mapper utilities |

**Nguyên tắc đặt test**: nếu behavior thay đổi ở đâu → test thuộc folder domain đó. Không gom vào `general`.

**Dead code — không thêm test vào**: `tests/streaming/` (Kafka đã bị bỏ hoàn toàn).

## Coverage backlog

Mỗi mục là behavior chưa có test. Thêm vào file đã ghi — tạo file mới nếu chưa tồn tại.

### API

**`/search`** → `tests/api/test_search_validation.py`

- [ ] query dài hơn `SEARCH_QUERY_MAX_LENGTH` → reject
- [ ] query chỉ whitespace → `422`
- [ ] `top_k=1` và `top_k=50` → hợp lệ
- [ ] response luôn có `request_id`
- [ ] threshold bật/tắt → số kết quả đúng kỳ vọng
- [ ] cache query embedding → kết quả không đổi giữa các lần gọi

**`/scan`** → `tests/api/test_scan_coordination.py`

- [ ] scanner exception → surface đúng, không im lặng
- [ ] đang scan → request mới trả `409`
- [ ] không có job mới → `queued=0`
- [ ] bucket/prefix override → truyền đúng xuống scanner

**`/status/{doc_id}`** → `tests/api/test_status.py` *(tạo mới)*

- [ ] doc không tồn tại → `404`
- [ ] doc indexed → có `total_chunks` và `processed_at`
- [ ] doc failed → `status` đúng

**`/health`** → `tests/api/test_health.py` *(tạo mới)*

- [ ] bình thường → `200`, `status=ok`
- [ ] fallback → `503`, `status=degraded`
- [ ] `degraded_reasons` chứa message build warning tương ứng

### Pipeline

→ `tests/pipeline/` (file tương ứng với bước pipeline)

- [ ] parse PDF không text layer, OCR disabled → fail rõ ràng — `test_parse_ocr.py`
- [ ] parse file unsupported suffix → fail sớm — `test_parse_formats.py`
- [ ] clean → loại page rỗng đúng — `test_clean.py`
- [ ] chunk → `page_start/page_end` hợp lý — `test_chunk.py`
- [ ] embed → dimension mismatch fail — `test_embed.py`
- [ ] index → re-run cùng `doc_id` idempotent ở vector level — `test_index.py`
- [ ] deadline timeout → ghi failed job — `test_run_extended.py`
- [ ] `try_claim_ingest()` → skip khi doc đang indexing chưa stale — `test_run_extended.py`

### S3 scanner (luồng vào)

→ `tests/adapters/test_s3_scanner.py`

- [ ] file indexed, `s3_last_modified` mới hơn → requeue
- [ ] file `failed` → retry
- [ ] file `indexing` stale → retry
- [ ] file unsupported suffix → bỏ qua
- [ ] list objects lỗi → trả `[]`, log phù hợp

→ `tests/adapters/test_s3_scanner_minio_integration.py` *(marker: `minio`)*

- [x] MinIO local: object thật trong bucket → scanner tạo `IngestJob`
- [x] `file_name` map vào typed field trên `IngestJob`
- [x] `document_type` derive từ segment đầu sau `SCAN_PREFIX`

### Stores

→ `tests/stores/` *(Qdrant integration: marker `qdrant`)*

- [ ] `QdrantStore` detect dimension mismatch của collection — `test_qdrant_integration.py`
- [ ] `build_vector_store()` fallback → set warning — `test_in_memory_stores.py`
- [ ] `build_metadata_store()` fallback → set warning — `test_in_memory_stores.py`
- [ ] `FileMetadataStore` → giữ document status và job history sau nhiều lần ghi — `test_in_memory_stores.py`
- [ ] `SQLMetadataStore` → stale chunk cleanup — `test_qdrant_integration.py` hoặc file riêng

### Non-functional

→ `tests/general/`

- [ ] benchmark `/search` với cache hit và cache miss
- [ ] benchmark ingest: txt nhỏ / html vừa / pdf scan lớn
- [ ] smoke test degraded mode: Qdrant unavailable / DB unavailable

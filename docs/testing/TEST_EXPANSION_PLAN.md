# Kế Hoạch Mở Rộng Test

Mục tiêu của file này là mở rộng test coverage dựa trên các contract, luồng xử lý, và production risks đã được mô tả trong:

- [PIPELINE.md](../PIPELINE.md)
- [PRODUCTION_ANALYSIS.md](../PRODUCTION_ANALYSIS.md)
- [overview.md](../overview.md)
- [onboarding.md](../onboarding.md)
- [migration.md](../migration.md)

File này chưa implement test vào code. Đây là backlog test cases ưu tiên cao để team bổ sung dần.

## Nguyên tắc

- `tests/general/` chỉ giữ happy-path workflows căn bản.
- Các test dưới đây chủ yếu là edge cases, failure handling, contract compliance, và production-safety checks.
- Mỗi case nên được viết theo domain, không đưa trở lại top-level `tests/`.
- Ưu tiên viết unit/integration nhỏ, deterministic, ít phụ thuộc external services.

## Khoảng trống coverage hiện tại

So với docs, suite hiện tại vẫn thiếu nhiều nhóm test quan trọng:

- Giới hạn kích thước file và memory guard
- Password-protected / malformed document handling
- Atomicity và consistency giữa Qdrant, metadata, và job history
- Startup fallback và degraded-mode behavior
- Permission filtering theo contract business
- Config drift và migration safety
- API validation hardening
- Observability contracts như status, error shape, và health semantics

## Ưu tiên 1: Contract và correctness

### 1. IngestJob và event schema contracts

Folder đề xuất:
- `tests/api/`
- `tests/streaming/`
- `tests/utils/`

Cases cần bổ sung:

1. `DocumentUploaded` thiếu `doc_id` phải vào DLQ, không được pipeline xử lý.
2. `DocumentUploaded` thiếu `s3_uri` phải vào DLQ.
3. `schema_version` không hợp lệ phải bị reject rõ ràng.
4. `language` thiếu phải default về `"vi"` đúng như docs.
5. `document_type` thiếu phải default về `"general"`.
6. `permission` thiếu phải sinh permission mặc định theo owner.
7. `file_uri` local và `s3_uri` phải map thành `DocumentRecord.file_path` đúng contract.
8. `status` values chỉ được nằm trong `pending/indexing/indexed/failed`.

### 2. Pipeline stage contracts

Folder đề xuất:
- `tests/pipeline/`

Cases cần bổ sung:

1. `01_parse` phải trả về `list[tuple[int, str]]`, không phải string phẳng.
2. `02_clean` phải loại bỏ page rỗng sau khi normalize.
3. `03_chunk` phải bảo toàn `doc_id`, `chunk_index`, `page_start`, `page_end`.
4. `04_embed` phải ghi `embedding_model` vào metadata chunk.
5. `05_index` phải tạo `DocumentRecord.total_chunks` bằng số chunk index thành công.
6. `run.py` phải ghi `ingestion_jobs` cho cả success lẫn fail.
7. `run.py` parse ra empty text phải fail, không được báo indexed với `chunk_count=0`.

## Ưu tiên 1: Parse và file handling

### 3. PDF edge cases

Folder đề xuất:
- `tests/pipeline/`

Cases cần bổ sung:

1. PDF có text layer ở một số trang, scan ở một số trang:
   OCR chỉ được chạy ở trang rỗng, không OCR lại trang đã có text.
2. PDF password-protected:
   expected fail có thông điệp rõ ràng, status `failed`, không loop im lặng.
3. PDF malformed/corrupted:
   parse fail có error message debug được.
4. PDF rất nhiều trang:
   kiểm tra timeout propagation sau một số trang OCR.
5. PDF page render fail bằng PyMuPDF:
   fallback image extraction vẫn được thử, nếu có.
6. PDF không text, không render được, không image:
   expected empty parse -> fail có chủ đích.

### 4. DOCX/HTML/TXT/Image edge cases

Folder đề xuất:
- `tests/pipeline/`

Cases cần bổ sung:

1. DOCX chỉ có blank paragraphs -> parse rỗng.
2. DOCX có bảng/table text:
   cần khóa lại behavior hiện tại là bỏ qua hay lấy được một phần.
3. DOCX có embedded image:
   xác nhận hiện tại không OCR image trong docx, để tránh kỳ vọng sai.
4. HTML có script/style:
   parser không được đưa noise vào content.
5. TXT chứa ký tự control/null bytes:
   clean phải xử lý ổn định, không làm vỡ pipeline.
6. Image OCR trả string rỗng:
   phải ra parse rỗng và fail đúng flow.

### 5. File size, path, và storage safety

Folder đề xuất:
- `tests/utils/`
- `tests/api/`
- `tests/streaming/`

Cases cần bổ sung:

1. File vượt qua `MAX_FILE_SIZE_BYTES` phải bị reject trước khi read full vào RAM.
2. `file_uri` trỏ ra ngoài allowed base path phải bị reject.
3. `s3_uri` bucket khác bucket được config phải bị reject.
4. Missing local file phải mark `failed`, không crash process.
5. S3 object không đọc được phải tạo failure có context bucket/key.

## Ưu tiên 1: Indexing atomicity và consistency

### 6. Vector store và metadata store consistency

Folder đề xuất:
- `tests/stores/`
- `tests/pipeline/`

Cases cần bổ sung:

1. `vector_store.delete(doc_id)` thành công nhưng `upsert(chunks)` fail:
   cần khóa lại status cuối cùng và xác minh có xảy ra mất vector nhưng vẫn marked indexed hay không.
2. `vector_store.upsert` thành công nhưng `metadata_store.upsert_chunks` fail:
   xác minh atomicity gap hiện tại và khóa lại behavior.
3. `metadata_store.update_status(..., "indexing")` thành công, process crash trước `indexed`:
   scanner phải nhận diện stale indexing theo strategy dự kiến.
4. Re-ingest cùng `doc_id` không được tạo chunk duplicate trong SQL.
5. Re-ingest file thay đổi phải thay thế nội dung chunk cũ, không cộng dồn.
6. `record_job` fail không được làm mất indexed vectors.

### 7. Embedding dimension và model drift

Folder đề xuất:
- `tests/stores/`
- `tests/pipeline/`
- `tests/config/` nếu sau này có

Cases cần bổ sung:

1. Qdrant collection có dimension khác `EMBEDDING_DIM` phải fail ngay lúc startup hoặc init store.
2. `AIProvider.embed()` trả vector sai dimension phải bị reject trước khi upsert.
3. `EMBED_MODEL` thay đổi nhưng collection cũ vẫn còn:
   cần test mô tả failure mode hiện tại.
4. `CHUNK_SIZE` thay đổi giữa các lần index:
   metadata job/chunk nên lưu đủ thông tin để truy vết.

## Ưu tiên 1: Search và permission filtering

### 8. Retrieval contract

Folder đề xuất:
- `tests/retrieval/`
- `tests/api/`

Cases cần bổ sung:

1. `SEARCH_SCORE_THRESHOLD` lớn hơn score thì kết quả bị loại hết.
2. `SEARCH_SCORE_THRESHOLD=0.0` thì không filter.
3. `top_k` kết quả sau filter permission vẫn không vượt quá requested `top_k`.
4. Search query rỗng/space-only phải bị reject ở API layer.
5. Search query quá dài phải bị reject nếu sau này thêm max length.

### 9. Permission filtering theo docs

Folder đề xuất:
- `tests/retrieval/`
- `tests/stores/`

Cases cần bổ sung:

1. `visibility=public` -> mọi user đều thấy.
2. `owner_id` trùng user -> pass dù `visibility=private`.
3. `user_roles` giao với `allowed_roles` -> pass.
4. `allowed_users` chứa user -> pass.
5. `visibility=org` và `org_id` trùng -> pass.
6. `visibility=org` nhưng khác `org_id` -> reject.
7. Chunk top score nhưng không có permission -> bị loại, chunk thấp hơn hợp lệ được đẩy lên.
8. Nếu metadata permission bị thiếu cho doc:
   retrieval phải fail-safe theo hướng reject, không phải allow.

## Ưu tiên 2: Scanner, Kafka, và concurrency

### 10. S3 scanner coordination

Folder đề xuất:
- `tests/adapters/`
- `tests/api/`

Cases cần bổ sung:

1. Hai request `/scan` gần nhau:
   một request được chạy, một request `409`.
2. Scanner gặp file `status=indexing` và `s3_last_modified` mới:
   policy retry/skip phải rõ ràng.
3. File `status=failed` phải được retry.
4. File `status=indexed` nhưng `s3_last_modified` mới hơn -> phải queue re-ingest.
5. Rename path trong S3 làm đổi `doc_id`:
   test khóa current design decision, duplicate là expected behavior hiện tại.
6. Bucket lớn nhiều object:
   unit test mô phỏng pagination và verify scanner không bỏ sót trang sau.

### 11. Timeout, retry, và worker pool

Folder đề xuất:
- `tests/api/`
- `tests/streaming/`
- `tests/pipeline/`

Cases cần bổ sung:

1. Job vượt `SCAN_JOB_TIMEOUT_SECONDS` phải mark `failed`.
2. Một worker timeout không được làm cả batch `/scan` crash im lặng.
3. `SCAN_MAX_WORKERS=1` và `>1` phải cho kết quả queue/process nhất quán.
4. Transient AI failure lần 1, thành công lần 2:
   retry batch/job phải đúng scope mong đợi.
5. Kafka retry hết số lần -> gửi DLQ duy nhất một bản ghi.
6. DLQ write file fail vì `OSError`:
   consumer không được crash vĩnh viễn.

## Ưu tiên 2: API và health semantics

### 12. API hardening

Folder đề xuất:
- `tests/api/`

Cases cần bổ sung:

1. `/health` phải trả `503` nếu downstream bắt buộc không sẵn sàng, nếu design đổi theo docs production.
2. Nếu app đang dùng `MockAIProvider` trong env production-like:
   health payload phải expose rõ.
3. Nếu vector store fallback InMemory:
   health hoặc startup log phải phát hiện được.
4. `/status/{doc_id}` với doc không tồn tại -> `404`.
5. `/scan` response phải có `queued` và không được trả số âm.
6. `/search` phải trả `request_id` hợp lệ trên mọi response.

## Ưu tiên 2: Config và startup behavior

### 13. Fallback và startup validation

Folder đề xuất:
- `tests/utils/`
- `tests/api/`

Cases cần bổ sung:

1. Không có `AI_API_KEY` và `AI_PROVIDER=auto` -> dùng `MockAIProvider`.
2. `AI_PROVIDER=openai` nhưng thiếu key -> startup fail rõ ràng, nếu sau này áp dụng stricter mode.
3. Qdrant unavailable:
   xác minh current fallback sang InMemory và test cover cảnh báo/log.
4. PostgreSQL unavailable:
   xác minh fallback chain Postgres -> File -> Memory đúng như docs.
5. Config `CHUNK_OVERLAP >= CHUNK_SIZE` phải reject.
6. Config `EMBEDDING_DIM <= 0` phải reject.

## Ưu tiên 3: Observability và operational contracts

### 14. Job records, logs, metrics-friendly behavior

Folder đề xuất:
- `tests/pipeline/`
- `tests/api/`

Cases cần bổ sung:

1. `ingestion_jobs.duration_seconds` luôn có giá trị không âm.
2. `error_message` được ghi khi fail parse/embed/index.
3. `embedding_model` được lưu vào `ingestion_jobs`.
4. `processed_at` chỉ được set khi indexed thành công.
5. `updated_at` phải thay đổi khi re-ingest.
6. `uploaded_at` không được bị ghi đè sai nghĩa khi dùng `s3_last_modified`.

## Ưu tiên 3: Regression tests theo production risks

### 15. Regression backlog từ Production Analysis

Folder đề xuất:
- phân bổ theo domain ở trên

Cases cần bổ sung:

1. OCR PDF scan không được trả empty text mà vẫn marked indexed.
2. `page_start/page_end` không được null với text có page boundaries rõ ràng.
3. Search không được trả kết quả score rất thấp nếu threshold đang bật.
4. Scanner không được compare S3 timestamp với `uploaded_at`.
5. Re-ingest không được bị race tạo duplicate processing trong cùng một scan cycle.
6. Consumer at-least-once không được tạo duplicate indexed chunks khi replay event.

## Đề xuất thứ tự implement

### Đợt 1

- Retrieval permission cases
- Indexing atomicity gap cases
- PDF malformed/password-protected cases
- `/health` và fallback behavior cases

### Đợt 2

- Scanner concurrency và stale indexing cases
- Config drift/dimension mismatch cases
- File size/path traversal cases
- DLQ disk full / retry storm cases

### Đợt 3

- Migration-safe cases
- Observability contract cases
- Performance-oriented integration cases

## Ghi chú khi implement

- Ưu tiên mock/stub cho AI, Qdrant, và S3 thay vì gọi thật.
- Test nào khóa behavior hiện tại dù rủi ro vẫn nên ghi rõ:
  `current behavior` và `desired future behavior`.
- Các case về production fallback nên thêm marker rõ ràng, vì một số case có thể phụ thuộc env startup.
- Nếu bổ sung test cho feature chưa implement, có thể đánh dấu `xfail` tạm thời, nhưng chỉ nên làm với case đã được chốt trong docs.

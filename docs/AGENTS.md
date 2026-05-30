# AGENTS.md — DE Vector Search Engine

## System này làm gì

Tự động quét S3, parse và index nội dung tài liệu thành vector embeddings. Trả context về caller qua REST API semantic search.

Đây là một Python service độc lập — không phải một module trong platform lớn hơn.

## Hai luồng duy nhất — không có ngoại lệ

| Hướng | Luồng | Code |
|---|---|---|
| **VÀO** | S3 scanner polls bucket → `IngestJob` → pipeline xử lý | `adapters/s3_adapter.py` → `app/application/ingest/run_ingest_job.py` |
| **RA** | `POST /search` → embed query → vector search → kết quả | `api/main.py` → `app/application/search/search_sections.py` |

Bất kỳ path nào đưa thông tin vào/ra ngoài 2 luồng này là bug hoặc dev tool — không phải kiến trúc.

## Off-limits — không được đụng, không được tham chiếu

| Thứ | Trạng thái |
|---|---|
| `streaming/kafka_consumer.py` | Dead code — Kafka đã bị loại bỏ hoàn toàn |
| `tests/streaming/` | Dead tests cho Kafka — không thêm test vào đây |
| Kafka env vars (`KAFKA_*`, `TOPIC_*`) | Không còn dùng |
| `document_permissions` table | Đã drop — permission logic không còn ở service này |
| `POST /retrieve-context` | Endpoint cũ — API đúng là `POST /search` |
| `DocumentUploaded` Kafka event format | Event bus không còn tồn tại |

Nếu thấy code cũ còn tham chiếu những thứ trên → đó là legacy noise, không dùng làm cơ sở implement.

## Conventions bắt buộc

1. **Application layer chỉ phụ thuộc vào ports** — `app/application/` không được import `boto3`, `openai`, `qdrant_client`, `sqlalchemy` hay bất kỳ SDK cụ thể nào. Mọi dependency đi qua port interface trong `app/ports/`.
2. **Runtime config qua env vars** — không hardcode URL, key, hay model name vào code.
3. **Mọi thay đổi API contract hoặc DB schema** → cập nhật `PIPELINE.md` trước khi merge.
4. **`FileAdapter`** là dev/test only — không xuất hiện trong production flow, không mô tả trong architecture.
5. **`/health` phải phản ánh fallback** — nếu thêm dependency mới, phải hook vào health check.
6. **Không thêm luồng vào/ra mới** mà không cập nhật `ARCHITECTURE.md` và `PIPELINE.md` trước.

## Tìm thứ gì ở đâu

| Tôi cần biết... | File |
|---|---|
| Developer mới — setup từ đầu, cấu trúc, workflow hàng ngày | `ONBOARDING.md` |
| Tại sao system thiết kế thế này + diagram + design principles + extension guide | `ARCHITECTURE.md` |
| Chi tiết từng bước pipeline, schema DB, API request/response, env vars | `PIPELINE.md` |
| Cách chạy local, docker compose, test commands | `SETUP.md` |
| CI/CD — 5 jobs, trigger logic, secrets, debug failed deploy | `CICD.md` |
| Vận hành GKE, xem log, debug production | `GKE.md` |
| Production risks, bottlenecks, hardening backlog | `RISKS.md` |
| Test structure + coverage backlog còn thiếu | `TESTS.md` |
| Thứ gì đã bị bỏ, code nào là legacy, không được dùng làm reference | `LEGACY.md` |
| Schema log task, sprint review cadence, cách track agent quality | `LOGGING.md` |

## Nguyên tắc làm việc

1. **Đọc trước khi code** — đọc docs tương ứng (xem "Tìm thứ gì ở đâu"), code hiện tại của component bị ảnh hưởng, và contract mà nó expose. Nếu behavior kỳ vọng vẫn không rõ → hỏi một câu cụ thể, không tự đoán.

2. **Mỗi unit có nguyên tắc rõ trước khi viết** — xác định interface tối giản nhất và complexity nào phải ẩn bên trong. Kiểm tra: mô tả được bằng một câu không có "and" không? Nếu có "and" → tách thành 2 unit trước.

3. **Test theo 2 tầng**:
   - *General*: input hợp lệ → output đúng, contract không vỡ, chạy được với mock/in-memory.
   - *Edge case*: input rỗng/null/sai type, boundary values, failure path — dependency lỗi thì caller nhận được gì? Không bỏ qua vì "ít xảy ra".

4. **Docs phản ánh thực tế, không phải ý định** — sau khi code và test xong, cập nhật đúng file (xem "Tìm thứ gì ở đâu"). Không viết ý định, không viết "sẽ cải thiện sau". Nếu cần comment giải thích lý do → interface chưa đủ rõ, sửa interface trước.

## Definition of done

Mọi task hoàn thành khi tất cả các điều sau đúng:

- [ ] Code chạy được với `MockAIProvider` + `InMemoryVectorStore` + `InMemoryMetadataStore`
- [ ] Unit tests pass cho component bị thay đổi
- [ ] Không vi phạm nguyên tắc "chỉ 2 luồng qua ranh giới"
- [ ] Nếu thay đổi API contract hoặc DB schema → `PIPELINE.md` đã được cập nhật
- [ ] Nếu thay đổi dev/test flow → `SETUP.md` đã được cập nhật
- [ ] `/health` vẫn phản ánh đúng fallback state
- [ ] Không có SDK-specific code trong `app/application/` hoặc `app/domain/`

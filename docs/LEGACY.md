# Legacy — Thứ đã bị bỏ, code không được tham chiếu

## Bối cảnh migrate

Project này đã chuyển từ e-commerce analytics pipeline (PySpark) sang document ingestion + vector search engine. Một số file code cũ còn tồn tại trong repo nhưng không còn là part của kiến trúc hiện tại.

## So sánh trước và sau

| Hạng mục | Pipeline cũ | Hiện tại |
|---|---|---|
| Input | event rows / analytics dataset | S3 scanner phát hiện file |
| Compute | PySpark-oriented | Python service |
| Trigger | batch pipeline | S3 scanner tự động + `/scan` thủ công |
| Output | tables / features | vectors + metadata + job history |
| Serving | analytics API | `POST /search` — semantic search |

## Những gì đã bị loại bỏ hoàn toàn

Các khái niệm sau **không còn là source of truth**. Nếu gặp trong tài liệu cũ → đó là historical noise:

| Khái niệm | Lý do bỏ |
|---|---|
| Kafka consumer / producer / DLQ | Event bus thay bằng S3 scanner — không cần Kafka |
| `DocumentUploaded` Kafka event | Không còn event bus |
| `streaming/kafka_consumer.py` | Dead code — Kafka đã bỏ |
| `tests/streaming/` | Dead tests cho Kafka — không thêm test vào đây |
| `KAFKA_BOOTSTRAP` env var | Kafka không còn dùng |
| `document_permissions` table | Permission logic chuyển ra BE |
| `POST /retrieve-context` | Đổi thành `POST /search` |
| Permission filter trong retrieval | Retrieval không còn filter permission |
| `POST /ingest` nhận document từ caller | Nguồn duy nhất là S3 |

## Code còn tồn tại nhưng đã đổi vai trò

Các file này vẫn được dùng nhưng với mục đích khác:

| File | Vai trò cũ | Vai trò hiện tại |
|---|---|---|
| `utils/storage.py` | Storage utilities cho analytics | Đọc file từ local hoặc S3 |
| `docker-compose.yml` | Orchestration cho pipeline cũ | Local stack: postgres + qdrant + minio |
| `config/settings.py` | Runtime config analytics | Runtime config vector search engine |

## Không tham chiếu những thứ trên

Khi thêm tính năng mới: bám vào `IngestJob`, `ChunkResult`, `VectorStore`, `MetadataStore` và REST surface hiện tại (`/search`, `/scan`, `/status`, `/health`). Không dùng tài liệu cũ làm ràng buộc thiết kế.

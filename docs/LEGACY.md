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
| `utils/stores.py` | Chứa toàn bộ VectorStore/MetadataStore implementations | Re-export layer backward compat — implementations đã chuyển sang `app/infrastructure/` |
| `models/ingest_job.py` | Model chính cho ingest | Compat alias file: `ChunkResult = SectionRecord`, re-export các domain models |
| `pipeline/run.py` | Orchestrator chính | Thin wrapper gọi `RunIngestJob` — không chứa logic |
| `pipeline/01_parse.py` | Parse file thực sự | Thin wrapper — logic trong `RouterDocumentParser` |
| `pipeline/03_chunk.py` | Chunk 512 token | Thin wrapper — không còn là retrieval unit |
| `pipeline/04_embed.py` | Embed chunk content | Thin wrapper — hiện embed caption |
| `pipeline/05_index.py` | Index chunk records | Thin wrapper — hiện index section records |
| `retrieval/service.py` | Search service chính | Thin wrapper — logic trong `SearchSections` use case |

## Compat aliases đã tồn tại nhưng sẽ bị xóa

| Alias | Tại đâu | Trỏ về |
|---|---|---|
| `ChunkResult` | `models/ingest_job.py` | `SectionRecord` trong `app/domain/documents/models.py` |

**Không tạo thêm alias mới.** Khi viết code mới, dùng trực tiếp `SectionRecord`.

## Không tham chiếu những thứ trên

Khi thêm tính năng mới: bám vào `app/ports/`, `app/application/`, `app/domain/` và REST surface hiện tại (`/search`, `/scan`, `/status`, `/health`). Không dùng tài liệu cũ hay các wrapper file trên làm ràng buộc thiết kế.

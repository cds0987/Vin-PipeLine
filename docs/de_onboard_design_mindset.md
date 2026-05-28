# DE Pipeline — Onboard Design Mindset

> Tài liệu này mô tả **tư duy thiết kế** cho DE team khi build ingestion pipeline trong môi trường codebase chưa hoàn chỉnh, BE chưa deliver, SA chưa có tài liệu cuối. Mục tiêu: onboard đúng hạn, không bị block, không cần rewrite khi bên ngoài thay đổi.

---

## 1. Vấn đề cần giải quyết

Dự án gấp. Codebase BE chưa có. SA chưa confirm architecture cuối. Nhưng DE phải build ngay.

Rủi ro nếu không có mindset đúng:

| Tình huống | Hậu quả nếu code bẩn |
|------------|----------------------|
| BE deliver Kafka schema khác mock | Sửa nhiều chỗ trong pipeline |
| SA đổi message queue (Kafka → RabbitMQ) | Rewrite consumer |
| SA đổi Vector DB (Chroma → Qdrant) | Rewrite toàn bộ write logic |
| Permission model thay đổi | Rewrite cả permission handling |
| BE đổi field name trong event | Pipeline crash, không replay được |

**Giải pháp:** Thiết kế DE như một **black box độc lập** — bên ngoài thay đổi gì thì chỉ đụng vào đúng một lớp mỏng ở rìa.

---

## 2. Nguyên tắc cốt lõi — Ports & Adapters

```
Bên ngoài (thay đổi thoải mái)
        ↓
   Input Adapter          ← chỉ sửa chỗ này khi BE/SA thay đổi input
        ↓
   Input Port: IngestJob  ← contract bất biến
        ↓
   CORE PIPELINE          ← không bao giờ đổi
   (parse → chunk → embed → enrich)
        ↓
   Output Port: ChunkResult ← contract bất biến
        ↓
   Output Adapter         ← chỉ sửa chỗ này khi SA đổi store
        ↓
Bên ngoài (thay đổi thoải mái)
```

**Rule duy nhất:** Core pipeline không được import bất cứ thứ gì từ Adapter. Chỉ nhận `IngestJob`, chỉ trả `ChunkResult`.

---

## 3. Input Port — IngestJob (bất biến)

Đây là contract nội bộ của DE. Bất kỳ nguồn nào từ bên ngoài đều phải map về struct này trước khi vào pipeline.

```python
class IngestJob(BaseModel):
    doc_id: str                           # bắt buộc
    file_uri: str                         # bắt buộc — s3://... hoặc /local/path
    language: str = "vi"                  # default
    document_type: str = "general"        # default
    permission: Optional[PermissionModel] = None
    metadata: dict = {}

class PermissionModel(BaseModel):
    visibility: str = "private"           # private | org | public
    allowed_roles: List[str] = []
    allowed_users: List[str] = []
    owner_id: Optional[str] = None
    org_id: Optional[str] = None
```

> Chỉ `doc_id` và `file_uri` là bắt buộc. Còn lại có default — mock thiếu field vẫn chạy được.

---

## 4. Output Port — ChunkResult (bất biến)

Pipeline luôn trả ra struct này. Output Adapter nhận và ghi vào bất kỳ store nào.

```python
class ChunkResult(BaseModel):
    chunk_id: str                         # doc_id + "_chunk_" + index
    doc_id: str
    content: str
    embedding: List[float]
    page_start: Optional[int]
    page_end: Optional[int]
    section: Optional[str]
    metadata: dict                        # chunking_strategy, embedding_model, v.v.
```

---

## 5. Input Adapters — lớp duy nhất thay đổi khi BE/SA đổi

### 5.1 KafkaAdapter (dùng khi BE deliver)

```python
class KafkaAdapter:
    def map(self, raw_event: dict) -> IngestJob:
        # Đây là nơi DUY NHẤT cần sửa khi BE đổi schema
        return IngestJob(
            doc_id=raw_event["doc_id"],
            file_uri=raw_event["s3_uri"],          # BE đổi tên → sửa dòng này
            language=raw_event.get("metadata", {}).get("language", "vi"),
            document_type=raw_event.get("metadata", {}).get("document_type", "general"),
            permission=self._map_permission(raw_event.get("permission")),
        )
```

### 5.2 FileAdapter (dùng ngay từ tuần 1, không cần BE)

```python
class FileAdapter:
    def map(self, file_path: str, doc_id: str = None) -> IngestJob:
        return IngestJob(
            doc_id=doc_id or str(uuid4()),
            file_uri=file_path,
        )
```

### 5.3 RESTAdapter (dùng cho manual trigger)

```python
class RESTAdapter:
    def map(self, request_body: dict) -> IngestJob:
        return IngestJob(**request_body)
```

### Khi SA đổi message queue

```
# Kafka → RabbitMQ
# Chỉ viết thêm RabbitMQAdapter, không đụng vào KafkaAdapter hay Core
class RabbitMQAdapter:
    def map(self, amqp_message: dict) -> IngestJob:
        ...
```

---

## 6. Output Adapters — lớp duy nhất thay đổi khi SA đổi store

### VectorStore interface

```python
class VectorStore(ABC):
    def upsert(self, chunks: List[ChunkResult]) -> None: ...
    def search(self, query_vec: List[float], top_k: int, filters: dict) -> List[ChunkResult]: ...
    def delete(self, doc_id: str) -> None: ...

# Dev
class ChromaStore(VectorStore): ...

# Production — chỉ viết thêm class này, không đổi gì khác
class QdrantStore(VectorStore): ...
class MilvusStore(VectorStore): ...
```

### MetadataStore interface

```python
class MetadataStore(ABC):
    def upsert_document(self, doc: DocumentRecord) -> None: ...
    def update_status(self, doc_id: str, status: str) -> None: ...
    def upsert_permission(self, doc_id: str, permission: PermissionModel) -> None: ...
```

> Đổi từ PostgreSQL sang MongoDB hay bất kỳ DB nào — chỉ viết thêm implementation, Core không đổi.

---

## 7. Core Pipeline — không bao giờ đổi

```python
class IngestionPipeline:
    def __init__(self, vector_store: VectorStore, metadata_store: MetadataStore):
        # Inject store qua interface — không biết đang dùng Chroma hay Qdrant
        self.vector_store = vector_store
        self.metadata_store = metadata_store

    def run(self, job: IngestJob) -> None:
        # Bước 1: idempotent — xóa chunks cũ nếu đã tồn tại
        self.vector_store.delete(job.doc_id)

        # Bước 2: parse
        text = self._parse(job.file_uri)

        # Bước 3: chunk
        chunks = self._chunk(text, job)

        # Bước 4: embed
        chunks = self._embed(chunks)

        # Bước 5: ghi ra store
        self.vector_store.upsert(chunks)
        self.metadata_store.update_status(job.doc_id, "indexed")
        if job.permission:
            self.metadata_store.upsert_permission(job.doc_id, job.permission)
```

---

## 8. Dead Letter Queue — không mất event khi thay đổi

```
Event vào
    ↓
Validate (Pydantic)
    ↓ fail
    → DLQ: schema_error   ← alert BE ngay, sửa Mapper, replay
    ↓ pass
Mapper → IngestJob
    ↓
Pipeline
    ↓ fail (S3 timeout, OCR lỗi)
    → retry 3x
    → DLQ: pipeline_error ← fix, replay
    ↓ pass
Done — update status = indexed
```

**Replay script:** khi fix xong Mapper hoặc pipeline, chạy lại toàn bộ event trong DLQ mà không cần upload lại file.

---

## 9. Kafka Event — schema_version bắt buộc

```json
{
  "event": "DocumentUploaded",
  "schema_version": "1.0",
  "doc_id": "doc_123",
  "s3_uri": "s3://bucket/policy.pdf",
  "uploaded_by": "user_abc",
  "metadata": {
    "file_name": "policy.pdf",
    "document_type": "policy",
    "language": "vi"
  },
  "permission": {
    "visibility": "private",
    "allowed_roles": ["admin", "legal"],
    "allowed_users": [],
    "owner_id": "user_abc",
    "org_id": "org_456"
  },
  "timestamp": "2026-05-28T10:00:00Z"
}
```

Consumer kiểm tra `schema_version` trước khi parse — version cũ dùng Mapper cũ, version mới dùng Mapper mới. Không vỡ khi migrate.

---

## 10. Build order — onboard đúng hạn không cần đợi ai

### Tuần 1 — Core pipeline + FileAdapter
- Không cần Kafka, không cần BE, không cần SA confirm
- Dùng FileAdapter đọc file local hoặc S3 trực tiếp
- Test với 20 file thật, đo chất lượng chunk và retrieval
- Deliverable: pipeline chạy end-to-end, Vector DB có data thật

```bash
python ingest.py --file ./samples/policy.pdf
python ingest.py --folder ./samples/
```

### Tuần 2 — KafkaAdapter + mock event + DLQ
- Viết KafkaAdapter map mock event → IngestJob
- Setup DLQ, test retry logic
- Core pipeline không đổi một dòng
- Deliverable: consumer chạy được với mock event tự publish

```json
// Mock event tự publish, không cần BE
{"event":"DocumentUploaded","schema_version":"1.0","doc_id":"test_001","s3_uri":"s3://bucket/test.pdf"}
```

### Tuần 3 — Retrieval API
- Expose Output Port ra HTTP: `POST /retrieve-context`
- Permission filter trong Retrieval Service
- Swagger / OpenAPI doc
- Deliverable: API có thể test bằng Postman, latency < 500ms

### Khi BE deliver (bất kỳ lúc nào)
- Cập nhật `KafkaAdapter.map()` cho đúng schema thật
- Thời gian: 30 phút đến 2 giờ tùy mức độ khác biệt so với mock
- Core pipeline, Retrieval API không đổi gì

### Khi SA đổi stack (bất kỳ lúc nào)
- Đổi message queue → viết thêm Adapter mới
- Đổi Vector DB → viết thêm Store implementation
- Thời gian: 1 ngày mỗi thứ
- Core pipeline không đổi gì

---

## 11. Khi nào cần họp với BE/SA

Chỉ cần sync **1 lần duy nhất** để chốt 3 thứ tối thiểu:

| Thứ cần chốt | Lý do | Nếu chưa chốt được |
|---|---|---|
| `doc_id` format | UUID hay string tự sinh — join key giữa các store | Dùng UUID v4 làm default |
| Kafka topic name | Consumer cần biết subscribe topic nào | Dùng `document.ingestion.v1` làm default |
| `permission` shape | Có dùng roles từ PostgreSQL không | Dùng inline payload làm default |

> Nếu SA/BE không available — document assumption, gửi email, đợi 2 ngày không reply thì coi như accepted. Build theo assumption, Mapper sẽ absorb thay đổi sau.

---

## 12. Quy tắc cứng

```
✅ Core pipeline chỉ nhận IngestJob, chỉ trả ChunkResult
✅ Mọi nguồn bên ngoài đều phải qua Adapter trước khi vào Core
✅ Mọi store đều được inject qua interface — không gọi SDK trực tiếp trong Core
✅ DLQ cho mọi loại lỗi — không drop event
✅ Pipeline idempotent — chạy lại cùng doc_id không sinh chunk trùng
✅ schema_version trong mọi Kafka event
✅ Lưu embedding_model và chunking_strategy vào mỗi chunk

❌ Core không import Kafka SDK, S3 SDK, Chroma SDK, hay bất kỳ Adapter nào
❌ Không hardcode permission vào Vector DB metadata
❌ Không đợi BE hay SA xong mới bắt đầu — build với FileAdapter từ tuần 1
❌ Không họp thêm ngoài 1 buổi sync ban đầu — mọi thay đổi sau absorb qua Adapter
```

---

## 13. Tóm tắt một câu

> **Build Core pipeline thật tốt từ tuần 1 bằng FileAdapter. Mọi thứ bên ngoài — Kafka, BE schema, Vector DB, Permission model — đều là Adapter mỏng ở rìa. Bên ngoài thay đổi gì thì chỉ viết hoặc sửa Adapter, Core không ai đụng vào.**

# overview.md — DE Ingestion Service

## Phạm vi service

Đây là **1 service độc lập** — nhận tài liệu thô, xử lý hoàn toàn bên trong, ghi ra store.  
Bên ngoài chỉ giao tiếp qua **REST API**. Mọi chi tiết triển khai là black box.

---

## Vị trí trong hệ thống

```
Frontend
   │  (1) upload file → xin Presigned URL
   ▼
Backend (BE)
   │  (2) publish Kafka event: DocumentUploaded
   ▼
[ DE Service — black box ]
   │  parse → clean → chunk → embed → index
   ▼
Vector DB + Metadata DB + Permission Store
   ▲  (3) query qua Retrieval API
[ DE Service — Retrieval ]
   │  (4) contexts[] đã filter permission
   ▼
Backend (BE)
   │  (5) build prompt + call LLM
   ▼
LLM → Answer → User
```

---

## Ranh giới trách nhiệm

| Phần | Owner | Không được phép |
|---|---|---|
| Upload API, Presigned URL, Auth | BE | Gọi thẳng Vector DB |
| Kafka publish + permission definition | BE | Tự quyết chunking / embedding |
| Parse, clean, chunk, embed, index | DE | Sửa permission |
| Retrieval API, permission filter | DE | Trả chunk chưa filter |
| Prompt building, LLM call | BE | Import SDK Vector DB |

---

## Luồng xử lý bên trong

```
Input (PDF / DOCX / PPTX / TXT / MD / HTML / Image)
        │
        ▼
   01_parse      ─── nếu scan/ảnh → AIProvider.ocr()
        │
        ▼
   02_clean      ─── loại noise, normalize (rule-based)
        │
        ▼
   03_chunk      ─── sliding window (CHUNK_SIZE=512 tokens, CHUNK_OVERLAP=64 default)
        │
        ▼
   04_embed      ─── AIProvider.embed()
        │
        ▼
   05_index      ─── VectorStore.upsert() + MetadataStore.upsert()
```

---

## AIProvider — 1 interface duy nhất cho mọi tác vụ AI

Toàn bộ pipeline chỉ biết `AIProvider`. Không import OpenAI SDK ngoài lớp này.

```python
# utils/ai_provider.py

class AIProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def ocr(self, image_bytes: bytes) -> str: ...

class OpenAIProvider:
    """Trỏ tới OpenAI cloud, Ollama, vLLM, LM Studio — chỉ đổi config."""
    def __init__(self, base_url: str, api_key: str, embed_model: str, vision_model: str):
        self._client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self._embed_model = embed_model
        self._vision_model = vision_model

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(model=self._embed_model, input=texts)
        return [d.embedding for d in resp.data]

    def ocr(self, image_bytes: bytes) -> str:
        b64 = base64.b64encode(image_bytes).decode()
        resp = self._client.chat.completions.create(
            model=self._vision_model,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": "Extract all text from this image."},
            ]}],
        )
        return resp.choices[0].message.content
```

### Đổi AI server — chỉ đổi config, không đổi code

| Môi trường | AI_BASE_URL | AI_API_KEY | EMBED_MODEL |
|---|---|---|---|
| OpenAI cloud | `https://api.openai.com/v1` | `sk-...` | `text-embedding-3-small` |
| Ollama local | `http://localhost:11434/v1` | `ollama` | `nomic-embed-text` |
| vLLM server | `http://gpu-host:8000/v1` | `token-...` | model name trên server |
| Azure OpenAI | `https://<resource>.openai.azure.com/` | `...` | deployment name |

### Đổi Qdrant server — chỉ đổi config, không đổi code

**Ưu tiên connection (logic tự động trong `QdrantStore`):**

```
QDRANT_URL có giá trị?
    ├─ YES → QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)
    │         → Qdrant Cloud hoặc self-hosted có auth
    └─ NO  → QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
              → Local Docker / self-hosted không cần auth
```

| Môi trường | Env vars cần set |
|---|---|
| Local Docker | `QDRANT_HOST=qdrant`, `QDRANT_PORT=6333` *(default, không cần set)* |
| Self-hosted | `QDRANT_HOST=<ip>`, `QDRANT_PORT=6333` |
| Qdrant Cloud (có API key) | `QDRANT_URL=https://<cluster>.cloud.qdrant.io`, `QDRANT_API_KEY=<key>` |
| Qdrant Cloud (không auth) | `QDRANT_URL=https://<cluster>.cloud.qdrant.io` *(bỏ trống API key)* |

> Xóa hoặc bỏ trống `QDRANT_URL` để switch về local — không cần đổi code.

**Lưu ý kỹ thuật — `QdrantStore` implementation:**
- Search dùng `client.query_points()` (API từ qdrant-client ≥ 1.7; `client.search()` đã bị xóa)
- Payload index trên field `doc_id` được tạo tự động khi khởi tạo — **bắt buộc** trên Qdrant Cloud để filter trong `delete()`; idempotent nếu index đã tồn tại

---

## Store Adapters — đổi DB không đổi pipeline

```python
# utils/stores.py

class VectorStore(Protocol):
    def upsert(self, chunks: list[ChunkResult]) -> None: ...
    def search(self, vector: list[float], top_k: int, filters: dict | None = None) -> list[ChunkResult]: ...
    def delete(self, doc_id: str) -> None: ...

class MetadataStore(Protocol):
    def upsert(self, doc: DocumentRecord) -> None: ...
    def update_status(self, doc_id: str, status: str) -> None: ...
    def upsert_permission(self, doc_id: str, permission: PermissionModel) -> None: ...
    def get_permission(self, doc_id: str) -> PermissionModel | None: ...

# Implementations — thêm class mới khi SA đổi stack, pipeline không đổi
class QdrantStore(VectorStore): ...             # default (local + cloud)
class InMemoryVectorStore(VectorStore): ...     # test / CI / fallback
class SQLMetadataStore(MetadataStore): ...
class FileMetadataStore(MetadataStore): ...     # local dev / fallback khi Postgres unavailable
class InMemoryMetadataStore(MetadataStore): ... # test / CI
```

---

## Config — tất cả thay đổi qua env vars

```python
# config/settings.py — pydantic-settings (BaseSettings), đọc từ env vars / .env

# AI Provider
AI_PROVIDER    = "auto"               # "auto" | "mock" | "openai"; "auto" → OpenAI nếu có API key, else Mock
AI_BASE_URL    = None                 # e.g. "https://api.openai.com/v1" hoặc Ollama/vLLM URL
AI_API_KEY     = None                 # set để dùng OpenAI; để None → MockAIProvider
EMBED_MODEL    = "text-embedding-3-small"
VISION_MODEL   = "gpt-4o"
EMBEDDING_DIM  = 1536

# Chunking
CHUNK_SIZE     = 512                  # tokens per chunk
CHUNK_OVERLAP  = 64                   # overlap tokens

# Vector DB
VECTOR_STORE      = "qdrant"          # "qdrant" | "memory"
QDRANT_HOST       = "qdrant"
QDRANT_PORT       = 6333
QDRANT_URL        = None              # Qdrant Cloud override (xem fallback logic trên)
QDRANT_API_KEY    = None              # Qdrant Cloud auth
QDRANT_COLLECTION = "documents"

# Metadata DB
METADATA_STORE = "postgres"           # "postgres" | "file" | "memory"
DB_URL         = "postgresql://rag:rag@postgres:5432/ragdb"

# Storage (S3 / MinIO)
S3_BUCKET             = "rag-pipeline-local"
USE_S3                = False
S3_ENDPOINT           = "http://minio:9000"
AWS_ACCESS_KEY_ID     = None         # None → boto3 credential chain (IAM role, etc.)
AWS_SECRET_ACCESS_KEY = None

# Kafka
KAFKA_BOOTSTRAP      = "kafka:9092"
TOPIC_INGEST         = "DocumentUploaded"
TOPIC_DONE           = "EmbeddingDone"
TOPIC_FAILED         = "IndexingFailed"
TOPIC_PERMISSION     = "PermissionUpdated"
TOPIC_DLQ            = "DocumentUploaded.DLQ"
CONSUMER_GROUP_ID    = "de-ingestion-service"
CONSUMER_MAX_RETRIES = 3
```

---

## REST API — surface duy nhất expose ra ngoài

```
POST /ingest
  Body:     { "doc_id": "...", "file_uri": "s3://...", "uploaded_by": "...", "org_id": "...", "permission": {...}, "metadata": {...} }
  Response: { "doc_id": "...", "status": "queued" }

POST /retrieve-context
  Body:     { "query": "...", "user_id": "...", "user_roles": [...], "org_id": "...", "top_k": 5 }
  Response: { "request_id": "...", "contexts": [ { "chunk_id", "content", "score", "source", "metadata" } ] }

GET /health
  Response: { "status": "ok", "vector_store": "...", "ai_provider": "..." }
```

---

## Kafka Event Schema

### DocumentUploaded (BE publish, DE consume)

```json
{
  "event": "DocumentUploaded",
  "schema_version": "1.0",
  "doc_id": "doc_123",
  "s3_uri": "s3://bucket/path/policy.pdf",
  "uploaded_by": "user_abc",
  "org_id": "org_456",
  "metadata": {
    "file_name": "policy.pdf",
    "document_type": "policy",
    "language": "vi",
    "file_size_bytes": 204800
  },
  "permission": {
    "visibility": "private",
    "allowed_roles": ["admin", "legal"],
    "allowed_users": ["user_xyz"],
    "owner_id": "user_abc",
    "org_id": "org_456"
  },
  "timestamp": "2026-05-28T10:00:00Z"
}
```

| Field | Bắt buộc | Default nếu thiếu |
|---|---|---|
| `doc_id` | ✅ | — |
| `s3_uri` | ✅ | — |
| `uploaded_by` | ✅ | — |
| `language` | ❌ | `"vi"` |
| `document_type` | ❌ | `"general"` |
| `permission` | ❌ | `{ visibility: "private", owner_id: uploaded_by }` |

### Events DE publish

```json
{ "event": "EmbeddingDone",   "doc_id": "doc_123", "chunk_count": 42 }
{ "event": "IndexingFailed",  "doc_id": "doc_123", "reason": "OCR timeout" }
```

---

## Data Stores Schema

### Metadata DB (PostgreSQL)

```sql
documents (
  id              TEXT PRIMARY KEY,        -- doc_id từ Kafka event (UUID string)
  file_path       TEXT NOT NULL,           -- s3://... hoặc /local/path
  file_name       TEXT,
  file_type       TEXT,                    -- pdf | docx | txt | html | image (format kỹ thuật)
  document_type   TEXT DEFAULT 'general',  -- policy | contract | manual (phân loại nghiệp vụ)
  language        TEXT DEFAULT 'vi',
  status          TEXT DEFAULT 'pending',  -- pending | indexing | indexed | failed
  uploaded_by     TEXT,
  org_id          TEXT,
  uploaded_at     TIMESTAMP,               -- khi user upload file
  processed_at    TIMESTAMP,               -- khi pipeline hoàn thành
  updated_at      TIMESTAMP
)

document_permissions (
  doc_id          TEXT PRIMARY KEY,        -- FK logic đến documents.id
  visibility      TEXT DEFAULT 'private',  -- private | org | public
  owner_id        TEXT,
  org_id          TEXT,
  allowed_roles   JSONB DEFAULT '[]',      -- list of role name strings (từ BE)
  allowed_users   JSONB DEFAULT '[]',      -- list of user_id strings (từ BE)
  updated_at      TIMESTAMP
)
```

### Vector DB (schema per chunk)

```json
{
  "chunk_id":        "doc_123_chunk_004",
  "document_id":     "doc_123",
  "content":         "...",
  "embedding":       [0.12, -0.34, "..."],
  "page_start":      2,
  "page_end":        2,
  "chunk_index":     4,
  "embedding_model": "text-embedding-3-small"
}
```

> Permission **không** lưu vào Vector DB — lưu riêng trong `document_permissions`. Thu hồi quyền chỉ update 1 bảng, không reindex.

---

## Permission Filter Algorithm (Retrieval Service)

```
1. Lấy top_k × 3 chunks từ Vector DB (lấy dư để bù sau khi filter)
2. Với mỗi chunk, query document_permissions theo doc_id
3. Kiểm tra:
   - visibility = "public"                    → pass
   - user_id == owner_id                      → pass
   - user_roles ∩ allowed_roles ≠ ∅           → pass
   - user_id ∈ allowed_users                  → pass
   - org_id match + visibility = "org"        → pass
   - Còn lại                                  → loại
4. Trả top_k sau khi filter
```

---

## Contract nội bộ (không expose ra REST API)

```python
class IngestJob(BaseModel):      # Input Port — contract với BE, không đổi
    doc_id: str
    file_uri: str                # s3://... hoặc local path
    language: str = "vi"
    document_type: str = "general"   # phân loại nghiệp vụ: policy | contract | manual
    permission: Optional[PermissionModel] = None
    metadata: dict = {}

class DocumentRecord(BaseModel): # DB record — documents table
    id: str                      # = doc_id từ IngestJob
    file_path: str               # = file_uri từ IngestJob
    file_name: str | None = None
    file_type: str | None = None # format kỹ thuật: pdf | docx | txt | html | image
    document_type: str = "general"
    language: str = "vi"
    status: str = "pending"      # pending | indexing | indexed | failed
    uploaded_by: str | None = None
    org_id: str | None = None
    uploaded_at: datetime        # khi user upload
    processed_at: datetime | None = None  # khi pipeline xong
    updated_at: datetime

class ChunkResult(BaseModel):    # Output Port — contract bất biến
    chunk_id: str
    doc_id: str
    content: str
    embedding: list[float]
    page_start: Optional[int]
    page_end: Optional[int]
    section: Optional[str]
    metadata: dict               # embedding_model, chunk_strategy, language, v.v.
```

---

## Contracts phải thống nhất với BE

| Contract | Nội dung | Owner |
|---|---|---|
| Kafka event schema | `DocumentUploaded` field list + types | BE định nghĩa, DE implement |
| Permission model | `allowed_roles`, `visibility` values | BE định nghĩa, DE lưu + enforce |
| Retrieval API | Request/response shape `/retrieve-context` | DE định nghĩa, BE consume |
| Status values | `pending`, `indexing`, `indexed`, `failed` | Thống nhất hai bên |

---

## Quy tắc cứng

```
✅ Pipeline chỉ nhận IngestJob, chỉ trả ChunkResult — contract bất biến
✅ Mọi tác vụ AI đều qua AIProvider interface — không import openai SDK trong pipeline/
✅ Mọi store đều qua VectorStore / MetadataStore interface — không import DB SDK trong pipeline/
✅ Config thay đổi AI server / model / DB → chỉ đổi env vars, không đổi code
✅ FileAdapter cho phép test pipeline từ Day 1 — không cần Kafka, không cần BE
✅ DLQ cho mọi lỗi — không drop tài liệu
✅ Pipeline idempotent — ingest lại cùng doc_id không sinh chunk trùng
✅ Retrieval Service filter permission trước khi trả contexts[]
✅ schema_version trong mọi Kafka event

❌ Không import openai / chromadb / psycopg2 trực tiếp trong pipeline/
❌ Không hardcode model name hay AI_BASE_URL trong pipeline code
❌ Không lưu permission vào Vector DB metadata
❌ Không để API trả chunk rồi caller mới filter permission
❌ BE không import SDK của Vector DB hay embedding model
```

---

## Scale khi product mở rộng

| Nhu cầu | Thay đổi |
|---|---|
| Đổi AI model / server | 1 dòng env var |
| Đổi Vector DB (Milvus, Weaviate) | Thêm 1 class adapter, đổi env var |
| Thêm loại file mới | Thêm parser trong `01_parse.py` |
| Build AI agent xử lý data | Thêm step trong pipeline, extend AIProvider |
| Đổi message queue | Thêm Adapter mới, Core không đổi |
| Multi-tenant permission | Mở rộng `PermissionModel` + `MetadataStore` |

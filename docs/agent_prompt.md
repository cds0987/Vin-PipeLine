# Agent Prompt — DE Ingestion Service

## Nhiệm vụ

Build **DE Ingestion Service** — một service Python độc lập nhận tài liệu (PDF/DOCX/TXT/Image), xử lý qua pipeline parse → clean → chunk → embed → index, và expose REST API để retrieval.

---

## Đọc trước khi code

Đọc theo thứ tự:
1. `docs/overview.md` — kiến trúc, interfaces, contracts, quy tắc cứng
2. `docs/migration.md` — build order ngày nào làm gì, cái gì giữ lại
3. `docs/de_onboard_design_mindset.md` — khi nào cần đưa ra quyết định thiết kế

---

## Trạng thái hiện tại

✅ **Tất cả code đã hoàn thành và CI pass.** Không còn file nào cần rewrite hay tạo mới.

```
config/settings.py          ✅ Qdrant config, pydantic-settings, credential-safe
utils/storage.py            ✅ read_binary S3/local, boto3 credential chain
utils/notifier.py           ✅ Kafka publish với lazy producer, thread-safe
utils/ai_provider.py        ✅ AIProvider Protocol + OpenAIProvider + MockAIProvider
utils/stores.py             ✅ QdrantStore + InMemoryVectorStore
                               SQLMetadataStore + FileMetadataStore + InMemoryMetadataStore
utils/validator.py          ✅ validate Kafka payload → DLQ nếu fail
utils/mapper.py             ✅ DocumentUploaded → IngestJob
models/ingest_job.py        ✅ IngestJob, ChunkResult, PermissionModel, DocumentRecord
models/events.py            ✅ DocumentUploaded, EmbeddingDone, IndexingFailed
pipeline/01_parse.py        ✅ PDF/DOCX/TXT/HTML/Image (pypdf, python-docx, OCR)
pipeline/02_clean.py        ✅ normalize text
pipeline/03_chunk.py        ✅ sliding window với overlap
pipeline/04_embed.py        ✅ batch embed qua AIProvider
pipeline/05_index.py        ✅ upsert VectorDB + MetadataDB + PermissionStore
pipeline/run.py             ✅ orchestrate 5 bước, trả dict stats
retrieval/service.py        ✅ vector search + permission filter (5 rules)
streaming/kafka_consumer.py ✅ consume → validate → retry 3x → DLQ; manual offset commit
api/main.py                 ✅ POST /ingest, POST /retrieve-context, GET /health
adapters/file_adapter.py    ✅ file_path → IngestJob
adapters/kafka_adapter.py   ✅ raw Kafka event → IngestJob
tests/                      ✅ 17 tests, CI green (pytest + docker-test)
```

---

## Build order — làm đúng thứ tự

```
Day 1:  config/settings.py + models/
Day 2:  utils/ai_provider.py
Day 3:  utils/storage.py + utils/validator.py + utils/mapper.py
Day 4:  pipeline/01_parse.py + pipeline/02_clean.py
Day 5:  pipeline/03_chunk.py
Day 6:  pipeline/04_embed.py  (test với AI_BASE_URL=http://localhost:11434/v1 nếu có Ollama)
Day 7:  utils/stores.py + pipeline/05_index.py  (cần docker-compose up postgres qdrant)
Day 8:  pipeline/run.py + adapters/file_adapter.py → test end-to-end với file thật
        ✅ Checkpoint: pipeline chạy hoàn chỉnh từ file → Vector DB
Day 9:  adapters/kafka_adapter.py + utils/notifier.py + streaming/kafka_consumer.py
Day 10: DLQ + retry logic
Day 11: retrieval/service.py
Day 12: api/main.py
        ✅ Checkpoint: API chạy, test bằng curl/Postman
```

---

## Quy tắc bắt buộc

```
✅ Pipeline chỉ nhận IngestJob, chỉ trả ChunkResult
✅ Mọi tác vụ AI đều qua AIProvider — không import openai trực tiếp trong pipeline/
✅ Mọi store đều qua VectorStore / MetadataStore interface
✅ Model, base_url, api_key chỉ đọc từ config/settings.py
✅ Pipeline idempotent — gọi delete(doc_id) trước khi index
✅ DLQ cho mọi lỗi — không drop event, không raise exception thoát consumer
✅ Retrieval filter permission trước khi trả contexts[]

❌ Không import openai / chromadb / psycopg2 trực tiếp trong pipeline/
❌ Không hardcode URL, model name, credential trong code
❌ Không lưu permission vào Vector DB metadata
```

---

## Cách chạy test nhanh (không cần docker)

Tạo file `.env` (đã có sẵn trong `.gitignore` — không commit):

```env
# AI Provider
AI_PROVIDER=auto
AI_API_KEY=sk-...            # hoặc bỏ trống để dùng MockAIProvider

# Vector Store — chọn 1 trong 2:
VECTOR_STORE=qdrant

# Qdrant Cloud (ưu tiên nếu QDRANT_URL có giá trị)
QDRANT_URL=https://<cluster-id>.us-east-1-1.aws.cloud.qdrant.io
QDRANT_API_KEY=<jwt-key>

# Qdrant local Docker (fallback khi QDRANT_URL trống)
QDRANT_HOST=localhost
QDRANT_PORT=6333

# Metadata Store
METADATA_STORE=memory        # hoặc postgres (cần docker-compose up postgres)
USE_S3=false
```

```bash
# Chạy pipeline với FileAdapter (file local, không cần Kafka)
python -c "
from adapters.file_adapter import FileAdapter
from pipeline.run import run
job = FileAdapter().map('data/sample/policy.txt')
print(run(job))
"

# Chạy toàn bộ test suite
pytest -q
```

---

## Định dạng output mong đợi cuối Day 8

```python
# pipeline/run.py trả về
{
    "doc_id": "abc-123",
    "status": "indexed",
    "chunk_count": 42,
    "embedding_model": "text-embedding-3-small",
    "duration_seconds": 3.2
}
```

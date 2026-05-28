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

Các file sau đã tồn tại, cần **rewrite hoàn toàn** (không giữ logic cũ):

```
config/settings.py          ← rewrite theo overview.md#Config
utils/storage.py            ← rewrite: bỏ PySpark, đọc binary từ S3/local
utils/notifier.py           ← giữ Kafka publish logic, đổi topic names
streaming/kafka_consumer.py ← rewrite: consume DocumentUploaded → validate → run
dags/pipeline_dag.py        ← rewrite: KafkaSensor → pipeline.run()
api/main.py                 ← rewrite: POST /ingest, POST /retrieve-context, GET /health
```

Các file sau **chưa tồn tại**, cần tạo mới:

```
models/ingest_job.py        ← IngestJob, ChunkResult, PermissionModel, DocumentRecord
models/events.py            ← DocumentUploaded event schema
utils/ai_provider.py        ← AIProvider Protocol + OpenAIProvider
utils/stores.py             ← VectorStore, MetadataStore Protocol + implementations
utils/validator.py          ← validate Kafka payload → DLQ nếu fail
utils/mapper.py             ← DocumentUploaded → IngestJob
pipeline/01_parse.py        ← file_uri → raw text (PDF/DOCX/TXT/Image)
pipeline/02_clean.py        ← text → normalized text
pipeline/03_chunk.py        ← text → chunks[] sliding window
pipeline/04_embed.py        ← chunks[] → chunks với embedding (AIProvider)
pipeline/05_index.py        ← chunks[] → VectorDB + MetadataDB + PermissionStore
pipeline/run.py             ← orchestrate 5 bước, nhận IngestJob trả dict stats
retrieval/service.py        ← vector search + permission filter
adapters/file_adapter.py    ← file_path → IngestJob (dùng test local, không cần Kafka)
adapters/kafka_adapter.py   ← raw Kafka event → IngestJob
data/sample/                ← thư mục chứa 3-5 file PDF/DOCX/TXT test
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
Day 7:  utils/stores.py + pipeline/05_index.py  (cần docker-compose up postgres chroma)
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

```bash
# 1. Đặt file test vào data/sample/
# 2. Set env (Ollama local hoặc OpenAI)
export AI_BASE_URL=http://localhost:11434/v1
export AI_API_KEY=ollama
export EMBED_MODEL=nomic-embed-text
export USE_S3=false

# 3. Chạy pipeline với FileAdapter
python -c "
from adapters.file_adapter import FileAdapter
from pipeline.run import run
job = FileAdapter().map('data/sample/test.pdf')
print(run(job))
"
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

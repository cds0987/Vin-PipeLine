# Async Refactor — Thuần Async Pipeline

## Mục tiêu

Chuyển toàn bộ pipeline từ threading-based sang asyncio thuần — không có thread pool ẩn cho I/O, không có `asyncio.to_thread()` wrapper giả async. Chỉ CPU-bound work (parse, normalize) mới dùng `asyncio.to_thread()`.

Kết quả đích: một event loop duy nhất kiểm soát toàn bộ concurrency — scanner, ingest jobs, caption, embed, S3, DB, vector index, và search.

---

## Tại sao làm điều này

### Vấn đề của thiết kế thread hiện tại

Caption 30 sections của một document hiện chạy tuần tự — 30 API calls nối đuôi nhau trong vòng `for`. Mỗi call mất 2–8 giây. Một document có thể mất 90 giây chỉ cho caption.

`_JobDispatcher` dùng `threading.Thread` workers. Mỗi thread trong khi chờ network (S3, AI API, DB) không làm gì nhưng vẫn chiếm ~1MB RAM và OS scheduling overhead. Với nhiều pods và nhiều documents, thread overhead trở nên đáng kể.

`asyncio.to_thread(boto3_call)` — cách wrap boto3 vào async — vẫn dùng thread pool ngầm, không phải async thật. Đây là async nửa vời.

### Lợi ích của async thuần

**Caption song song thật sự:** `asyncio.gather()` + `asyncio.Semaphore` cho phép caption 30 sections đồng thời, giới hạn bởi semaphore để kiểm soát rate limit AI provider.

**Scanner không block pipeline:** Scanner chạy như `asyncio.Task`. Khi `await asyncio.sleep(interval)`, event loop chạy caption, embed, index, search song song — không cần thread riêng cho scanner.

**Scale theo coroutine, không theo thread:** 100 concurrent caption calls với asyncio dùng một thread. Với thread pool cần 100 threads.

**Một event loop, một chỗ kiểm soát concurrency:** Không có nhiều thread racing nhau, không có GIL tranh chấp, debug qua một execution context thống nhất.

---

## Thay đổi thư viện

| Hiện tại | Thay bằng | Lý do |
|---|---|---|
| `boto3` | `aioboto3` | S3 list, read, write thật sự async |
| `sqlalchemy` sync | `sqlalchemy[asyncio]` + `asyncpg` | DB queries không block event loop |
| `openai` sync | `AsyncOpenAI` (cùng package) | AI calls với `asyncio.gather` |
| `qdrant-client` sync | `AsyncQdrantClient` (cùng package) | Vector search không block |

Thêm vào `requirements.txt`:
```
aioboto3
asyncpg
sqlalchemy[asyncio]
```

---

## Kiến trúc đích

```
asyncio event loop (một thread duy nhất)
│
├── scanner task
│   ├── await asyncio.sleep(interval)
│   └── await aioboto3 list S3 objects
│
├── job tasks (asyncio.Semaphore giới hạn concurrent jobs)
│   ├── await aioboto3 read file
│   ├── await asyncio.to_thread(parse)        ← CPU-bound, đúng chỗ
│   ├── await asyncio.to_thread(normalize)    ← CPU-bound, đúng chỗ
│   ├── await aioboto3 write markdown
│   ├── await asyncio.gather(*caption_tasks)  ← song song với Semaphore
│   ├── await AsyncOpenAI embed
│   ├── await AsyncQdrantClient upsert
│   └── await asyncpg update status
│
└── search tasks
    ├── await AsyncOpenAI embed query
    └── await AsyncQdrantClient search
```

Chỉ `parse` và `normalize` là CPU-bound thật sự — hai chỗ duy nhất dùng `asyncio.to_thread()`.

---

## Phạm vi thay đổi theo layer

### Layer 1 — AI Provider

**`utils/ai_provider.py`**

- Thêm `AsyncOpenAIProvider` dùng `AsyncOpenAI` client
- `async def caption(texts)` — dùng `asyncio.gather()` với `asyncio.Semaphore(CAPTION_MAX_CONCURRENCY)`
- `async def embed(texts)` — một batch call async
- `async def ocr(image_bytes)` — async với retry
- `MockAIProvider` thêm async versions tương ứng

Protocol `AIProvider` tách thành `SyncAIProvider` (giữ cho test đơn giản) và `AsyncAIProvider` (production).

Env var mới: `CAPTION_MAX_CONCURRENCY` (default 5) — giới hạn số caption calls đồng thời trên toàn system.

---

### Layer 2 — Ports

**`app/ports/ai.py`**
```python
class CaptionProvider(Protocol):
    async def caption(self, texts: list[str]) -> list[str]: ...

class SectionEmbedder(Protocol):
    async def embed_sections(self, sections: list[SectionRecord]) -> list[SectionRecord]: ...
```

**`app/ports/section_captioner.py`**
```python
class SectionCaptioner(Protocol):
    async def caption_sections(self, sections: list[SectionRecord]) -> list[SectionRecord]: ...
```

**`app/ports/embedding_provider.py`**
```python
class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

---

### Layer 3 — Infrastructure AI

**`app/infrastructure/ai/captioner.py`**

```python
async def caption_sections(self, sections):
    pending = [s for s in sections if not s.caption.strip()]
    captions = await self._ai_provider.caption([s.section_content for s in pending])
    # assign captions back
    return sections
```

Caption song song xảy ra bên trong `ai_provider.caption()` qua `asyncio.gather()` + Semaphore — captioner không cần biết chi tiết này.

**`app/infrastructure/ai/embedder.py`**

```python
async def embed_sections(self, sections, batch_size=32):
    for batch in batches(sections, batch_size):
        embeddings = await self._ai_provider.embed([s.caption for s in batch])
        # assign embeddings
    return sections
```

---

### Layer 4 — Infrastructure I/O

**`app/infrastructure/storage/binary_reader.py`**

```python
async def read(self, uri: str) -> bytes:
    async with aioboto3.Session().client("s3") as s3:
        response = await s3.get_object(Bucket=bucket, Key=key)
        return await response["Body"].read()
```

**`app/infrastructure/storage/markdown_store.py`**

Tương tự — dùng `aioboto3` cho `put_object`.

**`app/infrastructure/scanning/s3_source_scanner.py`**

```python
async def scan(self) -> list[IngestJob]:
    async with aioboto3.Session().client("s3") as s3:
        paginator = s3.get_paginator("list_objects_v2")
        async for page in paginator.paginate(...):
            # process objects
```

**`app/infrastructure/repositories/sql_metadata_store.py`**

Dùng `sqlalchemy.ext.asyncio`:
```python
async with AsyncSession(engine) as session:
    result = await session.execute(select(Document).where(...))
```

Engine tạo bằng `create_async_engine("postgresql+asyncpg://...")`.

**`app/infrastructure/vector/qdrant_store.py`**

```python
from qdrant_client import AsyncQdrantClient

async def search_sections(self, vector, top_k):
    return await self._client.search(collection_name=..., query_vector=vector, limit=top_k)
```

---

### Layer 5 — Application

**`app/application/ingest/run_ingest_job.py`**

```python
async def execute(self, job: IngestJob, deadline_monotonic: float | None = None) -> dict:
    # claim
    claimed = await self._ingest_claim_repository.try_claim_ingest(job)
    if not claimed:
        return {"status": "skipped"}

    file_bytes = await self._binary_reader.read(job.file_uri)

    # CPU-bound → to_thread
    markdown_doc = await asyncio.to_thread(self._parser.parse, job, file_bytes)
    markdown_doc = markdown_doc.model_copy(
        update={"markdown_content": await asyncio.to_thread(self._normalize, markdown_doc.markdown_content)}
    )

    markdown_doc = await self._markdown_store.save(markdown_doc)
    sections = await asyncio.to_thread(self._section_splitter.split, markdown_doc, job)
    sections = await self._section_captioner.caption_sections(sections)
    sections = await self._section_embedder.embed_sections(sections)
    result = await self._index_service.index_sections(sections, job)
    return result
```

**`app/application/search/search_sections.py`**

```python
async def search(self, query: str, top_k: int, request_id: str) -> list[SectionSearchResult]:
    query_vector = await self._embed_query(query)
    raw = await self._section_index.search_sections(query_vector, top_k=top_k * 3)
    return self._map_results(raw, top_k)
```

Query cache giữ nguyên logic, dùng `asyncio.Lock` thay `threading.Lock`.

---

### Layer 6 — API

**`api/main.py`**

Thay `_JobDispatcher` thread-based bằng asyncio-based:

```python
class _JobDispatcher:
    def __init__(self, max_workers: int, queue_capacity: int) -> None:
        self._semaphore = asyncio.Semaphore(max_workers)
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_capacity)
        self._queued: set[str] = set()
        self._running: set[str] = set()
        self._lock = asyncio.Lock()

    async def enqueue_jobs(self, jobs, container) -> int:
        enqueued = 0
        for job in jobs:
            if not await self._track_queued(job.doc_id):
                continue
            try:
                self._queue.put_nowait((job, container))
                asyncio.create_task(self._run_job(job, container))
                enqueued += 1
            except asyncio.QueueFull:
                await self._untrack_queued(job.doc_id)
        return enqueued

    async def _run_job(self, job, container):
        async with self._semaphore:
            await self._mark_running(job.doc_id)
            try:
                await container.run_ingest_job.execute(job)
            except Exception as exc:
                log.error("Pipeline failed doc_id=%s: %s", job.doc_id, exc)
            finally:
                await self._mark_finished(job.doc_id)
```

Scanner trở thành asyncio Task:

```python
async def _scanner_loop(container, dispatcher, stop_event):
    while not stop_event.is_set():
        try:
            await _scan_and_enqueue_once(container, dispatcher)
        except Exception as exc:
            log.error("Scanner error: %s", exc)
        await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS)
```

`lifespan` khởi động scanner bằng `asyncio.create_task()`:

```python
@asynccontextmanager
async def lifespan(app):
    container = await build_container()
    dispatcher = _JobDispatcher(...)
    scanner_task = None

    if settings.USE_S3 and settings.SCAN_INTERVAL_SECONDS > 0:
        scanner_task = asyncio.create_task(_scanner_loop(container, dispatcher, stop_event))

    try:
        yield
    finally:
        stop_event.set()
        if scanner_task:
            await scanner_task
```

Endpoints đổi thành `async def`:

```python
@app.post("/search")
async def search(request: SearchRequest):
    results = await app.state.container.search_sections.search(...)
    return {...}

@app.post("/scan")
async def trigger_scan(request: ScanRequest):
    ...
```

`_scan_lock` đổi thành `asyncio.Lock()`.

---

## Thứ tự implement

Làm từ dưới lên để có thể test từng bước mà không phá luồng hiện tại.

```
Bước 1  utils/ai_provider.py          AsyncOpenAIProvider + async MockAIProvider
Bước 2  app/ports/*                   Cập nhật protocols sang async
Bước 3  app/infrastructure/ai/        captioner + embedder async
Bước 4  app/infrastructure/storage/   binary_reader + markdown_store → aioboto3
Bước 5  app/infrastructure/scanning/  s3_source_scanner → aioboto3
Bước 6  app/infrastructure/vector/    qdrant_store → AsyncQdrantClient
Bước 7  app/infrastructure/repositories/  sql_metadata_store → asyncpg
Bước 8  app/application/ingest/       run_ingest_job async
Bước 9  app/application/search/       search_sections async
Bước 10 app/bootstrap/container.py    build_container async
Bước 11 api/main.py                   _JobDispatcher async + endpoints async
```

Sau mỗi bước chạy `pytest -q` để xác nhận không có regression.

---

## Testing

`MockAIProvider` cần thêm async versions để test không phụ thuộc vào AI API thật:

```python
class MockAIProvider:
    async def caption(self, texts): return [_heuristic_caption(t) for t in texts]
    async def embed(self, texts): return [self._deterministic_vector(t) for t in texts]
    async def ocr(self, image_bytes): return "[mock-ocr]"
```

Tests dùng `pytest-asyncio`:

```python
@pytest.mark.asyncio
async def test_caption_sections_parallel():
    captioner = AISectionCaptioner(MockAIProvider())
    sections = make_sections(30)
    result = await captioner.caption_sections(sections)
    assert all(s.caption for s in result)
```

---

## Env vars mới

| Var | Default | Ý nghĩa |
|---|---|---|
| `CAPTION_MAX_CONCURRENCY` | `5` | Số caption API calls đồng thời tối đa trên toàn system |
| `DATABASE_URL` | — | Đổi format sang `postgresql+asyncpg://...` |

---

## Điều không thay đổi

- Interface `POST /search` và `POST /scan` — contract API giữ nguyên
- Logic business bên trong `run_ingest_job` — chỉ thêm `await`, không đổi sequence
- `PIPELINE.md` schema — không có thay đổi DB schema
- `MockAIProvider` vẫn là provider mặc định cho local dev và test

---

## Rủi ro cần chú ý

**Exception trong asyncio Task bị nuốt im lặng** nếu không có `try/except` bao quanh. Mọi `asyncio.create_task()` phải được wrap hoặc có exception handler rõ ràng.

**aioboto3 session lifecycle** — `aioboto3.Session()` nên được tạo một lần và reuse, không tạo mới mỗi call để tránh overhead kết nối.

**asyncpg connection pool** — `create_async_engine` cần cấu hình `pool_size` và `max_overflow` phù hợp với số concurrent jobs.

**`asyncio.to_thread()` vẫn cần thread pool** — parse và normalize vẫn dùng threads, chỉ là ít hơn và có kiểm soát hơn.

---

## BatchEmbedder — Cross-job Embedding Coalescing

### Vấn đề giải quyết

Không có `BatchEmbedder`, mỗi ingest job gọi `provider.embed()` độc lập:

```
Job A: embed [sA1, sA2, ... sA20]  → 1 API call, 20 sections
Job B: embed [sB1, sB2, ... sB20]  → 1 API call riêng, 20 sections
Job C: embed [sC1, sC2, ... sC20]  → 1 API call riêng, 20 sections
```

GPU xử lý từng batch nhỏ riêng lẻ. `BatchEmbedder` gom sections từ tất cả jobs vào một queue chung rồi flush cùng lúc.

### Hai trigger flush

```
flush khi:
  len(pending) >= EMBED_MAX_BATCH_SIZE   (mặc định 32)
  OR
  thời gian chờ >= EMBED_BATCH_WINDOW_MS (mặc định 80ms)
```

Timeout đảm bảo job không bị treo khi số sections ít hơn `MAX_BATCH_SIZE`.

### Cache theo content hash

```python
key = sha256(section_content)
if key in cache:
    return cache[key]   # không gọi API
```

Lợi ích:
- Re-ingest cùng document → sections đã có hash → bỏ qua embed
- Nhiều documents có section giống nhau (footer, disclaimer) → embed 1 lần

### Env vars

| Var | Default | Ý nghĩa |
|---|---|---|
| `EMBED_BATCH_WINDOW_MS` | `80` | Thời gian chờ tối đa trước khi flush |
| `EMBED_MAX_BATCH_SIZE` | `32` | Flush ngay khi queue đạt size này |
| `EMBED_CACHE_SIZE` | `4096` | Số vector cached tối đa (LRU) |

### Vị trí trong kiến trúc

```
build_container()
└── BatchEmbedder (singleton, shared across all jobs)
    ├── AISectionEmbedder (ingest pipeline)
    └── [SearchSections — future integration]
```

`BatchEmbedder` được tạo một lần trong `build_container()`, dùng chung cho tất cả ingest jobs đồng thời. `api/main.py` lifespan gọi `flush_and_close()` khi shutdown để đảm bảo không có item nào bị mất.

### File tham chiếu

- [utils/batch_embedder.py](../../utils/batch_embedder.py)
- [app/infrastructure/ai/embedder.py](../../app/infrastructure/ai/embedder.py)
- [app/bootstrap/container.py](../../app/bootstrap/container.py)

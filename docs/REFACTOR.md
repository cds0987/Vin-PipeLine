# REFACTOR.md — Hướng dẫn clean architecture cho DE Vector Search Engine

Tài liệu này mô tả chính xác những gì cần sửa, tại sao, và sửa như thế nào.
Mọi issue đều có file + line cụ thể, code trước/sau, và lệnh verify.

Không implement gì ngoài scope từng issue. Không refactor tiện thể.

---

## Nguyên tắc deep module đang áp dụng

Một module **deep** khi:
- Interface nhỏ — ít thứ caller phải biết
- Implementation ẩn — complexity nằm bên trong, không lộ ra ngoài
- Không có side effect ẩn — caller đọc signature hiểu hết

Repo này vi phạm nguyên tắc đó ở 6 chỗ cụ thể. Mỗi chỗ dưới đây là một task độc lập, có thể làm theo bất kỳ thứ tự nào sau khi xong P0.

---

## P0 — Xóa dead code (làm trước, không cần review kiến trúc)

Dead code không gây bug ngay, nhưng nó làm mờ ranh giới "cái gì đang chạy" — đặc biệt nguy hiểm khi onboard người mới hoặc đọc lại sau 3 tháng.

### P0-A: Xóa toàn bộ Kafka artifacts

**Xóa các file sau:**

```
streaming/kafka_consumer.py
adapters/kafka_adapter.py
models/events.py
dags/pipeline_dag.py
tests/streaming/test_kafka_adapter.py
tests/streaming/test_kafka_consumer.py
tests/streaming/__init__.py
tests/streaming/          ← xóa cả folder
```

**Xóa các setting trong `config/settings.py`:**

Xóa các field khỏi class `Settings` (lines 52–60):
```python
# XÓA những dòng này:
kafka_bootstrap: str = "kafka:9092"
topic_ingest: str = "DocumentUploaded"
topic_done: str = "EmbeddingDone"
topic_failed: str = "IndexingFailed"
topic_permission: str = "PermissionUpdated"
topic_dlq: str = "DocumentUploaded.DLQ"
consumer_group_id: str = "de-ingestion-service"
consumer_max_retries: int = 3
```

Xóa các constant export tương ứng (lines 138–144):
```python
# XÓA những dòng này:
KAFKA_BOOTSTRAP = _settings.kafka_bootstrap
TOPIC_INGEST = _settings.topic_ingest
TOPIC_DONE = _settings.topic_done
TOPIC_FAILED = _settings.topic_failed
TOPIC_PERMISSION = _settings.topic_permission
TOPIC_DLQ = _settings.topic_dlq
CONSUMER_GROUP_ID = _settings.consumer_group_id
CONSUMER_MAX_RETRIES = _settings.consumer_max_retries
```

**Verify:**
```powershell
python -m pytest -q --ignore=tests/streaming
grep -r "kafka" . --include="*.py" -l   # kết quả phải rỗng
grep -r "KAFKA" . --include="*.py" -l   # kết quả phải rỗng
```

---

## P1 — Fix Protocol drift (critical — ảnh hưởng type safety toàn bộ pipeline)

### P1-A: Thêm `update_processed()` vào `MetadataStore` Protocol

**Vấn đề:**

`utils/stores.py` định nghĩa `MetadataStore` Protocol (lines 28–59), nhưng method `update_processed()` — được implement ở cả ba class (`SQLMetadataStore:410`, `FileMetadataStore:531`, `InMemoryMetadataStore:628`) — **không có trong Protocol**.

Hậu quả: `pipeline/05_index.py:53` phải dùng `hasattr` check để gọi method này:

```python
# pipeline/05_index.py — hiện tại (sai):
if hasattr(metadata_store, "update_processed"):
    metadata_store.update_processed(job.doc_id, len(chunks), processed_at)
```

`hasattr` trong pipeline core là dấu hiệu "tôi đang đoán interface" — phá vỡ invariant "pipeline chỉ biết 5 interface".

**Sửa `utils/stores.py` — thêm vào Protocol:**

```python
# Trong class MetadataStore(Protocol): — thêm method này vào cuối Protocol
@abstractmethod
def update_processed(
    self,
    doc_id: str,
    total_chunks: int,
    processed_at: datetime,
) -> None: ...
```

**Sửa `pipeline/05_index.py` — bỏ hasattr:**

```python
# TRƯỚC (lines 53–54):
if hasattr(metadata_store, "update_processed"):
    metadata_store.update_processed(job.doc_id, len(chunks), processed_at)

# SAU:
metadata_store.update_processed(job.doc_id, len(chunks), processed_at)
```

**Verify:**
```powershell
python -m pytest tests/pipeline/test_index.py -q
python -m pytest tests/stores/ -q
grep -n "hasattr" pipeline/05_index.py   # kết quả phải rỗng
```

---

### P1-B: Tách IO ra khỏi `pipeline/01_parse.py`

**Vấn đề:**

`pipeline/01_parse.py` import và gọi `read_binary()` từ `utils/storage.py`:

```python
# pipeline/01_parse.py:10 — hiện tại (sai):
from utils.storage import read_binary

# pipeline/01_parse.py:151 — hiện tại (sai):
def run(job: IngestJob, ai_provider: AIProvider) -> list[tuple[int, str]]:
    file_bytes = read_binary(job.file_uri)   # ← IO ở đây
    suffix = Path(job.file_uri).suffix.lower()
    ...
```

Parse stage đang tự đọc file từ S3/local. Đây là infra concern, không phải parse concern. Hậu quả:
- Test parse phải có file thật hoặc mock `read_binary` — không test được thuần logic parse
- Thay đổi nguồn file (ví dụ: thêm GCS) buộc sửa parse stage, không phải adapter

**Sửa `pipeline/01_parse.py` — nhận bytes, bỏ IO:**

```python
# XÓA import này:
from utils.storage import read_binary

# Đổi signature của run():
# TRƯỚC:
def run(job: IngestJob, ai_provider: AIProvider) -> list[tuple[int, str]]:
    file_bytes = read_binary(job.file_uri)
    suffix = Path(job.file_uri).suffix.lower()
    ...

# SAU:
def run(
    job: IngestJob,
    ai_provider: AIProvider,
    file_bytes: bytes,
) -> list[tuple[int, str]]:
    suffix = Path(job.file_uri).suffix.lower()
    ...
```

**Sửa `pipeline/run.py` — đọc bytes trước khi gọi parse:**

```python
# Thêm import ở đầu file:
from utils.storage import read_binary

# Trong hàm run(), trước dòng gọi parse.run():
# TRƯỚC:
pages = parse.run(job, ai)

# SAU:
file_bytes = read_binary(job.file_uri)
pages = parse.run(job, ai, file_bytes)
```

**Kết quả sau sửa:**

```
pipeline/run.py    ← biết file đến từ đâu (vì nó là orchestrator)
    │ bytes
    ▼
pipeline/01_parse  ← chỉ biết "bytes + suffix → pages", không biết S3 hay local
```

**Verify:**
```powershell
python -m pytest tests/pipeline/test_parse_formats.py -q
python -m pytest tests/pipeline/test_parse_ocr.py -q
# Quan trọng: test parse giờ có thể dùng b"..." trực tiếp, không cần file path
```

---

## P2 — Làm sạch interface (quan trọng nhưng không block production)

### P2-A: Typed `file_name` trên `IngestJob`

**Vấn đề:**

`IngestJob.metadata` là `dict` untyped. `file_name` được truyền qua convention string key:

```python
# adapters/s3_adapter.py:120 — viết vào dict:
metadata={"file_name": file_name}

# pipeline/05_index.py:26 — đọc từ dict:
file_name = job.metadata.get("file_name") or Path(job.file_uri).name

# utils/stores.py:363 — đọc từ dict:
file_name=job.metadata.get("file_name"),
```

Ba chỗ dùng cùng một string key `"file_name"` — không có gì ngăn typo, không có type check, không có IDE autocomplete.

**Sửa `models/ingest_job.py`:**

```python
# TRƯỚC:
class IngestJob(BaseModel):
    doc_id: str
    file_uri: str
    language: str = "vi"
    document_type: str = "general"
    s3_last_modified: datetime | None = None
    metadata: dict = Field(default_factory=dict)

# SAU:
class IngestJob(BaseModel):
    doc_id: str
    file_uri: str
    language: str = "vi"
    document_type: str = "general"
    s3_last_modified: datetime | None = None
    file_name: str | None = None
    metadata: dict = Field(default_factory=dict)
```

**Sửa các caller:**

`adapters/s3_adapter.py` — 2 chỗ tạo IngestJob:
```python
# TRƯỚC:
IngestJob(..., metadata={"file_name": file_name})

# SAU:
IngestJob(..., file_name=file_name)
```

`pipeline/05_index.py:26`:
```python
# TRƯỚC:
file_name = job.metadata.get("file_name") or Path(job.file_uri).name

# SAU:
file_name = job.file_name or Path(job.file_uri).name
```

`utils/stores.py` — `SQLMetadataStore.try_claim_ingest()` và `FileMetadataStore.try_claim_ingest()`, `InMemoryMetadataStore.try_claim_ingest()`:
```python
# TRƯỚC (mỗi implementation):
file_name=job.metadata.get("file_name"),

# SAU:
file_name=job.file_name,
```

> `metadata: dict` vẫn giữ lại — nó là extension point cho data tùy ý từ adapter. Chỉ promote `file_name` ra typed field vì nó được đọc ở nhiều chỗ trong core.

**Verify:**
```powershell
python -m pytest -q
grep -n 'metadata.get("file_name")' pipeline/ utils/ adapters/   # kết quả phải rỗng
```

---

### P2-B: Fix `_scan_lock` release trong `api/main.py`

**Vấn đề:**

`/scan` endpoint có pattern release lock bị duplicate và error-prone (lines 168–182):

```python
# api/main.py:168–182 — hiện tại:
if not _scan_lock.acquire(blocking=False):
    raise HTTPException(status_code=409, detail="scan already in progress")

try:
    jobs = S3Scanner(app.state.metadata_store).scan(...)
except Exception:
    _scan_lock.release()
    raise
finally:
    if _scan_lock.locked():    # ← check này sai: locked() = True ngay cả khi
        _scan_lock.release()   #   thread khác giữ lock, không phải thread này
```

`threading.Lock.locked()` trả về `True` nếu **bất kỳ ai** đang giữ lock, không phân biệt thread hiện tại. Pattern này release lock 2 lần nếu exception xảy ra.

**Sửa `api/main.py`:**

```python
# SAU — dùng context manager, không cần track thủ công:
if not _scan_lock.acquire(blocking=False):
    raise HTTPException(status_code=409, detail="scan already in progress")

try:
    jobs = S3Scanner(app.state.metadata_store).scan(
        bucket=request.bucket,
        prefix=request.prefix,
    )
finally:
    _scan_lock.release()
```

`_scan_and_run_once()` dùng `acquire/release` trực tiếp với try/finally đúng — không cần sửa.

**Verify:**
```powershell
python -m pytest tests/api/test_scan_coordination.py -q
```

---

### P2-C: Bỏ lazy import `S3Scanner` trong function body

**Vấn đề:**

`S3Scanner` được import lazy bên trong 2 function trong `api/main.py`:

```python
# api/main.py:93:
def _scan_and_run_once(...):
    from adapters.s3_adapter import S3Scanner   # ← lazy

# api/main.py:168:
def trigger_scan(...):
    from adapters.s3_adapter import S3Scanner   # ← lazy, duplicate
```

Lazy import không có lý do ở đây (không phải optional dependency, không phải circular import). Nó ẩn dependency thật của module, làm khó đọc.

**Sửa `api/main.py` — move lên đầu file:**

```python
# Thêm vào block import ở đầu file (sau các import hiện tại):
from adapters.s3_adapter import S3Scanner

# Xóa 2 dòng `from adapters.s3_adapter import S3Scanner` bên trong function body.
```

**Verify:**
```powershell
python -c "from api.main import app"   # phải không có lỗi
grep -n "from adapters.s3_adapter" api/main.py   # chỉ 1 dòng, ở đầu file
```

---

## P3 — Cải thiện robustness (không urgent, làm khi có thời gian)

### P3-A: Bỏ global mutable warning state

**Vấn đề:**

Ba module dùng global variable để truyền warning ra ngoài:

```python
# utils/ai_provider.py:
LAST_AI_PROVIDER_BUILD_WARNING: str | None = None
def build_ai_provider() -> AIProvider:
    global LAST_AI_PROVIDER_BUILD_WARNING
    ...

# utils/stores.py:
LAST_VECTOR_STORE_BUILD_WARNING: str | None = None
LAST_METADATA_STORE_BUILD_WARNING: str | None = None
```

Pattern này không thread-safe nếu `build_*` được gọi concurrently (hiện tại chỉ gọi một lần lúc startup — nhưng sẽ không rõ ràng cho người đọc sau). Ngoài ra, caller phải nhớ gọi `get_last_*_warning()` ngay sau `build_*()` — coupling ngầm theo thứ tự call.

**Hướng sửa — trả warning kèm object:**

```python
# Thay vì:
provider = build_ai_provider()
warning = get_last_ai_provider_build_warning()

# Trả về tuple:
def build_ai_provider() -> tuple[AIProvider, str | None]:
    ...
    return provider, warning_or_none

# Caller:
provider, warning = build_ai_provider()
```

Áp dụng tương tự cho `build_vector_store()` và `build_metadata_store()`.

Cập nhật `api/main.py` lifespan để unpack tuple thay vì gọi `get_last_*_warning()`.

> Đây là breaking change nhỏ — chỉ ảnh hưởng `api/main.py`. Làm khi cần, không urgent.

---

### P3-B: Xóa Kafka settings khỏi `.env.example`

Sau khi xong P0-A, kiểm tra `.env.example`:

```powershell
grep -n "KAFKA\|TOPIC_\|CONSUMER_" .env.example
```

Xóa các dòng tương ứng để `.env.example` không gây nhầm lẫn cho dev mới.

---

## Thứ tự thực hiện — đã hoàn thành

```
P0-A ✓  P1-A ✓  P1-B ✓  P2-A ✓  P2-B ✓  P2-C ✓  P3-A ✓  P3-B ✓
(xóa)   (proto)  (IO)    (type)   (lock)   (import) (global) (env)
```

```powershell
# Full test suite:
.\tasks.ps1 test
```

---

## Checklist — đã hoàn thành (verified 2026-05-29)

- [x] `grep -rn "kafka" . --include="*.py"` → rỗng
- [x] `grep -rn "hasattr.*metadata_store" . --include="*.py"` → rỗng
- [x] `grep -n "read_binary" pipeline/01_parse.py` → rỗng (`run.py` giữ IO như thiết kế P1-B)
- [x] `grep -rn 'metadata.get("file_name")' . --include="*.py"` → rỗng
- [x] `grep -n "from adapters.s3_adapter" api/main.py` → chỉ 1 dòng ở đầu file
- [x] `docker compose run --rm test` → 188 passed, 0 failed
- [x] `pipeline/01_parse.py` đến `05_index.py` không import `boto3`, `psycopg2`, `qdrant_client`, `storage`

---

## Những gì KHÔNG làm trong đợt refactor này

- Không thêm tính năng mới
- Không đổi chunking strategy
- Không đổi API response format
- Không di chuyển `utils/stores.py` thành nhiều file
- Không thêm abstract base class hay thêm layer trừu tượng nào mới
- Không sửa `pipeline/02_clean.py`, `pipeline/03_chunk.py`, `pipeline/04_embed.py` — các module này đã deep, không cần đụng

Mục tiêu duy nhất: làm cho interface hiện tại nói thật về những gì nó làm.

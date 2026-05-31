# BatchEmbedder — Thiết kế, Rủi ro, và Bài học

## Mục đích

Trước khi có `BatchEmbedder`, mỗi ingest job gọi embedding API độc lập:

```
Job A (20 sections) → provider.embed([s1..s20])  → 1 API call
Job B (20 sections) → provider.embed([s1..s20])  → 1 API call riêng
Job C (20 sections) → provider.embed([s1..s20])  → 1 API call riêng
```

`BatchEmbedder` là một queue dùng chung cho tất cả jobs đang chạy đồng thời. Sections từ nhiều jobs được gom lại và embed trong một lần gọi API:

```
Job A section 1  ─┐
Job A section 2  ─┤
Job B section 1  ─┼─→ provider.embed([...32 sections...]) → 1 API call
Job B section 2  ─┤
Job C section 1  ─┘
```

Ngoài ra có LRU cache theo content hash — nếu section đã được embed trước đó (re-ingest, nội dung trùng), bỏ qua hoàn toàn.

---

## Cơ chế hoạt động

### Hai trigger flush

```
flush khi:
  len(pending) >= EMBED_MAX_BATCH_SIZE   → flush ngay, không chờ
  OR
  đã chờ >= EMBED_BATCH_WINDOW_MS        → flush dù chưa đủ batch
```

Timeout bắt buộc để tránh job bị treo khi có ít sections hơn `MAX_BATCH_SIZE`.

### Flow chi tiết

```
embed_one(text)
  ├── cache hit?   → return cached vector ngay
  └── cache miss   → tạo Future, thêm vào pending queue
                    ├── queue đầy (>= MAX_BATCH_SIZE)  → flush ngay
                    └── chưa đầy                        → tạo delayed_flush task
                                                           (ngủ WINDOW_MS rồi flush)
                    → await Future (chờ kết quả)

_flush()
  → gom tất cả pending vào một batch
  → asyncio.to_thread(provider.embed, texts)
  → set_result() cho từng Future
  → lưu vào cache
```

### Singleton pattern

`BatchEmbedder` được tạo một lần trong `build_container()` và dùng chung cho tất cả `AISectionEmbedder` instances. Điều này là bắt buộc — nếu mỗi job tạo `BatchEmbedder` riêng, sẽ không có cross-job batching.

---

## Cấu hình

| Env var | Default | Production nên đặt |
|---|---|---|
| `EMBED_BATCH_WINDOW_MS` | `5` | `50`–`100` |
| `EMBED_MAX_BATCH_SIZE` | `32` | `32`–`64` |
| `EMBED_CACHE_SIZE` | `4096` | Tăng nếu RAM dư |

**Lý do default `5ms` thay vì `80ms`:** Tests cần chạy nhanh. Production override qua env var. Xem phần Risk 1 bên dưới.

---

## Rủi ro và Bài học cho đội dev

### Risk 1 — Self-cancellation bug (đã gặp, đã fix)

**Vấn đề:**

`_flush()` chứa đoạn code hủy `_flush_task`:

```python
# CODE CŨ — SAI
if self._flush_task and not self._flush_task.done():
    self._flush_task.cancel()
self._flush_task = None
```

Khi `_flush()` được gọi từ BÊN TRONG `_delayed_flush` task (flush theo timeout), `self._flush_task` chính là task đang chạy. Gọi `self._flush_task.cancel()` tức là task đang tự hủy chính nó.

`cancel()` không raise exception ngay — nó schedule `CancelledError` tại `await` tiếp theo. `await` tiếp theo trong `_flush()` là `await asyncio.to_thread(...)`. Tại đó `CancelledError` được throw vào. Vì `CancelledError` là `BaseException` (không phải `Exception`), `except Exception` không bắt được. Exception lan ra ngoài. Tất cả Futures không bao giờ được set. Các coroutine đang `await future` treo mãi mãi.

**Fix:**

```python
# CODE ĐÚNG
current = asyncio.current_task()
if (
    self._flush_task
    and self._flush_task is not current   # ← không tự cancel chính mình
    and not self._flush_task.done()
):
    self._flush_task.cancel()
self._flush_task = None
```

**Bài học:** Trong asyncio, task có thể tự cancel chính mình qua reference gián tiếp. Luôn kiểm tra `asyncio.current_task() is not target` trước khi cancel bất kỳ task nào từ bên trong một task khác có thể là cùng object.

---

### Risk 2 — asyncio primitives tạo ngoài event loop

`BatchEmbedder.__init__()` được gọi từ `build_container()` — một hàm sync, có thể chạy trước khi event loop tồn tại. `asyncio.Lock()` trong `__init__` sẽ lỗi ở Python 3.10+ nếu không có running loop.

**Fix đã áp dụng:** Lock được khởi tạo lazy — chỉ tạo khi `embed_one()` được gọi lần đầu (từ trong async context):

```python
def _get_lock(self) -> asyncio.Lock:
    if self._lock is None:
        self._lock = asyncio.Lock()   # tạo trong running loop
    return self._lock
```

**Bài học:** Không tạo `asyncio.Lock`, `asyncio.Semaphore`, `asyncio.Queue`, `asyncio.Event` trong `__init__` nếu object có thể được khởi tạo ngoài event loop. Dùng lazy init hoặc `asyncio.run()` wrapper.

---

### Risk 3 — CancelledError không phải Exception

Python phân biệt hai hierarchy:

```
BaseException
├── Exception        ← except Exception bắt được
│   ├── ValueError
│   ├── RuntimeError
│   └── ...
└── CancelledError   ← except Exception KHÔNG bắt được
    (từ Python 3.8+, CancelledError là BaseException trực tiếp)
```

Trong bất kỳ async code nào xử lý cleanup hoặc error propagation, phải dùng `except BaseException` hoặc xử lý `CancelledError` riêng nếu muốn bắt tất cả.

**Pattern đúng khi set exception cho Futures:**

```python
try:
    result = await some_async_call()
    future.set_result(result)
except BaseException as exc:        # ← BaseException, không phải Exception
    if not future.done():
        future.set_exception(exc)
    raise                           # ← re-raise CancelledError để asyncio xử lý đúng
```

---

### Risk 4 — Futures không được set → coroutine treo vĩnh viễn

Nếu bất kỳ code path nào trong `_flush()` exit mà không set tất cả Futures (cả `set_result` và `set_exception`), tất cả coroutine đang `await future` sẽ treo vĩnh viễn và không có timeout.

`asyncio.run()` sẽ không thoát ra được. Pytest sẽ treo test. Không có traceback rõ ràng — chỉ thấy test không hoàn thành.

**Bài học:** Bất kỳ hàm nào tạo `asyncio.Future` và trả nó cho caller phải đảm bảo: **mọi code path đều set kết quả cho Future**, kể cả exception paths và cancellation paths.

Pattern defensive:

```python
futures = [...]
try:
    ...
    for future in futures:
        future.set_result(value)
except BaseException as exc:
    for future in futures:
        if not future.done():       # ← kiểm tra .done() trước khi set
            future.set_exception(exc)
    raise
```

---

### Risk 5 — Window mặc định ảnh hưởng tốc độ test

`EMBED_BATCH_WINDOW_MS` mặc định được đặt ở `5ms` thay vì `80ms`. Lý do: mỗi `asyncio.run()` trong test phải chờ hết window trước khi flush. Với `80ms` và 15 test cases, tổng thêm `1.2 giây` chờ không cần thiết.

**Giải pháp đã áp dụng:**
1. Default thấp (`5ms`) — production override qua env var
2. `autouse=True` fixture trong `tests/conftest.py` giảm xuống `1ms`

```python
@pytest.fixture(autouse=True)
def _fast_embed_batch(monkeypatch):
    monkeypatch.setattr("config.settings.EMBED_BATCH_WINDOW_MS", 1)
```

**Bài học:** Bất kỳ setting nào liên quan đến timing (sleep, timeout, window) cần có cơ chế override cho test environment. Dùng autouse fixture để không cần thêm vào từng test.

---

### Risk 6 — Batch size ảnh hưởng latency ingest

`EMBED_MAX_BATCH_SIZE` càng lớn, GPU càng efficient nhưng job phải chờ nhiều sections hơn trước khi flush. Nếu document chỉ có 5 sections, batch size 64 không giúp gì — vẫn phải chờ timeout.

**Nguyên tắc:**
- `EMBED_BATCH_WINDOW_MS` kiểm soát latency tối đa
- `EMBED_MAX_BATCH_SIZE` kiểm soát throughput
- Hai tham số này không thể cùng tối ưu được — luôn có tradeoff

---

### Risk 7 — Cache không persist qua restart

`BatchEmbedder` cache sống trong RAM. Khi pod restart hoặc deploy mới, cache mất hoàn toàn. Re-ingest cùng document sau restart sẽ embed lại từ đầu.

Nếu muốn cache persist: cần tích hợp Redis hoặc lưu embedding vào DB kèm `content_hash`. Đây là bước tiếp theo nếu volume re-ingest lớn.

---

### Risk 8 — flush_and_close() trong shutdown phải được gọi

`api/main.py` lifespan gọi `await container.batch_embedder.flush_and_close()` trước khi shutdown. Nếu bỏ bước này, các sections đang pending trong queue sẽ bị mất — job ingest coi như thành công nhưng embedding không được lưu.

```python
finally:
    scanner_stop.set()
    ...
    await container.batch_embedder.flush_and_close()   # ← bắt buộc
    await dispatcher.stop()
```

**Bài học:** Bất kỳ component nào có internal state cần được drained khi shutdown đều phải có `close()`/`shutdown()` method, và lifespan phải gọi nó theo thứ tự đúng (drain trước khi stop workers).

---

## Checklist trước khi thay đổi BatchEmbedder

- [ ] Mọi code path trong `_flush()` đều set kết quả cho tất cả Futures?
- [ ] Không có chỗ nào cancel `asyncio.current_task()` gián tiếp?
- [ ] `CancelledError` được re-raise sau khi cleanup?
- [ ] Autouse fixture trong tests đang giới hạn `EMBED_BATCH_WINDOW_MS`?
- [ ] `flush_and_close()` vẫn được gọi trong lifespan finally?
- [ ] `BatchEmbedder` vẫn là singleton trong `Container`?

---

---

## Logging và Observability

### Log levels

| Level | Khi nào |
|---|---|
| `INFO` | Khởi tạo, flush_start, flush_done, flush_and_close lifecycle |
| `WARNING` | Future đã done trước khi set (cancelled caller), CancelledError trên flush |
| `ERROR` | Provider exception, size mismatch, futures bị orphan |
| `DEBUG` | Cache hit/miss, enqueue, eviction, timer scheduling — verbose, tắt ở production |

### Log fields quan trọng

**flush_start / flush_done:**
```
BatchEmbedder flush_start flush_id=a1b2c3d4 trigger=timeout batch_size=18 flush_count=5
BatchEmbedder flush_done  flush_id=a1b2c3d4 trigger=timeout batch_size=18 resolved=18 duration_ms=212 cache_size=156
```

- `flush_id` — ID ngẫu nhiên mỗi flush, dùng để correlate start/done/error trong log
- `trigger` — `size_limit` (batch đầy), `timeout` (window hết), `shutdown` (flush_and_close)
- `resolved` — số futures được set thành công
- `duration_ms` — thời gian provider.embed() mất

**flush_error:**
```
BatchEmbedder flush_error flush_id=a1b2c3d4 trigger=timeout error_type=RateLimitError error=... duration_ms=3001 — setting exception on 18 futures
```

Khi thấy log này: 18 ingest sections bị fail. Job sẽ raise exception, được đánh dấu `failed` trong DB.

**size_mismatch:**
```
BatchEmbedder size_mismatch flush_id=a1b2c3d4 expected=18 got=1 provider=OpenAIProvider — setting exception on 18 futures
```

Provider trả về ít embedding hơn số texts gửi đi. Thường do bug ở provider wrapper hoặc provider API thay đổi format.

**flush_cancelled:**
```
BatchEmbedder flush_cancelled flush_id=a1b2c3d4 duration_ms=0 pending_futures=18 — setting CancelledError on all futures
```

Task bị cancel trong khi flush đang chờ provider. Thường xảy ra khi shutdown bất ngờ. Futures được set `CancelledError` để caller không treo.

**future already done:**
```
BatchEmbedder future already done flush_id=a1b2c3d4 key=a1b2c3d4 — likely cancelled by caller
```

Caller đã cancel trước khi flush kịp set result. Không nguy hiểm nhưng đáng chú ý nếu xuất hiện nhiều.

### stats() endpoint

`container.batch_embedder.stats()` trả về:

```json
{
  "total_requests": 1240,
  "cache_hits": 87,
  "cache_hit_rate": 0.07,
  "cache_size": 412,
  "flush_count": 43,
  "provider_errors": 0,
  "futures_orphaned": 0,
  "pending": 0
}
```

Nên expose qua `/health` hoặc `/metrics` trong production để monitor:
- `provider_errors > 0` → AI provider đang lỗi
- `futures_orphaned > 0` → có items bị mất, cần điều tra
- `cache_hit_rate` thấp → cache size quá nhỏ hoặc content đa dạng cao

### Cách đọc log khi điều tra vấn đề

**Scenario 1: Job ingest bị stuck, không kết thúc**

Tìm `embed_one enqueued` nhưng không có `embed_one resolved` tương ứng.
→ Có thể flush chưa fire hoặc future không được set.
→ Kiểm tra có `flush_start` / `flush_done` cùng `flush_id` không.

**Scenario 2: Embedding lỗi nhưng không rõ nguyên nhân**

Tìm `flush_error` với `flush_id` → lấy `error_type` và `error` message.
→ Kiểm tra `provider_errors` tăng dần → provider đang có vấn đề.

**Scenario 3: Cache không hoạt động như mong đợi**

So sánh `cache_hit_rate` với lý thuyết.
→ Nếu thấp hơn nhiều: nội dung section bị thay đổi nhỏ giữa các lần ingest (whitespace, encoding khác nhau) làm hash khác. Cần normalize trước khi hash.

---

## File tham chiếu

| File | Vai trò |
|---|---|
| [utils/batch_embedder.py](../../utils/batch_embedder.py) | Implementation |
| [app/infrastructure/ai/embedder.py](../../app/infrastructure/ai/embedder.py) | Caller trong ingest pipeline |
| [app/bootstrap/container.py](../../app/bootstrap/container.py) | Singleton creation |
| [api/main.py](../../api/main.py) | Lifespan flush_and_close() |
| [tests/conftest.py](../../tests/conftest.py) | Autouse fixture 1ms window |
| [docs/ASYNC_REFACTOR.md](./ASYNC_REFACTOR.md) | Bức tranh toàn cảnh async pipeline |

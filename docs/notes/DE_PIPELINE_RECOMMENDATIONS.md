# DE Pipeline — Recommendations & Known Issues

Tài liệu này tổng hợp các vấn đề đã phân tích và hướng cải thiện được đề xuất cho pipeline hiện tại.

---

## 1. Scope và định vị

Repo này là **DE pipeline** phục vụ data ingestion và context retrieval — không phải AI chatbot service.

- Hai luồng duy nhất: **S3 scan → ingest** (vào) và **`POST /search`** (ra)
- Caption và embedding là transformation steps trong ETL, không phải AI service logic
- `/search` trả raw sections — access control, filtering, LLM reasoning là trách nhiệm của caller
- Consumer trực tiếp: BE team hoặc AI chatbot team ở tầng trên

---

## 2. Vấn đề đã xác định

### 2.1 Caption tuần tự trong critical path

**Vị trí:** [utils/ai_provider.py:64](../../utils/ai_provider.py) — `OpenAIProvider.caption()`

```python
for text in texts:
    response = self._client.chat.completions.create(...)  # 1 call / section, nối tiếp
```

**Vấn đề:**
- Document 30 sections = 30 LLM calls nối tiếp nhau
- Không có retry/backoff — LLM rate limit giữa chừng → cả job fail
- Không có caching — re-index cùng document gọi lại toàn bộ caption dù content không đổi

**So sánh:** embedding đã có retry + backoff ([utils/ai_provider.py:54](../../utils/ai_provider.py)), caption chưa có.

---

### 2.2 Section size không có ceiling

**Vị trí:** [app/infrastructure/sectioning/heading_splitter.py](../../app/infrastructure/sectioning/heading_splitter.py)

Nếu tài liệu không có heading rõ ràng hoặc có section rất dài, toàn bộ nội dung đó trả về trong một section. Caller (LLM tầng trên) nhận context vượt context window mà không có cảnh báo.

---

### 2.3 S3 scanner không scale tốt với high-frequency upload

**Vị trí:** [app/infrastructure/scanning/s3_source_scanner.py](../../app/infrastructure/scanning/s3_source_scanner.py)

- Scan interval cố định → latency tối đa = scan interval
- ListObjects toàn bucket mỗi lần scan → tốn API call khi bucket lớn
- Với 6000 nhân viên và tài liệu cập nhật nhiều, đây là bottleneck thực tế

---

### 2.4 `/search` không có filter params

`POST /search` hiện chỉ nhận `query` và `top_k`. Caller không thể giới hạn search theo `document_type`, `language`, hoặc danh sách `doc_id` cụ thể — phải nhận toàn bộ kết quả rồi tự filter phía trên.

---

### 2.5 Schema gap với DA08-VSF

Nếu repo này phục vụ VSF RAG Service:

| VSF expects | Repo trả về | Ghi chú |
|---|---|---|
| `page_number` | `heading_path` | VSF citation dùng page number để highlight |
| `POST /ingest` HTTP endpoint | S3 scanner trigger | VSF Chat Service gọi HTTP push |

Access control (`classification`, `allowed_departments`) đã được quyết định **không implement** ở tầng này — giao BE team xử lý. Đây là quyết định đúng với scope DE.

---

## 3. Hướng cải thiện

### 3.1 Caption: retry + backoff (ưu tiên cao, effort thấp)

Thêm retry logic tương tự embed:

```python
def caption(self, texts: list[str]) -> list[str]:
    attempts = max(1, settings.CAPTION_MAX_RETRIES)
    for attempt in range(1, attempts + 1):
        try:
            ...
        except Exception:
            if attempt == attempts:
                raise
            time.sleep(settings.CAPTION_RETRY_BACKOFF_SECONDS * attempt)
```

---

### 3.2 Caption: caching theo content hash (ưu tiên cao, effort thấp)

Section content không đổi → không gọi lại LLM:

```python
cache_key = hashlib.md5(section_content.encode()).hexdigest()
if cached := cache.get(cache_key):
    return cached
caption = call_llm(section_content)
cache.set(cache_key, caption)
```

Cache có thể là in-memory (đủ cho single process) hoặc Redis (nếu cần persist giữa các runs).

---

### 3.3 Caption: concurrent batch thay vì sequential loop (ưu tiên trung bình)

```python
import asyncio

async def caption_sections_async(sections):
    tasks = [call_llm_async(s.content) for s in sections]
    captions = await asyncio.gather(*tasks, return_exceptions=True)
    # handle exceptions per-section, không fail toàn job
```

Giảm wall-clock time từ `N * latency_per_call` xuống gần bằng `max(latency_per_call)`.

---

### 3.4 Section max length guard (ưu tiên trung bình, effort thấp)

Trong splitter: nếu section vượt ngưỡng token, split tiếp theo paragraph:

```python
MAX_SECTION_TOKENS = 2000  # configurable

if token_count(section.content) > MAX_SECTION_TOKENS:
    subsections = split_by_paragraph(section)
    yield from subsections
else:
    yield section
```

---

### 3.5 Optional filter trong `/search` (ưu tiên trung bình, effort thấp)

```python
class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    filters: SearchFilters | None = None

class SearchFilters(BaseModel):
    document_type: str | None = None
    language: str | None = None
    doc_ids: list[str] | None = None
```

BE team truyền filter xuống khi cần giới hạn scope — repo không cần biết business rule, chỉ enforce filter.

---

### 3.6 S3 scanner: giảm ListObjects cost (ưu tiên thấp nếu corpus nhỏ)

Thay vì list toàn bucket, scan theo prefix + modified-since marker:

```python
response = s3.list_objects_v2(
    Bucket=bucket,
    Prefix=prefix,
    # dùng timestamp lần scan trước làm lower bound
)
```

Nếu scale lớn hơn: S3 Event Notification → write event vào DB/file. Scanner đọc event log thay vì ListObjects. Không cần SQS, không cần BE, vẫn độc lập hoàn toàn.

---

## 4. Quyết định đã chốt

| Quyết định | Lý do |
|---|---|
| Không implement access control trong pipeline | DE pipeline single-tenant, filter giao BE team |
| Giữ S3 scanner thay vì HTTP trigger | DE độc lập, không phụ thuộc BE bắt đầu trước |
| Caption/embed là DE responsibility | Chỉ là transformation tools, không phải AI service logic |
| Section-based retrieval thay vì chunk | Context trả về hoàn chỉnh, vocabulary mismatch giải quyết tại indexing time |

---

## 5. Thứ tự ưu tiên thực hiện

| # | Cải thiện | Effort | Impact |
|---|---|---|---|
| 1 | Caption retry + backoff | Thấp | Reliability tăng ngay |
| 2 | Caption caching theo hash | Thấp | Giảm cost khi reprocess |
| 3 | Optional filter trong `/search` | Thấp | BE team dùng được ngay |
| 4 | Section max length guard | Thấp | Caller không bị surprise |
| 5 | Caption concurrent batch | Trung bình | Throughput tăng đáng kể |
| 6 | Scanner dùng event log | Trung bình | Latency + ListObjects cost giảm |

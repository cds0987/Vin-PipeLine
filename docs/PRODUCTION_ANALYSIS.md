# Production Analysis — Vin-PipeLine

> **Mục đích:** Phân tích toàn diện các vấn đề kỹ thuật, rủi ro vận hành, và giới hạn kiến trúc khi hệ thống scale từ vài chục đến hàng triệu tài liệu trong môi trường production thực tế.

---

## Mục lục

1. [Tổng quan rủi ro theo mức độ](#1-tổng-quan-rủi-ro-theo-mức-độ)
2. [Pipeline Stage — Phân tích từng bước](#2-pipeline-stage--phân-tích-từng-bước)
3. [Vấn đề Atomicity & Data Consistency](#3-vấn-đề-atomicity--data-consistency)
4. [Concurrency & Race Conditions](#4-concurrency--race-conditions)
5. [Memory & Resource Leaks](#5-memory--resource-leaks)
6. [Failure Scenarios thực tế](#6-failure-scenarios-thực-tế)
7. [Kafka Consumer — At-Least-Once Edge Cases](#7-kafka-consumer--at-least-once-edge-cases)
8. [S3 Scanner — Race & Drift Issues](#8-s3-scanner--race--drift-issues)
9. [Database — Performance & Schema Issues](#9-database--performance--schema-issues)
10. [Vector Store — Qdrant Risks](#10-vector-store--qdrant-risks)
11. [AI Provider — Cost, Rate Limit, Quality Degradation](#11-ai-provider--cost-rate-limit-quality-degradation)
12. [API Layer — Security & Reliability](#12-api-layer--security--reliability)
13. [Observability Gap](#13-observability-gap)
14. [Configuration Drift & Embedding Model Migration](#14-configuration-drift--embedding-model-migration)
15. [Cascade Failure Chains](#15-cascade-failure-chains)
16. [Khuyến nghị ưu tiên](#16-khuyến-nghị-ưu-tiên)

---

## 1. Tổng quan rủi ro theo mức độ

| Mức độ | Vấn đề | Component | Khi nào xảy ra |
|--------|--------|-----------|----------------|
| 🔴 Critical | Atomicity gap: Qdrant delete → upsert không atomic | `05_index.py` | Mọi lúc |
| 🔴 Critical | Document stuck "indexing" vĩnh viễn sau crash | `05_index.py` + process kill | Crash / OOM |
| 🔴 Critical | OOM: read toàn bộ file bytes vào RAM | `utils/storage.py` | File > 200MB |
| 🔴 Critical | `ingestion_jobs` table tăng không giới hạn | `db/schema.py` | Scale > 1M docs |
| 🟠 High | Không retry khi OpenAI rate limit (429) | `04_embed.py` | Peak load |
| 🟠 High | Scanner lock bị giữ suốt quá trình index | `api/main.py` | Scan lớn |
| 🟠 High | SQLAlchemy pool exhaustion | `utils/stores.py` | Concurrent workers |
| 🟠 High | tiktoken fallback word-split không được phát hiện | `03_chunk.py` | Env thiếu thư viện |
| 🟡 Medium | Clock skew S3 last_modified comparison | `adapters/s3_adapter.py` | Multi-region |
| 🟡 Medium | Kafka offset commit sau process → duplicate index | `streaming/kafka_consumer.py` | Consumer restart |
| 🟡 Medium | Embedding model dimension mismatch | `config/settings.py` | Model upgrade |
| 🟡 Medium | DLQ disk full trong môi trường không có Kafka | `utils/storage.py` | Long outage |
| 🟢 Low | UUID5 namespace semantically sai (NAMESPACE_DNS) | `utils/stores.py` | Cosmetic |
| 🟢 Low | Airflow DAG dùng hardcoded doc_id | `dags/pipeline_dag.py` | Re-run issues |

---

## 1.1 Bottleneck Report — Điểm nghẽn vận hành hiện tại

Phần dưới đây tập trung vào **điểm nghẽn hiệu năng và throughput thực tế** của hệ thống hiện tại, khác với phần risk analysis ở chỗ nó trả lời câu hỏi:

- Hệ thống sẽ nghẽn đầu tiên ở đâu khi load tăng?
- Thành phần nào đang giới hạn throughput toàn hệ thống?
- Thành phần nào làm chi phí tăng nhanh nhất khi scale?

### Xếp hạng bottleneck hiện tại

| Rank | Bottleneck | Thành phần | Dạng nghẽn | Tác động chính |
|------|------------|------------|------------|----------------|
| 1 | OCR scan PDF tuần tự theo trang | `pipeline/01_parse.py` + `AIProvider.ocr()` | Latency + Cost + API throughput | File scan lớn rất chậm, chi phí OCR tăng mạnh |
| 2 | Scanner duyệt full bucket + lookup metadata từng file | `adapters/s3_adapter.py` | I/O + DB round-trips | Scan time tăng tuyến tính theo số object |
| 3 | Global scan lock giữ suốt cả scan + ingest batch | `api/main.py` | Coordination / head-of-line blocking | Một batch chậm chặn mọi scan khác |
| 4 | Re-index luôn rewrite toàn bộ vectors + chunks | `05_index.py` + `utils/stores.py` | Write amplification | Re-ingest tốn Qdrant + PostgreSQL I/O |
| 5 | Query embedding đồng bộ cho mọi `/search` | `retrieval/service.py` | Online latency | Search latency phụ thuộc trực tiếp AI API |
| 6 | Embed stage thiếu retry/backpressure/rate control | `04_embed.py` | External API dependency | Peak load làm fail job hàng loạt |

### Bottleneck #1 — OCR scan PDF là điểm nghẽn lớn nhất

Hiện tại flow parse PDF đi theo chuỗi:

1. đọc toàn bộ file vào RAM
2. `pypdf` thử extract text
3. nếu trang rỗng thì render cả trang sang PNG
4. gọi OCR remote cho từng trang một

Điểm nghẽn nằm ở chỗ OCR đang **tuần tự theo page**:

```python
for page_num, page in enumerate(reader.pages, start=1):
    text = (page.extract_text() or "").strip()
    if not text:
        rendered_page = _render_pdf_page_as_png(page_num - 1)
        if rendered_page:
            text = _ocr_page_image_bytes(rendered_page)
```

**Hệ quả thực tế:**
- Một PDF scan 200–500 trang sẽ biến thành 200–500 OCR calls nối đuôi nhau
- Latency xử lý một tài liệu lớn có thể lên hàng chục phút
- Timeout job dễ bị chạm trước khi xong OCR
- Cost OCR tăng tuyến tính theo số trang, không có caching theo page/content hash

**Kết luận:** Nếu workload production có nhiều scan PDF, đây sẽ là điểm nghẽn đầu tiên cả về thời gian lẫn chi phí.

### Bottleneck #2 — Scanner scale kém khi bucket lớn

Scanner hiện làm hai việc đắt đỏ trong cùng một vòng:

1. paginate toàn bộ prefix trong S3
2. gọi `get_by_file_path()` cho từng object

```python
for page in pages:
    for obj in page.get("Contents", []):
        ...
        existing = self._metadata_store.get_by_file_path(s3_uri)
```

Với metadata store là PostgreSQL, đây là mô hình **N+1 lookup**:
- 10,000 files → 10,000 metadata queries
- 100,000 files → 100,000 metadata queries

**Hệ quả thực tế:**
- Scan time tăng tuyến tính theo số object trong bucket/prefix
- DB chịu nhiều round-trip nhỏ, khó scale hơn một bulk query
- Scan có thể trở thành bottleneck ngay cả khi không ingest file nào mới

**Kết luận:** Ở scale lớn, scanner sẽ nghẽn trước cả pipeline ingest.

### Bottleneck #3 — Global lock làm giảm throughput toàn hệ thống

Hiện tại `_scan_lock` không chỉ bảo vệ pha scan mà còn bao trọn cả pha ingest batch:

```python
if not _scan_lock.acquire(blocking=False):
    ...
jobs = S3Scanner(metadata_store).scan()
return _run_jobs(jobs, ai_provider, vector_store, metadata_store)
```

Điều này giải quyết race condition, nhưng đổi lại tạo **head-of-line blocking**:
- một batch OCR chậm giữ lock rất lâu
- background scanner bị skip
- manual `/scan` trả `409`
- toàn hệ thống chỉ có thể có một “scan cycle” tại một thời điểm

**Kết luận:** Lock hiện tại tối ưu cho correctness, chưa tối ưu cho throughput.

### Bottleneck #4 — Re-index path gây write amplification cao

Mỗi lần re-index document, hệ thống đang:

1. `vector_store.delete(doc_id)`
2. upsert lại toàn bộ document record
3. upsert lại toàn bộ chunks

Trong SQL metadata store, `upsert()` thực chất là `DELETE + INSERT`, và `upsert_chunks()` cũng xóa hết chunks cũ rồi insert lại toàn bộ.

**Hệ quả thực tế:**
- một thay đổi nhỏ ở file vẫn gây rewrite toàn bộ document
- Qdrant write I/O và PostgreSQL write I/O tăng mạnh khi re-ingest thường xuyên
- tài liệu lớn có hàng nghìn chunks sẽ khuếch đại chi phí index

**Kết luận:** Đây là bottleneck lớn ở workload “re-index nhiều”, không nhất thiết ở workload “ingest lần đầu”.

### Bottleneck #5 — `/search` phụ thuộc trực tiếp vào latency embed online

Search flow hiện tại là:

```python
query_vector = self._ai_provider.embed([query])[0]
chunks = self._vector_store.search(query_vector, top_k=top_k)
```

**Hệ quả thực tế:**
- mỗi request `/search` phải chờ một external AI call trước khi chạm Qdrant
- p95 search latency gần như bị neo bởi p95 embedding latency
- nếu AI provider chậm/rate-limit, search degrade ngay cả khi Qdrant khỏe

**Kết luận:** Điểm nghẽn online của search không nằm ở vector DB, mà nằm ở bước embed query.

### Bottleneck #6 — Embed stage chưa có backpressure thật sự

`04_embed.py` có batching, nhưng chưa có:
- retry cho 429/5xx
- jitter/backoff
- adaptive batch sizing
- concurrency governor theo token budget

```python
embeddings = ai_provider.embed([chunk.content for chunk in batch])
```

**Hệ quả thực tế:**
- peak load có thể làm nhiều jobs fail cùng lúc
- retry ở tầng consumer không đủ tinh vì retry cả job thay vì retry từng batch
- cost và thời gian bị lãng phí do phải làm lại các batch đã thành công trước đó

**Kết luận:** Đây là bottleneck vận hành khi scale traffic, đặc biệt dưới rate limit hoặc transient outage.

### Bottleneck theo loại workload

| Loại workload | Bottleneck đầu tiên | Bottleneck thứ hai |
|---------------|---------------------|--------------------|
| Nhiều scan PDF lớn | OCR parse | Global scan lock |
| Nhiều file nhỏ trong bucket lớn | S3 scan + metadata lookup | DB round-trips |
| Re-ingest thường xuyên | Rewrite toàn bộ vectors/chunks | Qdrant + Postgres write I/O |
| Nhiều search đồng thời | Query embedding online | AI provider rate limit |

### Kết luận bottleneck

Nếu chỉ nhìn correctness, hệ thống hiện tại đã khá ổn. Nhưng nếu nhìn theo production scale:

- bottleneck lớn nhất về **latency/cost** là OCR scan PDF
- bottleneck lớn nhất về **throughput hệ thống** là scanner + global lock
- bottleneck lớn nhất về **online query latency** là embed query đồng bộ
- bottleneck lớn nhất về **write efficiency** là full rewrite khi re-index

Nói ngắn gọn: hệ thống hiện chưa nghẽn ở FastAPI hay chunking; nó nghẽn ở **I/O ngoài hệ thống** (S3, OpenAI, Qdrant, PostgreSQL) và ở **cách phối hợp pipeline**.

---

## 2. Pipeline Stage — Phân tích từng bước

### 2.1 `01_parse.py` — Memory & OCR Risks

#### Vấn đề: Không giới hạn kích thước file trước khi đọc

```python
# utils/storage.py
def read_binary(file_uri: str) -> bytes:
    return Path(file_uri).read_bytes()  # load toàn bộ file vào RAM
```

**Scenario thực tế:** Một file PDF scan chất lượng cao (300 DPI, 500 trang) có thể đạt 800MB–2GB. `read_bytes()` sẽ:
- Allocate 800MB–2GB heap trong process
- Nếu 4 workers chạy đồng thời: 3.2GB–8GB RAM chỉ cho file I/O
- Python GC không giải phóng ngay → peak memory cao hơn thực tế

**Khuyến nghị:** Stream-read cho S3, giới hạn file size trước khi load:
```python
MAX_FILE_SIZE_BYTES = 200 * 1024 * 1024  # 200MB

def read_binary(file_uri: str) -> bytes:
    if file_uri.startswith("s3://"):
        return _read_s3_bytes_streaming(file_uri)
    path = Path(file_uri)
    if path.stat().st_size > MAX_FILE_SIZE_BYTES:
        raise FileTooLargeError(f"{path.name}: {path.stat().st_size} bytes exceeds limit")
    return path.read_bytes()
```

---

#### Vấn đề: PyMuPDF render tại scale=2x tốn 4x RAM cho từng page

```python
# pipeline/01_parse.py
pixmap = rendered_document.load_page(page_index).get_pixmap(
    matrix=fitz.Matrix(2, 2),  # scale 2x cả chiều ngang lẫn dọc
    alpha=False,
)
```

**Tính toán:** Trang A4 tại 72 DPI (default) = 595×842 px. Scale 2x → 1190×1684 px. RGB = 3 bytes/pixel → ~6MB/trang chỉ trong RAM. Tài liệu 100 trang = ~600MB peak memory chỉ để render OCR. Sau đó gửi qua base64 lên GPT-4o API (thêm 33% overhead base64).

**Ảnh hưởng thực tế:** Một file scan 100 trang có thể tốn 600MB RAM và 100 API calls đến GPT-4o với chi phí ~$0.10–$0.50/tài liệu tùy độ phức tạp.

---

#### Vấn đề: Password-protected PDF silently returns empty

```python
# pypdf sẽ raise hoặc return empty string tùy phiên bản
text = (page.extract_text() or "").strip()
if not text:
    # sẽ cố OCR, nhưng nếu PDF encrypted → pixmap cũng trống
```

**Scenario:** User upload file PDF có password → pipeline không trích xuất được text → tất cả trang đều empty → chunker không có gì → job bị raise ValueError: "parse produced empty text" → `status="failed"`. Không có error message đủ rõ để user hiểu vấn đề.

---

#### Vấn đề: DOCX với embedded images/charts mất hoàn toàn

```python
def _parse_docx(file_bytes: bytes) -> list[tuple[int, str]]:
    document = DocxDocument(io.BytesIO(file_bytes))
    text = "\n".join(
        paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()
    ).strip()
```

**Mất mát dữ liệu:** Mọi biểu đồ (Chart), hình ảnh (Image), bảng (Table trong cell), SmartArt, math equation trong DOCX đều bị bỏ qua hoàn toàn. Đối với báo cáo tài chính hay tài liệu kỹ thuật, đây là mất mát nghiêm trọng về nội dung.

---

### 2.2 `02_clean.py` — Language-Specific Blind Spots

#### Vấn đề: Regex normalization phá vỡ cấu trúc có ý nghĩa

```python
normalized = re.sub(r"[ \t]+", " ", normalized)   # collapse whitespace
normalized = re.sub(r"\n{3,}", "\n\n", normalized)  # collapse blank lines
```

**Các trường hợp bị phá vỡ:**
- **Code snippets trong tài liệu kỹ thuật:** Indentation bị mất
- **Bảng ASCII:** Cột alignment bị hỏng
- **Thơ/văn xuôi đặc biệt:** Xuống dòng có ý nghĩa ngữ nghĩa bị collapse
- **Vietnamese: Dấu câu liên tiếp** như `...` (ba chấm) không bị ảnh hưởng nhưng `\n  ` trước bullet points bị normalize

---

#### Vấn đề: Null bytes và control characters không được xử lý

PDF scan chất lượng kém đôi khi produce text chứa `\x00`, `\x01`, `\x1a` (Ctrl+Z), hay các control characters khác. Sau khi `clean()`, những ký tự này vẫn tồn tại trong content, có thể:
- Gây lỗi khi ghi vào PostgreSQL TEXT column (tùy collation)
- Gây lỗi khi encode JSON trong API response
- Phá vỡ tokenizer downstream

---

### 2.3 `03_chunk.py` — Tokenizer Fallback & Memory

#### Vấn đề: tiktoken fallback hoàn toàn im lặng

```python
def _get_encoder():
    try:
        import tiktoken
        return tiktoken.encoding_for_model("text-embedding-3-small")
    except Exception:
        return None  # silently falls back to word-split

_ENCODER = _get_encoder()  # executed at module import time
```

**Hệ quả nghiêm trọng:**
- Nếu `tiktoken` không installed (vd: Docker image thiếu, air-gapped env, package conflict), `_ENCODER = None`
- `_tokenize()` fallback: `list(range(len(text.split())))` → đếm từ, không phải token
- Chunk size "512" trở thành "512 words" thay vì "512 tokens"
- Một chunk 512 words ≈ 700–1000 tokens → vượt context limit của embedding model
- OpenAI `text-embedding-3-small` có input limit là 8191 tokens → chunks lớn hơn sẽ bị truncate silently

**Worst case:** Toàn bộ production chạy với word-split mà không ai biết → search quality giảm, token limit exceeded sporadically → embedding API trả partial results.

---

#### Vấn đề: Memory footprint khi tokenize tài liệu lớn

```python
full_tokens, token_to_page = _build_token_page_map(pages)
```

Hàm này build 2 list song song có cùng độ dài với tổng số token của toàn bộ document. Với tài liệu 1000 trang pháp lý:
- 1000 trang × 500 token/trang = 500,000 token integers
- `full_tokens`: 500,000 × 8 bytes (Python int) = 4MB
- `token_to_page`: 500,000 × 8 bytes = 4MB  
- Nhân thêm overhead list Python: ~56 bytes per element = 56MB additional

Không nghiêm trọng một mình, nhưng cộng với file bytes và page text → có thể đạt 200–500MB per worker cho tài liệu lớn.

---

#### Vấn đề: Chunk cực kỳ nhỏ ở cuối tài liệu

Sliding window với step = chunk_size - overlap = 448:
- Tài liệu 600 tokens: chunk 0 = [0:512], chunk 1 = [448:600] = **152 tokens**
- Chunk 152 tokens vẫn được embed và index → tốn API call, có thể có chất lượng retrieval kém
- Không có minimum chunk size filter

---

### 2.4 `04_embed.py` — No Retry, No Deduplication

#### Vấn đề: Zero retry logic quanh API call

```python
def run(chunks: list[ChunkResult], ai_provider: AIProvider, batch_size: int = 32) -> list[ChunkResult]:
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        embeddings = ai_provider.embed([chunk.content for chunk in batch])
        for chunk, embedding in zip(batch, embeddings):
            chunk.embedding = embedding
```

**Scenario:** 500 chunks → 16 batches. Batch thứ 10 gặp OpenAI rate limit (429) hay transient 500 → toàn bộ job fail. 9 batches đầu đã embed xong nhưng không được lưu vì exception abort toàn bộ. Phải re-embed từ đầu khi retry → tốn thêm 9 × 32 × cost.

**Khuyến nghị:**
```python
import time
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(5),
)
def _embed_with_retry(provider, texts):
    return provider.embed(texts)
```

---

#### Vấn đề: Không validate embedding dimension trước khi index

```python
chunk.embedding = embedding  # không check len(embedding) == EMBEDDING_DIM
```

**Scenario:** Embedding model thay đổi (vd: upgrade từ `text-embedding-3-small` sang `text-embedding-3-large`) nhưng Qdrant collection vẫn tạo với `size=1536`. Qdrant sẽ reject upsert với vector sai dimension → job fail với lỗi khó debug, **sau khi đã xóa vectors cũ** (vì `05_index` gọi `vector_store.delete()` trước).

---

#### Vấn đề: Content duplication không được dedup

Nếu nhiều file có cùng nội dung (vd: cùng template nhưng khác tên file), chúng được embed riêng biệt hoàn toàn → tốn API cost, tốn storage Qdrant, làm loãng search results.

---

### 2.5 `05_index.py` — Atomicity Gap (Critical)

#### Vấn đề: Delete → Upsert không atomic — cửa sổ trống

```python
def run(chunks, job, vector_store, metadata_store, ...):
    vector_store.delete(job.doc_id)           # (1) Qdrant vectors bị xóa
    metadata_store.update_status(job.doc_id, "indexing")
    # ...
    vector_store.upsert(chunks)               # (2) Qdrant vectors được ghi lại
    metadata_store.upsert_chunks(chunks)      # (3) PostgreSQL chunks
    metadata_store.update_status(job.doc_id, "indexed")
```

**Vấn đề:**
1. Giữa `(1)` và `(2)`, nếu user search document này → **zero results** (vectors đã xóa)
2. Nếu process crash sau `(1)` nhưng trước `(2)` → document **mất vĩnh viễn khỏi Qdrant** mà PostgreSQL vẫn có record
3. Nếu `(2)` thành công nhưng `(3)` fail → Qdrant có vectors mới, PostgreSQL chunks table là cũ

**Không có transaction span cross Qdrant và PostgreSQL** → hai store có thể out-of-sync.

---

#### Vấn đề: Document stuck "indexing" không có recovery

```python
metadata_store.update_status(job.doc_id, "indexing")  # set trước khi làm gì
```

Nếu container bị kill (OOMKilled, SIGKILL, machine crash) sau dòng này → status mãi là "indexing". S3 Scanner sẽ **skip file này mãi mãi**:

```python
elif existing.status == "indexing":
    log.debug("S3Scanner: skipping %s — already indexing", s3_uri)
```

**Không có timeout / stale-lock recovery.** Cần kiểm tra `updated_at` so với threshold:
```python
STALE_INDEXING_THRESHOLD = timedelta(minutes=30)
if existing.status == "indexing":
    if datetime.now(timezone.utc) - existing.updated_at > STALE_INDEXING_THRESHOLD:
        log.warning("Stale indexing detected for %s, requeueing", s3_uri)
        # requeue as retry
    else:
        log.debug("Skipping %s — currently indexing", s3_uri)
```

---

## 3. Vấn đề Atomicity & Data Consistency

### 3.1 Cross-store Split Brain

Hệ thống dùng 2 stores hoàn toàn tách biệt (Qdrant + PostgreSQL) cho cùng một document. Không có distributed transaction, không có saga pattern, không có compensation logic.

**Trạng thái có thể xảy ra:**

| Qdrant | PostgreSQL `documents` | PostgreSQL `document_chunks` | Khả năng xảy ra |
|--------|------------------------|------------------------------|-----------------|
| Có vectors | `indexed` | Có chunks | ✅ Normal |
| Không có | `indexed` | Có chunks | 🔴 Sau crash ở (1) |
| Có vectors | `indexing` | Không có | 🔴 Sau crash ở (2) |
| Có vectors | `indexed` | Không có | 🟠 Nếu upsert_chunks fail |
| Có vectors (cũ) | `indexed` | Chunks mới | 🟠 Nếu Qdrant upsert fail |

Không có mechanism nào để phát hiện và heal các trạng thái inconsistent này.

---

### 3.2 SQLMetadataStore.upsert() dùng DELETE + INSERT, không phải UPSERT

```python
def upsert(self, doc: DocumentRecord) -> None:
    with self._engine.begin() as conn:
        conn.execute(delete(self._documents).where(self._documents.c.id == doc.id))
        conn.execute(self._documents.insert().values(**payload))
```

**Race condition:** Hai workers cùng index `doc_id="abc"` đồng thời (vd: Kafka duplicate delivery + manual scan):
1. Worker A: DELETE doc "abc"
2. Worker B: DELETE doc "abc" (noop)
3. Worker A: INSERT doc "abc" (status=indexing)
4. Worker B: INSERT doc "abc" (status=indexing) — **DUPLICATE KEY ERROR** hoặc 2 records

Trong PostgreSQL, bước `engine.begin()` tạo transaction nhưng không có SELECT FOR UPDATE → hai DELETE+INSERT chạy concurrently có thể gây unique constraint violation hoặc lost update.

**Đúng phải là:**
```sql
INSERT INTO documents (...) VALUES (...)
ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, updated_at = NOW();
```

---

### 3.3 Alembic vs `create_all()` — Schema Drift

```python
# utils/stores.py
class SQLMetadataStore:
    def __init__(self, db_url=None):
        self._metadata.create_all(self._engine)  # tự tạo table nếu chưa có
```

Vấn đề: `create_all()` chỉ tạo table khi **không tồn tại**, không apply migrations. Nếu:
1. DB khởi đầu với `create_all()` → schema version X
2. Alembic migration thêm column mới → schema version X+1
3. App restart → `create_all()` thấy table đã có → **bỏ qua migration** → column mới không được thêm
4. App crash với `OperationalError: column "new_col" does not exist`

**Production risk:** Migration `a1f3c8d20e47_add_s3_last_modified_to_documents.py` có thể không được apply nếu DB đã tồn tại từ trước khi Alembic được setup.

---

## 4. Concurrency & Race Conditions

### 4.1 Scan Lock — Dead Lock Risk

```python
# api/main.py
@app.post("/scan")
def trigger_scan(request: ScanRequest, background_tasks: BackgroundTasks):
    if not _scan_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="scan already in progress")
    try:
        jobs = S3Scanner(app.state.metadata_store).scan(...)
    except Exception:
        _scan_lock.release()
        raise
    if not jobs:
        _scan_lock.release()
        return {"status": "scan started", "queued": 0}
    background_tasks.add_task(
        _run_jobs_and_release_lock, jobs, ...
    )
    return {"status": "scan started", "queued": len(jobs)}
```

**Vấn đề:** `background_tasks.add_task()` chỉ *đăng ký* task, chưa chạy. Response được trả về trước khi background task bắt đầu. Nếu FastAPI/Starlette gặp lỗi khi dispatch background task (hiếm nhưng possible), lock không được release.

**Nghiêm trọng hơn:** Background task giữ lock trong suốt thời gian process **tất cả** jobs. Nếu S3 bucket có 10,000 files mới và 4 workers xử lý, lock bị giữ trong vài **giờ** → mọi POST /scan trong thời gian này đều trả 409.

---

### 4.2 Scanner Thread — Silent Death

```python
# api/main.py
def _scanner_loop(ai_provider, vector_store, metadata_store):
    while True:
        try:
            _scan_and_run_once(...)
        except Exception as exc:
            log.error("Scanner loop error: %s", exc)
        time.sleep(interval)
```

Thread daemon → nếu exception trong `time.sleep()` (bị signal, OS interrupt), loop thoát → thread chết. Không có restart mechanism, không có alerting. Application tiếp tục chạy bình thường nhưng tự động scan bị dừng vĩnh viễn cho đến khi restart.

---

### 4.3 Notifier Producer — Singleton với Threading Bug

```python
_producer = None
_producer_lock = threading.Lock()

def _get_producer():
    global _producer
    if _producer is not None:  # (A) check without lock
        return _producer
    with _producer_lock:
        if _producer is None:  # (B) double-check inside lock
            _producer = KafkaProducer(...)
    return _producer
```

Pattern double-checked locking này đúng trong Java (có `volatile`), nhưng trong Python với CPython GIL nó *thường* an toàn. Tuy nhiên với Jython/PyPy không có GIL → check (A) và assignment có thể race. Ít rủi ro trên CPython nhưng không phải zero-risk.

**Deeper issue:** Nếu `KafkaProducer()` constructor raise exception (Kafka unavailable), `_producer` vẫn là `None` → mỗi lần gọi `notify()` sẽ retry tạo producer → spam retry với overhead. Nên cache failure state.

---

## 5. Memory & Resource Leaks

### 5.1 PDF fitz Document Không Close Khi Exception

```python
# pipeline/01_parse.py
try:
    import fitz as fitz_module
    rendered_document = fitz.open(stream=file_bytes, filetype="pdf")
except Exception:
    rendered_document = None

try:
    reader = PdfReader(io.BytesIO(file_bytes))
    # ...
    return pages
finally:
    if rendered_document is not None:
        rendered_document.close()  # OK — finally block
```

Code này đúng — `finally` đảm bảo `close()` được gọi. Tuy nhiên, nếu `PdfReader(io.BytesIO(file_bytes))` raise exception *trước* khi `try` inner bắt đầu, `rendered_document` vẫn được close trong `finally`. Đây thực ra là **acceptable** — chỉ cần chú ý nếu refactor.

---

### 5.2 SQLAlchemy Engine Pool — Không Giới Hạn Connections

```python
self._engine = create_engine(db_url or settings.DB_URL, future=True)
```

Default connection pool: `pool_size=5`, `max_overflow=10` → tối đa 15 connections đồng thời per `SQLMetadataStore` instance. Nhưng:
- `SCAN_MAX_WORKERS=4` workers mỗi worker cần connection
- API requests cần connection cho `/status`
- Background scan thread cần connection
- Tổng có thể là 10–20 concurrent DB operations → pool exhaustion → `TimeoutError: QueuePool limit` → jobs fail

Cần configure pool explicitly:
```python
create_engine(
    db_url,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_pre_ping=True,  # detect stale connections
)
```

---

### 5.3 Embedding List Memory trong ChunkResult

```python
class ChunkResult(BaseModel):
    embedding: list[float] = Field(default_factory=list)
```

Sau `04_embed.py`, mỗi `ChunkResult` chứa vector 1536 floats = 1536 × 8 bytes = 12KB. Với 1000 chunks = 12MB chỉ riêng embeddings trong RAM. Sau khi `05_index.py` upsert xong, list này không cần thiết nữa nhưng giữ trong RAM cho đến khi GC collect.

Với 4 concurrent workers, mỗi worker có thể có 1000 chunks → 4 × 12MB = 48MB chỉ cho embeddings đã indexed xong.

---

## 6. Failure Scenarios thực tế

### Scenario 1: OpenAI Outage (Duration: 2 hours)

**Timeline:**
1. T+0: OpenAI embedding API down
2. T+0 → T+120min: Kafka consumer retry 3 lần mỗi message, sleep `min(attempt, 3)` = 3s
3. Mỗi message: 3 attempts × 3s sleep + pipeline time ≈ 30–60s per message
4. Consumer lag tích lũy: 120min / (60s/msg) = 120 messages blocked
5. T+120: Mỗi message đến DLQ, `write_dlq_file()` ghi file vào `data/dlq/`
6. DLQ notify gửi tới Kafka topic `DocumentUploaded.DLQ`
7. T+121: OpenAI recover, nhưng 120 files đã ở DLQ → cần manual reprocess
8. **Không có tự động replay DLQ** trong code hiện tại

**Data loss risk:** Trung → Không mất data (file vẫn trong S3), nhưng cần manual intervention.

---

### Scenario 2: OOM trong Scan Lớn (1000 files mới)

**Timeline:**
1. S3 bucket có 1000 files PDF mới, mỗi file trung bình 50MB
2. `POST /scan` → S3Scanner tạo 1000 `IngestJob` objects trong RAM
3. `ThreadPoolExecutor(max_workers=4)` submit 1000 futures
4. 4 workers song song, mỗi worker load 50MB PDF → 200MB peak
5. + 4 × 1000 chunks × 12KB embeddings = 48MB
6. + 1000 IngestJob objects pending in queue
7. Nếu machine có 4GB RAM: OS OOM killer có thể kill process
8. Khi process bị kill: `_scan_lock` không được release (không có finally cho thread death)
9. App restart → scan lock clear (in-memory), nhưng tất cả documents trong `status="indexing"` stuck
10. **Không có document nào được index thành công**

---

### Scenario 3: Qdrant Mất Kết Nối Giữa Delete và Upsert

**Timeline:**
1. Worker bắt đầu index `doc_id="important-contract"`
2. `vector_store.delete("important-contract")` → thành công, 200 vectors bị xóa
3. Network partition: kết nối tới Qdrant bị ngắt trong 30s
4. `vector_store.upsert(chunks)` → `ConnectionError` sau 30s
5. Exception được catch ở `pipeline/run.py`
6. `metadata.update_status("important-contract", "failed")` → PostgreSQL update OK
7. `metadata.record_job(status="failed")` → OK
8. **Kết quả: Document "important-contract" KHÔNG CÒN trong Qdrant, nhưng PostgreSQL status="failed"**
9. S3 Scanner: status="failed" → retry job → re-parse, re-embed, re-index → OK
10. **Gap time:** Từ khi delete đến khi re-index thành công: có thể 5–15 phút tùy retry interval
11. Trong thời gian này, mọi search liên quan đến document này trả về empty

---

### Scenario 4: Embedding Model Upgrade (text-embedding-3-small → text-embedding-3-large)

**Timeline:**
1. DevOps đổi `EMBED_MODEL=text-embedding-3-large` trong `.env`
2. `EMBEDDING_DIM=3072` cần được đổi (hiện tại = 1536)
3. **Nếu quên đổi EMBEDDING_DIM:**
   - Qdrant collection đã tạo với `size=1536`
   - Provider trả về vector 3072 dims
   - `vector_store.upsert()` → Qdrant reject: dimension mismatch
   - Tất cả jobs fail với error khó đọc
4. **Nếu nhớ đổi EMBEDDING_DIM:**
   - Qdrant collection cũ có `size=1536`
   - `QdrantStore.__init__()` check `if self._collection not in existing` → collection đã tồn tại → **không recreate**
   - Upsert với 3072-dim vector vào collection khai báo 1536-dim → Qdrant reject
   - **Phải xóa và recreate collection, mất toàn bộ data cũ**
5. **Không có migration path** từ model cũ sang model mới trong code hiện tại
6. Cần re-index toàn bộ corpus → có thể mất nhiều giờ đến nhiều ngày

---

### Scenario 5: Clock Skew Giữa Servers

```python
# adapters/s3_adapter.py
elif existing.s3_last_modified and s3_last_modified.replace(tzinfo=None) > existing.s3_last_modified.replace(tzinfo=None):
```

**Vấn đề timezone stripping:** `replace(tzinfo=None)` xóa timezone info TRƯỚC khi so sánh. S3 trả `s3_last_modified` là UTC, PostgreSQL lưu `s3_last_modified` có thể là local time (tùy config). Stripping timezone và so sánh naive datetime có thể:
- Nếu server ở UTC+7: local time = UTC + 7h → lưu vào DB là `2026-05-29 17:00:00` (naive)
- S3 trả `2026-05-29 10:00:00+00:00` → sau strip → `2026-05-29 10:00:00`
- So sánh: `10:00 > 17:00` → **False** → file không được re-index dù đã thay đổi

**Khuyến nghị:** Luôn so sánh timezone-aware:
```python
elif existing.s3_last_modified:
    db_ts = existing.s3_last_modified.replace(tzinfo=timezone.utc) if existing.s3_last_modified.tzinfo is None else existing.s3_last_modified
    s3_ts = s3_last_modified if s3_last_modified.tzinfo else s3_last_modified.replace(tzinfo=timezone.utc)
    if s3_ts > db_ts:
        # re-ingest
```

---

### Scenario 6: DLQ Disk Full

**Timeline:**
1. Kafka cluster unavailable trong 24 giờ
2. Mỗi failed Kafka consumer message → `write_dlq_file()` ghi file vào `data/dlq/`
3. File DLQ trung bình = event JSON size ≈ 2KB–10KB
4. 10,000 messages/ngày × 5KB = 50MB/ngày
5. 30 ngày Kafka outage = 1.5GB DLQ files
6. Disk full → `write_dlq_file()` raise `OSError: No space left on device`
7. `write_dlq_file()` exception không được catch trong kafka_consumer → **consumer crash**
8. Pod restart → consumer restart → đọc lại offset từ Kafka → retry tất cả failed messages → lại fail → DLQ lại đầy → loop
9. **Thundering herd restart loop**

---

### Scenario 7: Airflow DAG Re-run với Hardcoded doc_id

```python
# dags/pipeline_dag.py
def _run_placeholder_event() -> None:
    process_event({
        "doc_id": "airflow-manual-run",  # hardcoded
        "s3_uri": "data/sample/policy.txt",
        ...
    })
```

**Vấn đề:** Mỗi lần Airflow DAG re-run:
1. Cùng `doc_id="airflow-manual-run"` được index lại
2. Vector store delete vectors cũ → upsert mới → OK (idempotent)
3. `ingestion_jobs` table: **một record mới được insert** mỗi lần
4. Sau 1000 DAG runs: 1000 records trong `ingestion_jobs` cho cùng một doc_id
5. Không có semantic ý nghĩa — không có cách phân biệt manual run nào là "production"

---

## 7. Kafka Consumer — At-Least-Once Edge Cases

### 7.1 Duplicate Indexing từ Offset Replay

```python
# streaming/kafka_consumer.py
for message in consumer:
    process_event(message.value)  # (1) process
    consumer.commit()              # (2) commit offset
```

**Scenario:** Process_event thành công (file indexed) → commit đang gửi đến Kafka broker → network issue → commit không được acknowledge → broker coi offset chưa commit → consumer restart → **message được đọc lại và xử lý lần 2**.

Vì pipeline idempotent (delete + upsert), kết quả cuối cùng đúng, nhưng:
- Re-parse, re-embed lại toàn bộ file = tốn thời gian + API cost
- `ingestion_jobs` có 2 records "indexed" cho cùng một message

**Đây là behavior đúng của at-least-once** nhưng cần documented rõ.

---

### 7.2 Single-Threaded Consumer Bottle Neck

Consumer Kafka hiện tại là single-threaded. Một message slow (PDF 500 trang với OCR) có thể block consumer **15 phút** trước khi next message được đọc. Consumer lag tích lũy không giới hạn.

**Giải pháp:** Partition-based parallelism (tăng partition count + consumer instances) hoặc async processing với message queue internal.

---

### 7.3 Sleep Pattern Không Có Jitter — Thundering Herd

```python
# streaming/kafka_consumer.py
time.sleep(min(attempt, 3))  # sleep 1s, 2s, 3s
```

Nếu 10 consumer instances đều gặp lỗi cùng lúc (vd: OpenAI outage), tất cả cùng sleep 3s rồi retry đồng loạt → thundering herd vào OpenAI API → tất cả lại fail → repeat. Cần jitter:

```python
import random
time.sleep(min(attempt, 3) + random.uniform(0, 1))
```

---

## 8. S3 Scanner — Race & Drift Issues

### 8.1 Scanner Giữ Lock Trong Suốt Quá Trình Xử Lý

```python
# api/main.py
def _scan_and_run_once(ai_provider, vector_store, metadata_store):
    if not _scan_lock.acquire(blocking=False):
        return 0
    try:
        jobs = S3Scanner(metadata_store).scan()
        return _run_jobs(jobs, ...)  # có thể mất hàng giờ
    finally:
        _scan_lock.release()
```

**Vấn đề thiết kế:** Lock nên chỉ bảo vệ việc *liệt kê* jobs, không phải quá trình *xử lý*. Nếu scan phát hiện 500 files, `_run_jobs` mất 2 giờ → lock bị giữ 2 giờ → POST /scan trả 409 trong 2 giờ.

**Khuyến nghị:** Release lock sau scan, trước khi process:
```python
jobs = S3Scanner(metadata_store).scan()
_scan_lock.release()
return _run_jobs(jobs, ...)  # xử lý không cần lock
```

---

### 8.2 S3 List Objects Pagination — Memory và Timeout

```python
paginator = client.get_paginator("list_objects_v2")
pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
for page in pages:
    for obj in page.get("Contents", []):
        # process
```

**Vấn đề:** Không có timeout trên `paginate()`. Nếu bucket có 100,000 objects, đây là 1000 API calls (100 objects/page) đến S3. Mỗi call ~100ms → 100 giây chỉ để list. Trong thời gian này, scan lock được giữ và không thể cancel.

**Vấn đề 2:** Tất cả `IngestJob` objects được tạo trong RAM trước khi bắt đầu xử lý bất kỳ job nào. 100,000 IngestJob objects ≈ RAM đáng kể.

---

### 8.3 File Bị Xóa Giữa Scan và Process

**Timeline:**
1. Scanner detect file `s3://bucket/important.pdf` là mới
2. `IngestJob` được tạo
3. File bị xóa khỏi S3 (retention policy, user delete, etc.)
4. Worker bắt đầu process: `read_binary("s3://bucket/important.pdf")` → `NoSuchKey`
5. Job fail, `status="failed"`
6. Scanner cycle tiếp theo: file không còn trong S3 → không tạo job mới → document stuck ở `status="failed"` vĩnh viễn

---

## 9. Database — Performance & Schema Issues

### 9.1 Missing Indexes

Schema hiện tại (`db/schema.py`):

```python
documents = Table(
    "documents", metadata,
    Column("id", String, primary_key=True),  # index tự động
    Column("file_path", String, ...),         # NOT indexed
    Column("status", String, ...),            # NOT indexed
    ...
)
document_chunks = Table(
    "document_chunks", metadata,
    Column("chunk_id", String, primary_key=True),
    Column("doc_id", String, ...),  # NOT indexed — CRITICAL
    ...
)
ingestion_jobs = Table(
    "ingestion_jobs", metadata,
    Column("id", String, primary_key=True),
    Column("doc_id", String, ...),  # NOT indexed
    Column("status", String, ...),  # NOT indexed
    ...
)
```

**Impact:**
- `get_by_file_path(file_path)`: Sequential scan trên `documents` table → O(n) → 100ms tại 100K docs, 1s tại 1M docs. S3 Scanner gọi hàm này cho **mỗi object** trong bucket!
- `upsert_chunks()`: DELETE WHERE doc_id = ? → sequential scan trên `document_chunks` → O(n) → chậm kinh khủng khi có hàng triệu chunks
- `record_job()` lookup by doc_id: sequential scan

**Cần thiết:**
```sql
CREATE INDEX idx_documents_file_path ON documents(file_path);
CREATE INDEX idx_documents_status ON documents(status);
CREATE INDEX idx_document_chunks_doc_id ON document_chunks(doc_id);
CREATE INDEX idx_ingestion_jobs_doc_id ON ingestion_jobs(doc_id);
CREATE INDEX idx_ingestion_jobs_status ON ingestion_jobs(status);
```

---

### 9.2 `ingestion_jobs` Table Tăng Không Giới Hạn

Mỗi lần pipeline chạy (dù thành công hay thất bại) đều insert một record mới vào `ingestion_jobs`. Không có cleanup/archival.

**Tính toán:** 
- 10,000 documents, mỗi document re-index 4 lần/năm = 40,000 records/năm
- 100,000 documents, re-index daily = 36.5 triệu records/năm
- Mỗi record ~200 bytes (với error_message) → 36.5M × 200B = 7.3GB/năm chỉ cho jobs table

---

### 9.3 `document_chunks` Giữ Content Duplicate

`document_chunks` table lưu toàn bộ `content` của mỗi chunk (TEXT column), trong khi Qdrant cũng lưu content trong payload. Đây là duplicate storage:

- 1M chunks × trung bình 500 tokens × 4 bytes/token ≈ 2GB PostgreSQL content
- Cộng với Qdrant payload ≈ thêm 2GB
- Tổng duplicate: ~4GB chỉ cho text content

Cần quyết định: lưu content ở đâu là *authoritative source*. Hiện tại cả hai đều là source nhưng không có sync mechanism.

---

### 9.4 `create_all()` Chạy Mỗi Startup — Race Condition Trong HA Setup

Nếu nhiều instances của service start đồng thời (Kubernetes rolling deploy, scale-out):
- Instance A: `create_all()` check table tồn tại → không → bắt đầu CREATE
- Instance B: `create_all()` check table tồn tại → không → bắt đầu CREATE
- Có thể gây `DuplicateTable` error tùy DB và isolation level

Trong practice SQLAlchemy `create_all()` dùng `CREATE TABLE IF NOT EXISTS` → an toàn, nhưng nếu có migration đang chạy đồng thời với app startup thì nguy hiểm.

---

## 10. Vector Store — Qdrant Risks

### 10.1 Fallback Sang InMemoryVectorStore Không Được Alert

```python
def build_vector_store() -> VectorStore:
    try:
        return QdrantStore()
    except Exception as exc:
        log.warning("QdrantStore unavailable (%s), falling back to InMemoryVectorStore", exc)
        return InMemoryVectorStore()
```

**Vấn đề nghiêm trọng:** 
- App khởi động khi Qdrant chưa ready → silent fallback sang InMemory
- Tất cả documents được index vào RAM
- App tiếp tục hoạt động "bình thường" — không có error, không có alert
- Khi Qdrant recover, InMemoryVectorStore **không sync data sang Qdrant**
- Khi pod restart: tất cả InMemory data **mất hoàn toàn**
- `/health` endpoint không kiểm tra Qdrant connectivity → trả `"status": "ok"` kể cả khi dùng InMemory

---

### 10.2 Qdrant Collection Không Kiểm Tra Dimension Mismatch

```python
class QdrantStore:
    def __init__(self):
        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection not in existing:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=settings.EMBEDDING_DIM, distance=Distance.COSINE),
            )
        # Nếu collection đã tồn tại: không kiểm tra size có khớp EMBEDDING_DIM không
```

**Scenario nguy hiểm:**
1. App deploy lần 1: `EMBEDDING_DIM=1536` → tạo collection với size=1536
2. Admin thay đổi config `EMBEDDING_DIM=3072` (để dùng model mới)
3. App deploy lần 2: collection đã tồn tại → KHÔNG recreate → KHÔNG validate size
4. `embed()` trả vector 3072 → `upsert()` → Qdrant error: wrong vector dimension
5. Tất cả jobs fail, khó debug vì error message từ Qdrant không rõ ràng

---

### 10.3 Qdrant Search Không Có Pagination

```python
def search(self, vector, top_k, filters=None):
    response = self._client.query_points(
        collection_name=self._collection,
        query=vector,
        limit=top_k,
        with_payload=True,
        with_vectors=False,
    )
```

`top_k` tối đa = 50 (validated ở API layer). Nếu cần retrieve nhiều hơn (vd: cho batch reranking), không có scroll/pagination mechanism. Phải rebuild feature này.

---

## 11. AI Provider — Cost, Rate Limit, Quality Degradation

### 11.1 Không Có Cost Tracking

Không có tracking nào cho:
- Số embedding API calls và tokens
- Số OCR (vision model) calls
- Estimated cost per document / per day

Ở scale 100K documents × 50 chunks/doc × 500 tokens/chunk = 2.5 tỷ tokens embedding. Với `text-embedding-3-small` giá $0.02/1M tokens → **$50 chỉ cho embedding ban đầu**.

Không có budget cap, không có spending alert → có thể unexpected cost khi re-index trigger nhầm.

---

### 11.2 Vision Model (GPT-4o) Cost Per OCR Page

Mỗi trang PDF scan render thành 1190×1684 PNG, base64 encode → gửi lên GPT-4o.

**Chi phí ước tính:**
- Ảnh 1190×1684 = ~2M pixels → GPT-4o vision ~765 tokens input (low detail) đến ~1900 tokens (high detail)
- Output tokens: ~200 tokens OCR text
- GPT-4o: $2.50/1M input tokens, $10/1M output tokens
- Per page: ~$0.003–$0.007

**Tài liệu 200 trang scan:** $0.6–$1.4 per document. Nếu 10,000 scan PDFs trong S3 bucket được trigger re-index → **$6,000–$14,000** chỉ cho OCR.

---

### 11.3 OpenAI Rate Limits Không Có Circuit Breaker

Không có circuit breaker pattern. Nếu rate limit hit:
- Mỗi job retry 3 lần (Kafka consumer)
- Mỗi retry fail → 3 attempts thêm → 9 API calls per message vào rate limit endpoint
- Với 100 concurrent messages: 900 calls đến endpoint đang bị throttle
- Rate limit throttle nặng hơn → vòng lặp tệ hơn (positive feedback loop)

---

### 11.4 MockAIProvider trong Production Không Được Phát Hiện

```python
def build_ai_provider() -> AIProvider:
    if provider_name == "auto":
        if api_key:
            return OpenAIProvider(...)
        return MockAIProvider()  # silent fallback
```

Nếu `AI_API_KEY` bị xóa khỏi environment (config management error, secret rotation issue), app tự động fallback sang `MockAIProvider`:
- Embedding: SHA-256 hash của text, không phải semantic embedding
- Search quality: near-zero (hash-based, not semantic)
- OCR: trả placeholder string
- Không có error, không có alert
- `/health` trả `"ai_provider": "MockAIProvider"` → nếu không monitoring health endpoint thì không ai biết

---

## 12. API Layer — Security & Reliability

### 12.1 Không Có Input Size Limit

```python
class SearchRequest(BaseModel):
    query: str  # không giới hạn độ dài
    top_k: int = Field(default=5, ge=1, le=50)
```

**Attack vector:** Request với `query` dài 10MB → `ai_provider.embed([query])` gửi 10MB lên OpenAI API → timeout 60s → wasted API cost. Không có `max_length` validation.

```python
query: str = Field(min_length=1, max_length=2000)
```

---

### 12.2 `file_uri` Không Được Validate — Path Traversal Risk

```python
class IngestJob(BaseModel):
    doc_id: str
    file_uri: str  # không validate format
```

Nếu `file_uri` được user-controlled (vd: qua Kafka event):
- `file_uri = "/etc/passwd"` → `read_binary("/etc/passwd")` → nội dung file được index vào vector store
- `file_uri = "../../secret/.env"` → secrets được embed và searchable
- `file_uri = "s3://other-bucket/private.pdf"` → cross-bucket access

**Cần validate:**
```python
def _validate_file_uri(uri: str) -> None:
    if uri.startswith("s3://"):
        parsed = urlparse(uri)
        if parsed.netloc != settings.S3_BUCKET:
            raise ValueError(f"Cross-bucket access denied: {parsed.netloc}")
    else:
        path = Path(uri).resolve()
        allowed_base = Path(settings.DATA_DIR).resolve()
        if not str(path).startswith(str(allowed_base)):
            raise ValueError(f"Path traversal denied: {uri}")
```

---

### 12.3 `/health` Endpoint Không Kiểm Tra Downstream Services

```python
@app.get("/health")
def health():
    return {
        "status": "ok",  # always ok, bất kể Qdrant/PostgreSQL/OpenAI status
        "vector_store": settings.VECTOR_STORE,
        "ai_provider": app.state.ai_provider.__class__.__name__,
        "scanner": "enabled" if (...) else "disabled",
    }
```

`/health` luôn trả `200 OK` dù:
- Qdrant không kết nối được (dùng InMemory fallback)
- PostgreSQL connection pool exhausted
- AI_API_KEY expired (dùng Mock)

Kubernetes liveness/readiness probe dựa vào `/health` → pod không bao giờ bị restart dù đang ở trạng thái degraded.

**Cần:**
```python
@app.get("/health")
def health():
    checks = {
        "vector_store": _check_qdrant(),
        "database": _check_postgres(),
        "ai_provider": _check_ai_provider(),
    }
    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ok" if all_ok else "degraded", **checks}
    )
```

---

### 12.4 Không Có Rate Limiting Trên API

Không có rate limiting trên `/search` và `/scan`. Attack scenarios:
- **DDoS /search:** 1000 req/s → 1000 concurrent embed calls → rate limit OpenAI → service degradation cho tất cả users
- **Scan spam:** Liên tục POST /scan → 409 responses fine, nhưng trong thời gian lock held, mọi scan thật sự đều bị reject

---

## 13. Observability Gap

### 13.1 Logging Không Có Structure

```python
log.info("S3Scanner: found %d file(s) to ingest from s3://%s/%s", len(jobs), bucket, prefix)
```

Plain text logging không thể aggregate/filter hiệu quả trong ELK/Datadog/CloudWatch. Thiếu:
- **Trace ID / Correlation ID** xuyên suốt pipeline stages
- **Structured JSON** format
- **Log level per component** configurable at runtime
- **doc_id** trong mọi log entry liên quan đến một job cụ thể

---

### 13.2 Không Có Metrics

Không có Prometheus metrics, không có OpenTelemetry. Không thể monitor:
- `pipeline_duration_seconds` histogram per stage
- `embedding_api_calls_total` counter
- `chunks_indexed_total` counter  
- `jobs_failed_total` counter by error type
- `qdrant_collection_size_gauge`
- `consumer_lag_gauge` (per Kafka topic/partition)
- `s3_scanner_jobs_queued_gauge`

---

### 13.3 Không Có Distributed Tracing

Một request document ingestion đi qua: Kafka → consumer → parse → clean → chunk → embed → index → Qdrant → PostgreSQL. Không có trace span nào. Khi latency tăng đột biến, không thể biết bottleneck ở stage nào.

---

### 13.4 `duration_seconds` Chỉ Được Lưu, Không Được Exposed

```python
metadata.record_job(
    doc_id=job.doc_id,
    status="indexed",
    chunk_count=len(chunks),
    embedding_model=embedding_model or settings.EMBED_MODEL,
    duration_seconds=duration_seconds,
)
```

`duration_seconds` được lưu vào `ingestion_jobs` table nhưng không có API endpoint nào để query, không có aggregate metrics. Không thể biết p50/p95/p99 của pipeline latency.

---

## 14. Configuration Drift & Embedding Model Migration

### 14.1 Không Có Validation Config Tại Startup

Nhiều config dependencies không được validate:

| Config | Dependency | Vấn đề nếu sai |
|--------|------------|----------------|
| `EMBEDDING_DIM` | Phải match output dim của `EMBED_MODEL` | Upsert fail toàn bộ |
| `CHUNK_SIZE` | Phải < input limit của `EMBED_MODEL` (8191 tokens) | Embedding API truncate silently |
| `QDRANT_COLLECTION` | Collection trong Qdrant phải có `size=EMBEDDING_DIM` | Dimension mismatch |
| `DATABASE_URL` | PostgreSQL phải reachable | Startup fail (handled gracefully) |
| `KAFKA_BOOTSTRAP` | Kafka phải reachable khi consumer chạy | Consumer fail to start |

Không có startup validation routine kiểm tra tất cả những điều này.

---

### 14.2 Migration Strategy Từ Embedding Model Cũ Sang Mới

Không có migration path được thiết kế. Nếu cần upgrade model:

1. **Problem:** Vectors cũ (1536-dim) và vectors mới (3072-dim) không thể coexist trong cùng Qdrant collection
2. **No blue/green collection support**
3. **No dual-write with gradual cutover**
4. **Phải downtime toàn bộ:** Xóa collection cũ → tạo collection mới → re-index tất cả documents → search available trở lại

Với 1M documents, re-index có thể mất 10–50 giờ → unacceptable downtime.

**Pattern cần thiết:** Blue/green collection với traffic split.

---

### 14.3 `CHUNK_SIZE` Thay Đổi → Inconsistent Search Quality

Nếu `CHUNK_SIZE` được thay đổi sau khi một số documents đã được index:
- Documents cũ: chunks 512 tokens
- Documents mới: chunks 256 tokens (giả sử thu nhỏ)
- Search query được embed với model hiện tại → similarity so sánh với cả 512-token và 256-token chunks → phân phối score không uniform → ranking bị sai lệch

Không có cách biết document nào đã index với chunk size nào (metadata `chunk_strategy` chỉ là `"sliding_window"`, không lưu `chunk_size` tại thời điểm index).

---

## 15. Cascade Failure Chains

### Chain A: Storage Pressure → Consumer Loop

```
Disk Full
  └─> write_dlq_file() raises OSError
        └─> Exception in kafka_consumer (unhandled)
              └─> Consumer process crash
                    └─> Pod restart (Kubernetes)
                          └─> Consumer reads from last committed offset
                                └─> Retry same messages
                                      └─> Same failures → DLQ → Disk still full
                                            └─> LOOP (infinite restart)
```

**Giải pháp:** Catch `OSError` trong `_send_pipeline_dlq`, log and continue. DLQ là best-effort, không nên crash consumer.

---

### Chain B: OpenAI Down → Rate Limit Storm

```
OpenAI API Down (503)
  └─> All pipeline workers fail at embed stage
        └─> Kafka consumer retry 3x per message
              └─> 10 consumers × 3 retries × 100 inflight = 3000 API calls/retry cycle
                    └─> OpenAI returns 429 (rate limit)
                          └─> All retries fail → DLQ
                                └─> After OpenAI recovers:
                                      └─> Operator replays DLQ
                                            └─> 3000 messages replayed simultaneously
                                                  └─> Rate limit again
                                                        └─> LOOP
```

**Giải pháp:** Circuit breaker + exponential backoff với jitter + rate limiter trước khi gọi AI provider.

---

### Chain C: Qdrant Restart → InMemory Fallback → Data Loss

```
Qdrant Pod Restart (planned maintenance)
  └─> QdrantStore() constructor raises ConnectionError
        └─> build_vector_store() catches → returns InMemoryVectorStore
              └─> Ingestion continues normally (no alert)
                    └─> 2000 new documents indexed into RAM
                          └─> Qdrant comes back online
                                └─> InMemoryVectorStore NOT synced to Qdrant
                                      └─> App restart (for unrelated reason)
                                            └─> InMemory data LOST
                                                  └─> 2000 documents in PostgreSQL status="indexed"
                                                        └─> But NOT in Qdrant
                                                              └─> Search returns nothing for those docs
                                                                    └─> Nobody notices (no monitoring)
```

---

### Chain D: Slow OCR → Scanner Timeout → Stuck Documents

```
100 scanned PDF files discovered by S3 Scanner
  └─> SCAN_JOB_TIMEOUT_SECONDS = 900 (15 min)
        └─> PDF with 500 pages, each page needs OCR:
              └─> 500 × avg 8s OCR latency = 4000s > 900s timeout
                    └─> TimeoutError at parse stage
                          └─> status = "failed"
                                └─> Next scanner cycle: status="failed" → retry
                                      └─> Timeout again → "failed" again
                                            └─> LOOP (never indexed)
```

**Giải pháp:** Per-page timeout + checkpoint-based resume, hoặc tăng `SCAN_JOB_TIMEOUT_SECONDS` cho tài liệu lớn.

---

## 16. Khuyến nghị ưu tiên

### 🔴 Ưu tiên 1 — Critical (Fix ngay trước production)

| # | Vấn đề | Fix |
|---|--------|-----|
| 1 | Document stuck "indexing" vĩnh viễn | Thêm `stale_indexing_threshold` trong S3 Scanner |
| 2 | Không giới hạn file size | Validate size trước `read_binary()`, reject files > limit |
| 3 | `ingestion_jobs` tăng không giới hạn | Thêm retention policy, archive job records > 90 days |
| 4 | Missing DB indexes | Add index trên `file_path`, `doc_id` (chunks), `doc_id` (jobs) |
| 5 | `/health` không check downstream | Implement proper health check với Qdrant + PostgreSQL probe |

### 🟠 Ưu tiên 2 — High (Fix trong sprint tiếp theo)

| # | Vấn đề | Fix |
|---|--------|-----|
| 6 | Không retry khi OpenAI rate limit | Implement tenacity retry với exponential backoff + jitter |
| 7 | tiktoken fallback không được phát hiện | Assert `_ENCODER is not None` hoặc log ERROR + metric |
| 8 | InMemoryVectorStore fallback không alert | Raise exception hoặc post metric/alert khi fallback xảy ra |
| 9 | SQLAlchemy pool không configured | Set `pool_size`, `max_overflow`, `pool_pre_ping=True` |
| 10 | DLQ disk full crash consumer | Catch `OSError` trong DLQ write, log and continue |
| 11 | Scan lock held trong suốt quá trình process | Release lock sau scan, trước khi process jobs |
| 12 | Clock skew S3 timestamp comparison | So sánh timezone-aware datetimes |

### 🟡 Ưu tiên 3 — Medium (Backlog)

| # | Vấn đề | Fix |
|---|--------|-----|
| 13 | Không có cost tracking | Log token usage, implement cost estimate per job |
| 14 | Không có structured logging | Migrate sang `structlog` hoặc JSON formatter |
| 15 | Không có metrics | Implement Prometheus metrics cho key pipeline events |
| 16 | Embedding model migration | Design blue/green collection cutover strategy |
| 17 | Path traversal trong file_uri | Validate file_uri against allowed bases |
| 18 | `documents.upsert()` dùng DELETE+INSERT | Migrate sang ON CONFLICT DO UPDATE |
| 19 | Alembic vs create_all() drift | Disable `create_all()`, enforce Alembic-only migrations |
| 20 | Consumer single-threaded | Tăng partition count + multiple consumer instances |

### 🟢 Ưu tiên 4 — Low (Nice to have)

| # | Vấn đề | Fix |
|---|--------|-----|
| 21 | Airflow DAG hardcoded doc_id | Generate doc_id từ file_uri hash |
| 22 | Minimum chunk size filter | Skip chunks < 10 tokens |
| 23 | UUID5 namespace semantically sai | Đổi sang `NAMESPACE_URL` |
| 24 | `document_chunks` content duplicate với Qdrant | Quyết định single source of truth |
| 25 | Không có input rate limiting trên /search | Implement per-IP rate limit với Redis |

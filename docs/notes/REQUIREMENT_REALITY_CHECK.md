# Requirement Reality Check

Phạm vi đọc: toàn bộ `docs/`, bỏ qua `docs/team-work/`.

Mục tiêu của tài liệu này là trả lời thẳng các câu hỏi "requirement có thật không", dựa trên những gì tài liệu hiện có xác nhận được, những gì chỉ là suy luận hợp lý, và những gì còn thiếu.

## Cách đọc

- `Docs xác nhận`: có thể đọc ra trực tiếp từ tài liệu hiện có.
- `Suy luận hợp lý`: không được viết nguyên văn, nhưng logic kiến trúc đang ngầm giả định như vậy.
- `Thiếu/chưa chốt`: chưa thấy source of truth trong `docs/`.

## 1. Requirement này có thật không?

**Kết luận ngắn:** Có thật ở mức kiến trúc kỹ thuật, nhưng chưa đủ chứng cứ về requirement nghiệp vụ cuối cùng.

**Docs xác nhận**

- Repo này hiện được định vị là một **DE pipeline cho document ingestion và context retrieval**, không phải chatbot hoàn chỉnh.
- Hướng kiến trúc đã chốt là `Markdown -> Section -> Caption -> Search`.
- Đơn vị retrieve mục tiêu là `section`, không còn là `512-token chunk`.
- Consumer trực tiếp là BE team hoặc AI/chatbot team ở tầng trên.

**Suy luận hợp lý**

- Requirement kỹ thuật là có thật vì nhiều tài liệu lặp lại cùng một target architecture, data contract, và risk model.
- Requirement nghiệp vụ đầu-cuối chưa thật sự được khóa, vì phần lớn docs đang trả lời "xây pipeline như thế nào", chưa trả lời "doanh nghiệp cần outcome gì để kiếm tiền/giảm rủi ro/vận hành tốt hơn".

**Thiếu/chưa chốt**

- Không có PRD hay business brief mô tả pain point gốc.
- Không có quyết định sản phẩm chính thức về phạm vi user, SLA, volume, hay ROI mong muốn.

## 2. Mục tiêu kinh doanh / tactical thật là gì?

**Kết luận ngắn:** Mục tiêu tactical khá rõ; mục tiêu kinh doanh mới chỉ được ngầm hiểu.

**Docs xác nhận**

- Chuẩn hóa tài liệu gốc thành Markdown canonical artifact.
- Chia tài liệu thành section có nghĩa.
- Sinh caption cho từng section.
- Embed caption để search semantic.
- Trả full section kèm `markdown_s3_uri` và `source_s3_uri`.
- Tăng chất lượng retrieval so với chunk-based retrieval.
- Giúp AI team đọc nhanh qua caption và vẫn truy ngược full context.

**Suy luận hợp lý**

- Mục tiêu tactical thực sự là: xây một retrieval layer ổn định để các hệ phía trên dùng làm grounding.
- Mục tiêu kinh doanh ngầm định là: giảm sai lệch khi trả lời câu hỏi nội bộ về policy/process/document, giảm thời gian tìm tài liệu, và tăng độ tin cậy của chatbot hay ứng dụng AI nội bộ.

**Thiếu/chưa chốt**

- Không có business KPI như giảm AHT, giảm ticket, tăng self-service rate, hay giảm chi phí support.
- Không có tài liệu nói ai chịu P&L hoặc owner nghiệp vụ.

## 3. Metric thành công là gì?

**Kết luận ngắn:** Docs nêu nhiều thứ nên đo, nhưng chưa chốt metric thành công chính thức.

**Docs xác nhận**

- Nên đo `precision top-k`, `recall` ở mức section, chất lượng caption, search latency, query embed latency, ingest success/fail.
- Cần metrics cho parse/split/caption/embed/index duration.
- Cần theo dõi fallback rate, OCR usage, no-result rate.

**Suy luận hợp lý**

- Nếu phải chọn vài metric gần nhất với mục tiêu hệ thống, chúng sẽ là:
  - Retrieval quality ở mức `top-k`.
  - Search latency phụ thuộc embedding latency.
  - Ingest success rate.
  - Freshness của index so với source.

**Thiếu/chưa chốt**

- Không có target số cụ thể như `P95 /search < X ms`, `top-5 recall > Y`, hay `freshness < Z phút`.
- Không có acceptance gate để nói "đủ tốt để production".

## 4. Ai là user?

**Kết luận ngắn:** User trực tiếp và user cuối đang bị tách lớp, nhưng docs mới định nghĩa rõ user trực tiếp.

**Docs xác nhận**

- Consumer trực tiếp: BE team hoặc AI chatbot team.
- Repo này không phải chatbot service; `/search` chỉ trả raw sections.

**Suy luận hợp lý**

- User cuối có thể là nhân viên nội bộ hỏi policy/process/tài liệu doanh nghiệp.
- Tài liệu refactor có nhắc bối cảnh chatbot nội bộ quy mô lớn, nên end user nhiều khả năng là nhân viên doanh nghiệp, không phải data engineer.

**Thiếu/chưa chốt**

- Không có persona chính thức.
- Không có phân loại rõ primary user, secondary user, operator user.

## 5. User quyết định gì?

**Kết luận ngắn:** User trực tiếp quyết định cách dùng retrieval result; pipeline không quyết định business action.

**Docs xác nhận**

- `/search` trả section raw; access control, filtering, reasoning là trách nhiệm caller.
- Repo này không implement permission logic ở tầng này.

**Suy luận hợp lý**

- BE/AI team quyết định:
  - Có dùng section nào vào prompt hay không.
  - Có filter theo domain/document type hay không.
  - Có hiển thị citation/source cho end user hay không.
- End user cuối quyết định:
  - Tin câu trả lời hay mở `markdown/source` để kiểm tra chéo.
  - Hành động nghiệp vụ tiếp theo dựa trên nội dung policy/process.

**Thiếu/chưa chốt**

- Không có flow quyết định người dùng cuối trong docs.
- Không có mô tả decision loop hay UX expectations.

## 6. Data đi từ đâu tới đâu?

**Kết luận ngắn:** Luồng dữ liệu đã khá rõ.

**Docs xác nhận**

```text
S3/local source
  ->
IngestJob
  ->
parse -> save markdown -> split sections -> caption -> embed -> index
  ->
Vector store + metadata store
  ->
/search
  ->
section-centric response
```

- Input chính: file nguồn từ S3 hoặc local.
- Artifact trung gian: Markdown canonical artifact.
- Output phục vụ search: vector index + metadata + section payload có lineage.

**Suy luận hợp lý**

- Đây là một ETL/retrieval pipeline đi từ raw document sang searchable semantic sections.

**Thiếu/chưa chốt**

- Chưa có data retention/lifecycle policy rõ cho raw, markdown, vector, job history.

## 7. Nút cổ chai ở đâu?

**Kết luận ngắn:** OCR, caption generation, query embedding, và scanner là các nút cổ chai chính.

**Docs xác nhận**

- OCR PDF rất đắt và chậm.
- Caption hiện có risk chạy tuần tự trong critical path.
- `/search` dính chặt vào latency của query embedding.
- S3 scanner phải list và đối chiếu diện rộng, scale kém khi upload tần suất cao.
- Scan lock gây head-of-line blocking cho các scan lớn.

**Suy luận hợp lý**

- Khi corpus tăng, bottleneck lớn nhất sẽ dịch từ code structure sang:
  - throughput của AI provider,
  - scale của scan discovery,
  - consistency/index update path.

## 8. Điểm failure ở đâu?

**Kết luận ngắn:** Có failure ở cả parsing, AI calls, indexing consistency, fallback behavior và hạ tầng.

**Docs xác nhận**

- OOM khi đọc file lớn vào RAM.
- Crash giữa `delete + upsert` vector gây trạng thái lệch.
- Qdrant và PostgreSQL không có transaction chung.
- AI provider fallback có thể làm mất semantic hoàn toàn.
- Vector store fallback sang in-memory làm mất durability.
- Metadata store fallback đổi behavior nhưng service vẫn chạy.
- Embedding dimension mismatch với collection gây lỗi runtime.
- Thiếu active probe và metrics làm failure khó nhìn thấy sớm.

**Suy luận hợp lý**

- Failure nguy hiểm nhất không phải chỉ là "service down", mà là "service vẫn chạy nhưng chất lượng sai".

## 9. Nếu component này chết thì sao?

**Kết luận ngắn:** Hiện nhiều trường hợp hệ thống sẽ degrade âm thầm thay vì fail loud.

**Docs xác nhận**

- Nếu AI provider/Qdrant/Postgres có vấn đề, hệ thống có thể rơi sang mock, memory, hoặc file fallback.
- `/health` có `degraded_reasons`, nhưng service vẫn chạy.
- Hardening backlog đã nêu cần cân nhắc trả `503` thay vì `200 degraded`.

**Suy luận hợp lý**

- Với production thật, nhiều fallback hiện tại quá nguy hiểm vì làm caller nghĩ rằng hệ thống còn usable trong khi semantic quality hoặc durability đã hỏng.

**Thiếu/chưa chốt**

- Chưa có failure policy chính thức cho từng dependency:
  - dependency nào được degrade,
  - dependency nào phải fail closed,
  - dependency nào được retry bao lâu.

## 10. Nếu dữ liệu sai thì sao?

**Kết luận ngắn:** Docs nhận ra vấn đề truy vết, nhưng chưa có cơ chế data-quality control đầy đủ.

**Docs xác nhận**

- Hệ thống muốn giữ lineage `source -> markdown -> section -> caption -> vector -> search result`.
- Cần log `parser_version`, `caption_model`, `embedding_model`.
- Cần khả năng kiểm tra chéo bằng `markdown_s3_uri` và `source_s3_uri`.

**Suy luận hợp lý**

- Khi dữ liệu sai, cách xử lý hiện tại thiên về debug và re-ingest, chưa phải data governance hoàn chỉnh.
- Sai có thể đến từ parser, splitter, captioner, embedding model, hoặc stale index.

**Thiếu/chưa chốt**

- Không có rule rõ cho quarantine, validation threshold, human review, rollback artifact, hay reprocess selective.

## 11. Nếu dữ liệu trễ thì sao?

**Kết luận ngắn:** Đây là risk đã được nhận diện, nhưng chưa có SLO freshness.

**Docs xác nhận**

- Scanner chạy theo interval; latency tối đa phụ thuộc scan interval.
- `STALE_INDEXING_SECONDS` chỉ giảm nguy cơ stuck job, không giải quyết triệt để failure chain.
- Freshness/version là thứ nên theo dõi.

**Suy luận hợp lý**

- Nếu dữ liệu trễ, search sẽ trả section cũ nhưng caller khó biết nếu không nhìn metadata/versioning.
- Với high-frequency upload, scanner hiện tại sẽ thành choke point thực sự.

**Thiếu/chưa chốt**

- Không có SLO kiểu "document mới phải searchable trong X phút".
- Không có alerting rõ cho freshness lag.

## 12. 1 năm nữa thay đổi gì?

**Kết luận ngắn:** Trong 1 năm, thứ nhiều khả năng thay là implementation strategy chứ không phải workflow lõi.

**Khả năng cao sẽ thay**

- Provider AI, model caption, model embedding.
- Scan strategy: từ polling sang event-driven.
- Search filter surface.
- Sectioning heuristics, max section guard, caching, retry/backoff.
- Observability, metrics, access metadata, versioning.

**Ít khả năng thay**

- Luồng cấp cao `source -> markdown -> sections -> captions -> vectors -> search`.
- Nhu cầu giữ canonical markdown artifact và lineage về source.

## 13. 3 năm nữa thay đổi gì?

**Kết luận ngắn:** 3 năm nữa khả năng lớn sẽ đổi cả storage/backend strategy, governance và integration contract.

**Khả năng cao sẽ thay**

- Vector backend, metadata backend, storage topology.
- Permission/access-control metadata integration.
- Reindex/migration strategy theo model version.
- Multi-tenant, tenant isolation, compliance logging.
- API contract để hỗ trợ filter, citation chi tiết hơn, hoặc hybrid retrieval.

**Khả năng vẫn nên giữ**

- Canonical artifact.
- Section-centric retrieval unit hoặc một biến thể semantic unit gần nghĩa.
- Clean architecture boundaries: domain/application/ports/infrastructure.

## 14. Module nào phải ổn định?

**Kết luận ngắn:** Domain contract, data lineage contract và orchestration shape phải ổn định.

**Phải ổn định**

- `IngestJob`, `MarkdownDocument`, `SectionRecord`, `SectionSearchResult`, `DocumentRecord`.
- Search response lineage fields: `section_content`, `caption`, `markdown_s3_uri`, `source_s3_uri`.
- Port contracts giữa application và infrastructure.
- Quy tắc dependency direction và composition root.
- Trạng thái document/job và metadata version fields.

Lý do: đây là phần nhiều team khác sẽ tích hợp vào; thay đổi bừa sẽ làm vỡ caller, test, và vận hành.

## 15. Module nào được phép thay đổi?

**Kết luận ngắn:** Strategy và adapter nên được phép thay nhanh.

**Được phép thay đổi**

- Parser strategies theo format.
- Splitter heuristics.
- Caption provider/prompting/caching/retry policy.
- Embedding provider/model.
- Vector store implementation.
- Metadata store implementation.
- Scan strategy.
- Logging/metrics implementation details.

Lý do: đây là nơi hệ thống cần học nhanh từ production và thích nghi với cost, scale, model, và infra.

## 16. Chỗ nào leverage cao nhất?

**Kết luận ngắn:** Có 4 điểm leverage cao nhất.

1. **Section quality + caption quality**
   
   Nếu section sai hoặc caption sai, toàn bộ retrieval semantic sẽ lệch dù hạ tầng tốt.

2. **Failure policy cho fallback/degraded mode**
   
   Hiện risk lớn nhất là hệ thống "sống nhưng sai". Làm rõ fail-loud/fail-closed sẽ tăng độ tin cậy mạnh hơn nhiều refactor nhỏ.

3. **Scanner/freshness architecture**
   
   Nếu tài liệu mới không vào index kịp, quality cảm nhận của toàn hệ sẽ giảm dù search logic đúng.

4. **Observability + lineage**
   
   Không nhìn thấy `raw -> markdown -> section -> result` thì không sửa được lỗi retrieval một cách hệ thống.

## Tổng kết thẳng

- Requirement kỹ thuật là có thật và đã khá nhất quán.
- Requirement nghiệp vụ cuối cùng chưa được viết đủ chặt.
- Hệ thống đang tối ưu mạnh cho **khả năng retrieve section đúng và truy vết được nguồn**, chưa chứng minh được **business success**.
- Rủi ro lớn nhất hiện tại không phải thiếu thêm feature, mà là:
  - fallback âm thầm,
  - freshness chưa được chốt bằng SLO,
  - thiếu success metrics có số,
  - thiếu owner rõ cho outcome nghiệp vụ.

## Tài liệu nguồn chính

- `docs/ARCHITECTURE.md`
- `docs/PIPELINE.md`
- `docs/RISKS.md`
- `docs/REFATOR_CAPTION_SECTION_ARCHITECTURE.md`
- `docs/DE_PIPELINE_RECOMMENDATIONS.md`
- `docs/LOGGING.md`
- `docs/LEGACY.md`

# MOSA Assessment

Tài liệu này ghi lại đánh giá hiện trạng repo theo tinh thần **MOSA - Modular Open Systems Approach**.

Phạm vi review:

- cấu trúc source code
- dependency boundaries giữa các module
- mức độ mở của interface
- khả năng thay thế implementation
- độ portable của core system
- một phần deployment structure trong `k8s/`

Tài liệu này không khẳng định compliance chính thức theo một standard quân sự hay procurement framework. Nó là một **engineering assessment** dựa trên codebase hiện tại.

## Kết luận ngắn

Hệ thống hiện tại **đi đúng hướng MOSA**, nhưng **chưa đạt MOSA mạnh ở mức implementation runtime**.

Nói ngắn gọn:

- kiến trúc module hóa là thật
- contract giữa các layer đã tương đối rõ
- dependency direction nhìn chung đúng
- nhưng runtime vẫn còn phụ thuộc lớp compatibility/legacy
- và fallback hiện tại làm thay đổi behavior thực tế quá nhiều để có thể xem là "replaceable" theo nghĩa mạnh của MOSA

## MOSA là gì trong ngữ cảnh repo này

Trong ngữ cảnh repo này, MOSA không nên được hiểu máy móc là "chia nhiều folder". Nó nên được hiểu qua các câu hỏi sau:

1. Hệ thống có tách thành module rõ ràng không?
2. Các module có giao tiếp qua contract ổn định không?
3. Có thể thay một implementation mà không kéo theo sửa business flow không?
4. Có thể thay backend/provider mà không làm đổi semantics quá nhiều không?
5. Có thể thêm consumer/integration mới qua interface mở mà không đập lõi không?
6. Core system có bị buộc quá chặt vào framework hay vendor nào không?

## Những gì repo đang làm đúng với MOSA

## 1. Module boundaries khá rõ

Repo đã tổ chức hệ thống theo các tầng có trách nhiệm khác nhau:

```text
app/
  domain/
  application/
  ports/
  infrastructure/
  bootstrap/

api/
pipeline/
retrieval/
```

Ý nghĩa thực tế:

- `app/domain/` giữ model và policy lõi
- `app/application/` giữ use case
- `app/ports/` giữ contract
- `app/infrastructure/` giữ implementation cụ thể
- `app/bootstrap/container.py` là composition root

Đây là dấu hiệu tốt theo tinh thần MOSA vì:

- caller không cần biết implementation cụ thể bên dưới
- complexity được nhốt vào module phù hợp
- thay đổi kỹ thuật có thể được cô lập tốt hơn

Nguồn:

- [docs/ARCHITECTURE.md](../ARCHITECTURE.md)
- [docs/PIPELINE.md](../PIPELINE.md)

## 2. Dependency direction nhìn chung đúng

Hướng phụ thuộc được tài liệu hóa và phần lớn code bám theo:

```text
api -> application -> ports <- infrastructure
                    ^
                 domain
```

Điểm tốt:

- use case `RunIngestJob` nhận dependency qua ports
- `SearchSections` nhận `EmbeddingProvider` và `SectionIndex`
- `GetDocumentStatus` nhận `DocumentRepository`

Ví dụ:

- [app/application/ingest/run_ingest_job.py](../../app/application/ingest/run_ingest_job.py)
- [app/application/search/search_sections.py](../../app/application/search/search_sections.py)
- [app/ports/document_parser.py](../../app/ports/document_parser.py)

Đây là một điểm rất gần MOSA vì business flow không bị cột cứng vào SDK hoặc database cụ thể.

## 3. Có composition root tương đối rõ

`app/bootstrap/container.py` đang là nơi tập trung wiring dependency cho runtime chính.

Điểm tốt:

- API layer không tự build từng dependency rời rạc
- runtime có một nơi khá rõ để chọn implementation
- use cases được inject theo mô hình có kiểm soát

Nguồn:

- [app/bootstrap/container.py](../../app/bootstrap/container.py)

Đây là điều quan trọng với MOSA vì một hệ mở cần có nơi kiểm soát assembly của các module.

## 4. Ports và data contracts đã hình thành

Repo đã có các contract tương đối rõ cho:

- parser
- reader
- markdown store
- splitter
- captioner
- embedder
- section index
- document repository
- scanner

Về mặt MOSA, đây là điểm mạnh nhất của repo hiện tại.

Nếu các contract này được giữ ổn định, hệ thống có nền tảng tốt để thay backend hoặc strategy theo thời gian.

## 5. Deployment structure cũng có tinh thần module hóa

Trong `k8s/` đã có tách:

- `base/`
- `overlays/production/`

Kustomize base/overlay là một dấu hiệu tốt vì deployment config được tổ chức theo lớp thay vì copy-paste nguyên khối.

Nguồn:

- [k8s/base/kustomization.yaml](../../k8s/base/kustomization.yaml)
- [k8s/overlays/production/kustomization.yaml](../../k8s/overlays/production/kustomization.yaml)

## Những gì repo chưa đạt theo tinh thần MOSA

## 1. Runtime chính vẫn còn phụ thuộc lớp compatibility/legacy

Đây là gap lớn nhất.

Mặc dù docs nói `utils/` chỉ là backward-compat re-export layer và code mới không nên phụ thuộc vào đó, runtime chính vẫn dùng:

- `utils.ai_provider`
- `utils.stores`

trong composition root:

- [app/bootstrap/container.py](../../app/bootstrap/container.py)

Vấn đề theo góc nhìn MOSA:

- lớp compatibility tạm thời đang nằm trên đường chạy chính
- architecture target và runtime implementation chưa khớp hoàn toàn
- contract chính thức và contract tạm thời đang cùng tồn tại

Điều này làm hệ thống bớt "open" và bớt "cleanly replaceable" hơn mức docs đang mô tả.

## 2. Một số module mới chỉ là wrapper cho legacy implementation

Hai ví dụ rõ:

### Scanner

`app/infrastructure/scanning/s3_source_scanner.py` chỉ wrap `adapters.s3_adapter.S3Scanner`.

Nguồn:

- [app/infrastructure/scanning/s3_source_scanner.py](../../app/infrastructure/scanning/s3_source_scanner.py)

### Parser

`RouterDocumentParser` vẫn gọi sang `pipeline.parsers`.

Nguồn:

- [app/infrastructure/parser/router.py](../../app/infrastructure/parser/router.py)

Theo MOSA, wrapper không sai. Nhưng nếu wrapper chỉ đổi tên mà không thật sự tách ownership và contract semantics ra khỏi legacy stack, thì mức module independence vẫn còn thấp.

## 3. Replaceability có, nhưng behavioral equivalence chưa mạnh

Repo có thể thay các implementation như:

- Qdrant -> in-memory vector store
- SQL metadata -> file metadata store
- OpenAI -> mock provider

Điều này cho thấy có modularity.

Nhưng theo MOSA mạnh, thay implementation không chỉ là "chạy được", mà còn phải giữ behavior ở mức chấp nhận được cho cùng operational intent.

Hiện trạng:

- `MockAIProvider` làm mất semantic quality
- `InMemoryVectorStore` làm mất durability
- `FileMetadataStore` có behavior khác production backend

Nguồn:

- [utils/ai_provider.py](../../utils/ai_provider.py)
- [utils/stores.py](../../utils/stores.py)
- [docs/RISKS.md](../RISKS.md)

Kết luận ở đây:

- hệ thống **modular**
- nhưng chưa **interchangeable with stable operational semantics**

Đó là một khác biệt quan trọng nếu đánh giá theo tinh thần MOSA.

## 4. External interfaces chưa đủ mở

Hiện tại surface chính của hệ thống là:

- `POST /search`
- `POST /scan`
- `GET /status/{doc_id}`
- `GET /health`

Nguồn:

- [api/main.py](../../api/main.py)

Vấn đề:

- `/search` chưa có filter contract đầy đủ
- ingest surface vẫn thiên về S3 scanner thay vì nhiều kiểu integration
- docs cũng thừa nhận có schema gap với các consumer khác

Nguồn:

- [docs/DE_PIPELINE_RECOMMENDATIONS.md](./DE_PIPELINE_RECOMMENDATIONS.md)

Theo MOSA, hệ mở cần interface đủ rõ và đủ mở để nhiều hệ khác có thể tích hợp mà không ép sửa lõi.

Repo hiện mới đạt mức này một phần.

## 5. Domain core chưa hoàn toàn framework-neutral

Domain models hiện dùng `pydantic.BaseModel`.

Nguồn:

- [app/domain/documents/models.py](../../app/domain/documents/models.py)

Điều này không phải bug.

Nhưng nếu soi theo MOSA/portability nghiêm ngặt:

- core domain đang gắn vào một framework validation/serialization cụ thể
- portability của domain layer chưa tối đa

Thực tế đây là tradeoff hợp lý cho tốc độ phát triển, nhưng vẫn là điểm lệch nếu mục tiêu là "modular open system" rất chặt.

## 6. Fallback policy hiện nghiêng về degrade âm thầm

MOSA không chỉ nói về module boundaries; nó cũng liên quan đến việc module thay thế phải có operational behavior được kiểm soát rõ.

Hiện repo có xu hướng:

- fallback sang implementation khác
- tiếp tục chạy
- expose degraded reason qua health

Nguồn:

- [app/bootstrap/container.py](../../app/bootstrap/container.py)
- [docs/RISKS.md](../RISKS.md)

Điểm mạnh:

- hệ thống không chết ngay

Điểm yếu:

- caller có thể vẫn dùng hệ thống trong trạng thái semantics đã lệch nhiều
- quality degradation chưa được chặn đủ mạnh

Với MOSA, đây là dấu hiệu interface thay được nhưng mission behavior chưa được kiểm soát chặt.

## Đánh giá theo từng nguyên tắc

## 1. Modularity

**Đánh giá:** tốt

Lý do:

- có phân tầng rõ
- có use case riêng
- có ports riêng
- có infrastructure riêng

## 2. Separation of concerns

**Đánh giá:** tốt

Lý do:

- parse, split, caption, embed, index, search đã được tách
- API không ôm toàn bộ business flow
- orchestration nằm trong application layer

## 3. Open interfaces

**Đánh giá:** trung bình

Lý do:

- internal contracts khá tốt
- external API contract còn hẹp
- một số integration assumptions vẫn S3-centric

## 4. Replaceability

**Đánh giá:** yếu đến trung bình

Lý do:

- thay implementation được
- nhưng behavior sau khi thay không tương đương đủ mạnh
- fallback hiện tại làm semantics lệch đáng kể

## 5. Portability

**Đánh giá:** trung bình

Lý do:

- core không gắn trực tiếp vào Qdrant/OpenAI/Postgres ở application layer
- nhưng runtime vẫn còn kéo qua compatibility layer
- domain vẫn phụ thuộc Pydantic

## 6. Evolution over time

**Đánh giá:** khá

Lý do:

- structure hiện tại có khả năng mở rộng thêm adapter/provider mới
- docs đã nghĩ tới versioning, access metadata, filters, observability
- nhưng migration khỏi legacy path chưa hoàn tất

## Những điểm leverage cao nhất để tiến gần MOSA hơn

## P0. Đưa compatibility layer ra khỏi runtime chính

Mục tiêu:

- `app/bootstrap/container.py` không còn build runtime qua `utils.*`
- compatibility chỉ còn phục vụ wrapper/tests cũ

Tác động:

- runtime bám đúng kiến trúc target
- giảm ambiguity giữa "cái đang chạy thật" và "cái còn giữ để migrate"

## P1. Làm rõ failure policy cho từng implementation thay thế

Mục tiêu:

- dependency nào được fallback
- dependency nào phải fail fast
- dependency nào chỉ được dùng ở dev/test

Tác động:

- replaceability có kiểm soát hơn
- không còn nhầm "module thay được" với "behavior vẫn chấp nhận được"

## P2. Nâng scanner/parser từ wrapper lên module ownership thật

Mục tiêu:

- scanner port có implementation thật sự thuộc `app/infrastructure/`
- parser runtime không còn phụ thuộc legacy entrypoint như bridge lâu dài

Tác động:

- module independence tăng rõ
- giảm leakage từ legacy stack sang kiến trúc mới

## P3. Mở rộng interface công khai

Mục tiêu:

- thêm filter contract cho `/search`
- chuẩn hóa ingest integration options
- làm rõ public integration model cho consumer khác nhau

Tác động:

- hệ thống "open" hơn theo nghĩa tích hợp hệ khác

## P4. Làm domain portable hơn nếu cần chuẩn cao hơn

Mục tiêu:

- cân nhắc tách domain khỏi framework-specific validation nếu sau này portability là yêu cầu cứng

Tác động:

- lợi cho long-term portability
- nhưng không nên làm sớm nếu chưa có nhu cầu thật

## Kết luận cuối

Repo hiện tại có thể được mô tả chính xác như sau:

- **modular by design**
- **partially open by interface**
- **not yet strongly interchangeable at runtime**

Hay nói dễ hiểu hơn:

- kiến trúc đã đi đúng hướng MOSA
- nhưng implementation thực tế vẫn còn transitional
- và mức thay thế module an toàn trong production chưa đủ mạnh để gọi là MOSA rất tốt

Nếu cần một câu kết ngắn:

> Hệ thống này giống MOSA về hình thái kiến trúc, nhưng chưa đạt MOSA mạnh về runtime behavior và module independence.

## File tham chiếu chính

- [docs/ARCHITECTURE.md](../ARCHITECTURE.md)
- [docs/PIPELINE.md](../PIPELINE.md)
- [docs/RISKS.md](../RISKS.md)
- [docs/DE_PIPELINE_RECOMMENDATIONS.md](./DE_PIPELINE_RECOMMENDATIONS.md)
- [app/bootstrap/container.py](../../app/bootstrap/container.py)
- [app/application/ingest/run_ingest_job.py](../../app/application/ingest/run_ingest_job.py)
- [app/application/search/search_sections.py](../../app/application/search/search_sections.py)
- [app/infrastructure/scanning/s3_source_scanner.py](../../app/infrastructure/scanning/s3_source_scanner.py)
- [app/infrastructure/parser/router.py](../../app/infrastructure/parser/router.py)
- [utils/stores.py](../../utils/stores.py)
- [utils/ai_provider.py](../../utils/ai_provider.py)

# Kiến Trúc Refactor - Markdown, Section, Caption Retrieval

Tài liệu này mô tả hướng refactor mới cho repo theo mục tiêu sản phẩm đã chốt:

- Chuyển mọi tài liệu về Markdown làm đầu ra chuẩn
- Chia tài liệu thành các section hoàn chỉnh theo heading
- Sinh caption 2-3 câu cho mỗi section
- Embed caption thay vì embed chunk text
- Search theo caption, trả về `section_content` đầy đủ kèm `caption` và `markdown_s3_uri`

Tài liệu này dùng làm nền để thiết kế, review và lập kế hoạch refactor. Nó không mô tả pipeline chunk 512 token hiện tại như kiến trúc đích; hướng đó được xem là kiến trúc cũ.

## 1. Mục tiêu sản phẩm

Hệ thống mới phục vụ chatbot nội bộ và AI team theo mô hình:

1. Tài liệu gốc (`.pdf`, `.docx`, `.html`, image, ...) được parse thành Markdown
2. Markdown được lưu ở output storage và trở thành canonical representation
3. Markdown được tách thành các section có nghĩa hoàn chỉnh
4. Mỗi section có một caption ngắn để biểu diễn ý nghĩa
5. Vector search dựa trên caption embedding
6. Kết quả trả về là full section, không phải mảnh text bị cắt

Mục tiêu của thay đổi này:

- Tăng chất lượng retrieval cho câu hỏi cụ thể
- Giảm tình trạng context bị cắt giữa câu hoặc giữa ý
- Cho AI team đọc nhanh qua `caption`
- Luôn có đường dẫn quay lại full markdown nếu cần thêm context

## 2. Vấn đề của kiến trúc chunk hiện tại

Kiến trúc cũ hiện đang là:

`parse -> clean -> chunk 512 token -> embed chunk -> index chunk -> search chunk`

Nó có các nhóm vấn đề sau:

### 2.1. Đơn vị retrieve không phù hợp

- Chunk token là đơn vị kỹ thuật, không phải đơn vị nghĩa
- Một policy có thể bị cắt thành 2-3 chunk
- Search dùng từ khóa có thể trả về mảnh văn bản thiếu đầu, thiếu đuôi

### 2.2. AI team nhận context khó dùng

- Kết quả search chỉ có text chunk
- Team phải tự phục hồi context xung quanh
- Không có `full section` và không có `full markdown` làm đường lui rõ ràng

### 2.3. File dài bị xử lý kém hiệu quả

- File 100-200 trang sinh ra rất nhiều chunk kỹ thuật
- Retrieval dễ khớp theo token overlap hơn là theo ý nghĩa section
- Không có layer tóm tắt semantic ở mức section

### 2.4. Kiến trúc parser đang dở dang

Repo hiện có 2 nhánh parser:

- `pipeline/01_parse.py` đang được runtime gọi thật
- `pipeline/parsers/` là hướng parser mới đang được test

Cần có một target architecture rõ ràng để hợp nhất parser và retrieval model.

## 3. Kiến trúc đích đã chốt

Kiến trúc mới vẫn giữ luồng ingestion tổng quát, nhưng đổi retrieval unit:

```text
Source file
    ->
Parse to Markdown
    ->
Store Markdown
    ->
Split Markdown by heading
    ->
Generate section captions
    ->
Embed captions
    ->
Index section records
    ->
Search by caption vector
    ->
Return section_content + caption + markdown_s3_uri
```

Đơn vị trung tâm mới:

- `File`: tài liệu gốc
- `Markdown`: văn bản chuẩn của file sau parse
- `Section`: đơn vị tri thức để retrieve
- `Caption`: đơn vị semantic để embed

## 4. Nguyên tắc thiết kế

Refactor sẽ đi theo hướng clean architecture nhẹ, đủ thực dụng cho repo hiện tại:

### 4.1. Giữ business flow, đổi cách tổ chức code

Không đổi mục tiêu xử lý tài liệu.
Chỉ đổi:

- đơn vị retrieval
- contract giữa các module
- cách wiring dependency
- schema và index payload

### 4.2. Markdown là canonical output

Sau parse, pipeline không làm việc trên raw bytes nữa.
Toàn bộ downstream sẽ dựa trên Markdown:

- split section
- caption
- indexing metadata
- trace và debug

### 4.3. Section là retrieval unit

Search không trả chunk token nữa.
Search trả section hoàn chỉnh để caller có context đầy đủ.

### 4.4. Caption là embedding unit

Embedding dùng cho vector search phải biểu diễn ý nghĩa section, không phải copy toàn bộ raw section text.

### 4.5. Full markdown luôn là fallback context

Mỗi section phải giữ liên kết về full markdown:

- để AI team đọc rộng hơn nếu cần
- để debug kết quả retrieval
- để hỗ trợ các use case tổng hợp sau này

## 5. Áp dụng SOLID vào repo này

Phần này chốt cách hiểu SOLID theo đúng bối cảnh của repo, để refactor không rơi vào việc chỉ tách thư mục nhưng vẫn giữ coupling cũ.

### 5.1. `S` - Single Responsibility Principle

Mỗi module chỉ nên có một lý do để thay đổi.

Áp dụng vào repo này:

- parser chỉ chịu trách nhiệm `file -> markdown`
- section splitter chỉ chịu trách nhiệm `markdown -> sections`
- captioner chỉ chịu trách nhiệm `section -> caption`
- embedder chỉ chịu trách nhiệm `text -> vector`
- indexer chỉ chịu trách nhiệm ghi section records vào index
- API chỉ chịu trách nhiệm request/response
- bootstrap chỉ chịu trách nhiệm wiring dependency

Không được giữ kiểu module ôm nhiều vai trò như hiện tại:

- `pipeline/run.py` vừa orchestration, vừa biết dependency, vừa biết error flow
- `utils/stores.py` vừa interface, vừa implementation, vừa fallback policy
- `api/main.py` vừa web layer, vừa startup wiring, vừa scan coordination

### 5.2. `O` - Open/Closed Principle

Hệ thống phải mở để mở rộng, nhưng đóng với việc sửa code lõi không cần thiết.

Áp dụng vào repo này:

- thêm định dạng file mới bằng cách thêm parser strategy mới
- thêm cách split section mới bằng cách thêm implementation của `SectionSplitter`
- thêm provider caption/embedding mới bằng cách thêm adapter mới
- thêm vector store hoặc metadata backend mới bằng cách thêm implementation mới của port

Không nên:

- mỗi lần thêm format lại sửa orchestrator ở nhiều nơi
- mỗi lần đổi provider lại sửa business flow
- mỗi lần đổi storage lại sửa API layer

### 5.3. `L` - Liskov Substitution Principle

Các implementation của cùng một port phải thay thế cho nhau mà không làm thay đổi kỳ vọng nghiệp vụ.

Áp dụng vào repo này:

- mọi `DocumentParser` đều phải trả cùng một dạng `MarkdownDocument`
- mọi `SectionIndex` đều phải hỗ trợ ghi và search theo contract section-centric
- mọi `DocumentRepository` đều phải giữ đúng semantics về status, lookup và update

Điểm cần tránh:

- fallback implementation có hành vi khác hẳn production nhưng vẫn dùng chung contract mà không nói rõ
- parser text và parser visual trả hai kiểu output khác nhau
- search adapter này trả `section_content`, adapter khác chỉ trả `caption`

Nếu không giữ được cùng semantics, phải tách contract thay vì nhét chung một interface.

### 5.4. `I` - Interface Segregation Principle

Không ép module phụ thuộc vào interface lớn hơn nhu cầu thật của nó.

Áp dụng vào repo này:

- không dùng một `MetadataStore` quá to cho mọi use case
- tách nhỏ thành các port như:
  - `DocumentRepository`
  - `JobLogRepository`
  - `IngestClaimRepository`
  - `MarkdownStore`
  - `SectionIndex`

Lý do:

- team search không cần biết job log
- team parser không cần phụ thuộc metadata update
- team scan chỉ cần lookup và claim, không cần biết vector index

### 5.5. `D` - Dependency Inversion Principle

Use case nghiệp vụ phải phụ thuộc vào abstraction, không phụ thuộc trực tiếp vào SDK hay implementation cụ thể.

Áp dụng vào repo này:

- `RunIngestJob` phụ thuộc vào `DocumentReader`, `DocumentParser`, `MarkdownStore`, `SectionSplitter`, `SectionCaptioner`, `EmbeddingProvider`, `SectionIndex`, `DocumentRepository`
- `SearchSections` phụ thuộc vào `EmbeddingProvider` và `SectionIndex`
- `api/main.py` phụ thuộc vào use case đã được dựng sẵn, không tự build Qdrant/OpenAI/Postgres

Không nên:

- để application import trực tiếp `boto3`, `openai`, `qdrant_client`, `sqlalchemy`
- để endpoint tự dựng dependency theo env
- để business rule nằm trong adapter hoặc SDK wrapper

## 6. Target response model

Kết quả search mới cần có ít nhất:

```json
{
  "section_id": "doc_123.section_0007",
  "doc_id": "doc_123",
  "caption": "Quy định về mức hoàn tiền tối đa cho vé máy bay công tác...",
  "section_content": "## Hoàn tiền vé máy bay\n...\n",
  "markdown_s3_uri": "s3://bucket/markdown/doc_123.md",
  "source_s3_uri": "s3://bucket/raw/hr/travel_policy.pdf",
  "score": 0.91
}
```

Có thể mở rộng thêm:

- `heading_path`
- `section_order`
- `document_type`
- `language`
- `token_count`

### 6.1. Quy tắc trả về context

Search API trong kiến trúc mới không chỉ trả nội dung đã xử lý, mà phải trả đủ hai lớp context:

- `markdown_s3_uri`: URI của file Markdown đã xử lý, dùng như canonical artifact
- `source_s3_uri`: URI của file raw gốc, dùng để kiểm tra chéo hoặc quay lại tài liệu nguồn khi cần chắc chắn hơn

Nguyên tắc sử dụng:

- dùng `section_content` khi caller cần context ngắn gọn, sẵn sàng cho chatbot
- dùng `markdown_s3_uri` khi caller cần đọc bản đã chuẩn hóa
- dùng `source_s3_uri` khi caller cần đối chiếu lại tài liệu gốc

## 7. Module boundaries đề xuất

Hướng đề xuất:

```text
domain/
  documents/
  markdown/
  retrieval/

application/
  ingest/
  search/
  scan/

ports/
  parser.py
  markdown_store.py
  captioner.py
  embedder.py
  vector_index.py
  document_repository.py

infrastructure/
  parser/
  ai/
  storage/
  vector/
  metadata/

bootstrap/
  container.py

api/
  main.py
```

## 8. Từng phần của thiết kế và lý do

### 7.1. `domain/`

Chứa model và rule nghiệp vụ cốt lõi:

- `SourceDocument`
- `MarkdownDocument`
- `DocumentSection`
- `SectionCaption`
- trạng thái ingest và index
- rule `stale indexing`
- rule validation cho section và caption payload

Lý do:

- Đây là ngôn ngữ chung của hệ thống
- Không phụ thuộc OpenAI, Qdrant, FastAPI, S3
- Nhiều team cùng có thể dựa vào một model ổn định

### 7.2. `application/`

Chứa các use case:

- `RunIngestJob`
- `SearchSections`
- `ScanSourceDocuments`
- `GetDocumentStatus`

Lý do:

- Hiện tại orchestrator đang bị dồn vào `pipeline/run.py`
- Cần một nơi duy nhất mô tả hệ thống làm gì
- Đây là tầng backend nghiệp vụ, độc lập với framework và provider

### 8.3. `ports/`

Chứa contract rõ ràng giữa use case và hạ tầng:

- `DocumentReader`
- `DocumentParser`
- `MarkdownStore`
- `SectionSplitter`
- `SectionCaptioner`
- `EmbeddingProvider`
- `SectionIndex`
- `DocumentRepository`
- `JobLogRepository`
- `IngestClaimRepository`

Lý do:

- Team parser, AI, storage, search có thể làm việc song song
- Unit test có thể mock ports thay vì mock SDK
- Dễ thay implementation mà không sửa use case
- Bám sát Interface Segregation: mỗi use case chỉ nhận đúng abstraction nó cần

### 7.4. `infrastructure/`

Chứa implementation thật:

- MarkItDown parser
- OpenAI/OpenRouter captioner
- OpenAI embedding provider
- S3/local markdown store
- Qdrant section index
- Postgres/file metadata store

Lý do:

- Cô lập SDK và logic vendor-specific
- Cho phép thay đổi hạ tầng mà không chạm vào application layer

### 7.5. `bootstrap/`

Là nơi duy nhất wiring dependency theo environment.

Lý do:

- `api/main.py` không nên tự build provider, store, service
- Giảm coupling và merge conflict
- Local/test/prod có thể dùng implementation khác nhau

### 7.6. `api/`

Chỉ làm:

- validate request
- gọi use case
- map response

Không nên làm:

- orchestration ingest
- build dependency
- chứa policy business

## 9. Refactor parser theo mục tiêu mới

Parser target không còn là `bytes -> pages -> clean -> chunk`.
Parser target là:

`bytes + suffix -> markdown`

Đề xuất:

```text
infrastructure/parser/
  router.py
  text_markdown_parser.py
  visual_markdown_parser.py
```

### Parser router

Trách nhiệm:

- nhận `file_bytes`, `suffix`
- quyết định parser strategy nào được dùng
- trả về `MarkdownDocument`

### Text parser

Dùng cho:

- `.txt`, `.md`, `.html`, `.htm`, `.ipynb`, code/data text formats

### Visual parser

Dùng cho:

- `.pdf`, `.docx`, `.pptx`, `.xlsx`, image, các file có text và visual

Lưu ý:

- Repo hiện đã có `pipeline/parsers/_text.py` và `_visual.py`
- Hướng đúng là tận dụng nhánh parser mới này, hợp nhất nó thành parser runtime chính thức
- `pipeline/01_parse.py` sau cùng phải bị loại bỏ hoặc biến thành wrapper tạm thời

## 10. Pipeline ingest mới

Use case `RunIngestJob` target:

```text
1. Read source file
2. Parse file -> markdown
3. Store markdown
4. Split markdown -> sections
5. Generate captions
6. Embed captions
7. Index sections
8. Update document/job status
```

Use case này là nơi orchestration duy nhất, nhưng bản thân nó không chứa SDK-specific logic.
Đây là điểm áp dụng trực tiếp Dependency Inversion và Single Responsibility:

- orchestration ở application layer
- implementation chi tiết nằm sau các ports

### 9.1. Read source file

Dùng `DocumentReader`.

Có thể đọc từ:

- S3 raw bucket
- local dev path

### 9.2. Parse to markdown

Dùng parser đã hợp nhất.

Output mong muốn:

- `markdown_text`
- `source metadata`
- `language` nếu parser xác định được

### 9.3. Store markdown

Markdown phải được lưu thành artifact riêng.

Ví dụ key:

- `s3://bucket/processed-markdown/{doc_id}.md`

Lý do:

- retrieval phải có `markdown_s3_uri`
- để debug parser output
- để cập nhật caption/index mà không cần parse lại file gốc trong một số trường hợp

### 9.4. Split markdown into sections

Rule-based, không dùng LLM.

Nguyên tắc:

- split theo heading Markdown
- có fallback cho file không có heading rõ ràng
- đảm bảo section không quá ngắn và không bị vô nghĩa

Output mỗi section cần có:

- `section_id`
- `doc_id`
- `heading`
- `heading_path`
- `order`
- `section_content`

### 9.5. Generate captions

Mỗi section được sinh 1 caption 2-3 câu.

Caption cần:

- tóm tắt đúng ý nghĩa
- ưu tiên thông tin chính sách, rule, limit, điều kiện
- không cần copy nguyên section

Captioner là port riêng vì:

- dễ thay prompt và provider
- dễ test và batch hơn

### 9.6. Embed captions

Embedding target:

- caption text

Không phải:

- raw section content
- full markdown

Lý do:

- caption đã nén ý nghĩa section
- vector index gọn hơn và semantic rõ hơn

### 9.7. Index sections

Mỗi section trở thành 1 record trong index:

- vector = caption embedding
- payload = section metadata + section content + uri

Qdrant payload tối thiểu:

- `section_id`
- `doc_id`
- `caption`
- `section_content`
- `markdown_s3_uri`
- `source_s3_uri`
- `heading`
- `heading_path`
- `section_order`
- `document_type`
- `language`

### 9.8. Update status

Metadata store cần track:

- source document
- markdown artifact
- section count
- ingest status
- latest embedding model
- latest caption model

## 11. Search flow mới

Use case `SearchSections` target:

```text
query
  ->
embed query
  ->
vector search trên caption embeddings
  ->
return top matched sections
```

Response không còn là chunk:

- `section_content`
- `caption`
- `markdown_s3_uri`
- `source_s3_uri`
- `score`
- `doc_id`

Nguyên tắc phục vụ trong search:

- `section_content` là context chính để caller dùng ngay
- `markdown_s3_uri` là đường dẫn tới bản Markdown đã xử lý
- `source_s3_uri` là đường dẫn tới file raw gốc để caller kiểm tra chéo khi cần chắc chắn hơn

Optional future improvements:

- rerank bằng section content
- filter theo `document_type`
- filter theo path/prefix/owner

## 12. Mapping từ code hiện tại sang target

### Giữ lại về mặt ý tưởng

- `api/main.py` vẫn là boundary HTTP
- `adapters/s3_adapter.py` vẫn là scanner đầu vào
- `retrieval/service.py` vẫn là seed cho search use case
- `utils/storage.py` vẫn là nơi đọc file source

### Cần đổi mới

- `pipeline/01_parse.py`
  -> đổi thành parser markdown hợp nhất hoặc bị thay thế

- `pipeline/02_clean.py`
  -> clean text kiểu chunk không còn là trung tâm; có thể chuyển thành helper parser markdown

- `pipeline/03_chunk.py`
  -> thay bằng `split_sections.py`

- `pipeline/04_embed.py`
  -> embed captions thay vì embed chunk contents

- `pipeline/05_index.py`
  -> index section records thay vì chunk records

- `models/ingest_job.py`
  -> mở rộng model cho markdown, section, caption metadata

- `utils/stores.py`
  -> tách nhỏ contract, bỏ góc nhìn chunk-centric, bỏ interface phình to vi phạm ISP

### Cần loại bỏ sau khi migration xong

- retrieval schema cũ dựa trên `chunk_id`
- logic page/token metadata phục vụ chunk sliding window
- tests chỉ verify chunk retrieval cũ

## 13. Team boundaries sau refactor

### Team Parser

Scope:

- markdown parser router
- text parser
- visual parser
- parser quality tests

Không cần sửa:

- Qdrant
- API search
- metadata persistence

### Team Retrieval/Search

Scope:

- section index payload
- caption embedding search
- ranking và threshold
- search response schema

Không cần sửa:

- scanner
- parser implementation

### Team AI

Scope:

- caption generation prompt
- caption batching
- embedding model strategy
- quality eval retrieval

Không cần sửa:

- S3 scanner
- FastAPI wiring

### Team Platform

Scope:

- S3/raw và markdown storage
- Postgres schema
- Qdrant setup
- dependency bootstrap

Không cần sửa:

- parser rules
- caption prompt contents

### Team API

Scope:

- endpoints
- request/response model
- auth/rate limit sau này

Không cần sửa:

- parser internals
- vector index internals

## 14. Các phase refactor đề xuất

### Phase 0 - Khóa target contracts

Mục tiêu:

- chốt search response mới
- chốt section payload
- chốt markdown artifact URI convention
- chốt luôn các ports nhỏ theo SOLID, không để refactor nửa chừng vẫn giữ interface cũ

Deliverables:

- tài liệu này
- mock JSON examples
- schema decisions

### Phase 1 - Hợp nhất parser thành Markdown entrypoint

Mục tiêu:

- runtime dùng parser mới
- `pipeline/parsers/` trở thành parser path chính
- output là Markdown text

Chưa đổi retrieval ngay ở phase này.

### Phase 2 - Tạo section split layer

Mục tiêu:

- thay `03_chunk.py` bằng section splitter
- bổ sung model `DocumentSection`
- test split by heading

### Phase 3 - Thêm caption generation

Mục tiêu:

- mỗi section có caption
- test quality, caching, retry
- metadata lưu được caption model

### Phase 4 - Đổi embedding và index schema

Mục tiêu:

- embed caption
- Qdrant lưu section payload mới
- bỏ chunk-centric payload

### Phase 5 - Đổi retrieval API

Mục tiêu:

- `/search` trả section-centric response
- update tests, docs, clients

### Phase 6 - Cleanup và hardening

Mục tiêu:

- xóa dead code chunk-specific
- tách contracts, store, bootstrap
- bỏ parser cũ
- bỏ page/token metadata nếu không còn dùng

## 15. Các rủi ro cần quản lý

### 14.1. Caption sai ý

Nếu caption tóm tắt sai, retrieval semantic sẽ lệch.

Cần:

- prompt ổn định
- review sample output
- có khả năng fallback đọc section content đầy đủ

### 14.2. Section split kém

Nếu heading split không tốt, section có thể quá dài hoặc quá ngắn.

Cần:

- rule-based splitter có fallback
- test trên bộ tài liệu thật

### 14.3. Migration dữ liệu index

Index cũ đang chunk-based.
Cần quyết định:

- tạo collection mới
- hoặc reindex toàn bộ collection cũ

Không nên mix chunk payload và section payload trong cùng một schema mà không version.

### 14.4. Chi phí tăng do caption generation

Mỗi section cần 1 caption.
Cần:

- batch hợp lý
- cache theo checksum markdown hoặc section
- chỉ caption lại khi nội dung section thay đổi

## 16. Thiết kế Modular Process tối đa

Mục tiêu của phần này là biến pipeline thành một quy trình tháo lắp được, để:

- thêm loại tài liệu mới mà không phải sửa luồng lõi
- thay provider hoặc storage mà không phải sửa use case
- cho nhiều team làm việc song song ít đụng nhau nhất
- vận hành và debug từng bước độc lập

### 16.1. Giữ lõi pipeline thật mỏng

Lõi pipeline chỉ nên giữ workflow chuẩn:

```text
read source
  ->
parse -> markdown
  ->
store markdown
  ->
split -> sections
  ->
caption sections
  ->
embed captions
  ->
index sections
  ->
update status
```

Lõi này không nên biết:

- PDF parse bằng thư viện gì
- caption gọi OpenAI hay provider khác
- Qdrant hay backend nào đang dùng
- section split bằng rule nào

Ý nghĩa:

- workflow ổn định
- implementation có thể thay được
- toàn bộ hệ thống dễ mở rộng mà không vỡ orchestration

### 16.2. Mỗi bước là một port độc lập

Để tháo lắp tối đa, mỗi bước phải là một capability riêng với contract nhỏ:

- `DocumentReader`
- `DocumentParser`
- `MarkdownStore`
- `SectionSplitter`
- `SectionCaptioner`
- `EmbeddingProvider`
- `SectionIndex`
- `DocumentRepository`
- `JobLogRepository`
- `IngestClaimRepository`

Nguyên tắc:

- một port chỉ mô tả một năng lực
- không gộp nhiều concern vào cùng một interface lớn
- use case nào cần gì thì chỉ inject đúng abstraction đó

Ví dụ:

- parser không được kiêm luôn lưu markdown
- captioner không được kiêm luôn embed
- indexer không được kiêm luôn update status document

### 16.3. Chuẩn hóa input/output giữa các bước

Pipeline chỉ modular thật sự nếu dữ liệu đi giữa các bước được chuẩn hóa.

Các model trung gian nên ổn định:

- `SourceDocument`
- `MarkdownDocument`
- `DocumentSection`
- `SectionCaption`
- `SectionEmbedding`
- `IndexedSection`

Nguyên tắc:

- parser nào cũng phải trả `MarkdownDocument`
- splitter nào cũng phải nhận `MarkdownDocument` và trả `list[DocumentSection]`
- captioner nào cũng phải nhận `DocumentSection` và trả `SectionCaption`
- embedder nào cũng phải nhận caption text và trả vector
- indexer nào cũng phải nhận section record hoàn chỉnh

Lợi ích:

- thay implementation không đổi workflow
- test contract được viết một lần và dùng lại cho nhiều implementation
- dễ debug vì mỗi bước có kiểu dữ liệu rõ ràng

### 16.4. Dùng registry thay vì `if/else` cứng

Để hỗ trợ nhiều loại tài liệu sau này, không nên để routing hardcode rải trong flow.

Nên có registry cho parser:

```text
parser registry
  .pdf   -> PdfMarkdownParser
  .docx  -> DocxMarkdownParser
  .pptx  -> PptxMarkdownParser
  .xlsx  -> XlsxMarkdownParser
  .html  -> HtmlMarkdownParser
  .png   -> ImageMarkdownParser
```

Cũng có thể áp dụng registry cho:

- splitter strategy
- caption strategy
- embedding provider
- index backend

Nguyên tắc:

- core không biết implementation cụ thể
- mở rộng bằng đăng ký module mới
- hạn chế sửa code lõi khi thêm năng lực mới

### 16.5. Thiết kế theo document family, không chỉ theo file extension

Để mở rộng bền hơn, nên nhóm tài liệu theo family:

- `text-like`
  - `.txt`, `.md`, `.html`, `.xml`, `.json`
- `office-like`
  - `.docx`, `.pptx`, `.xlsx`
- `pdf-like`
  - `.pdf`
- `image-like`
  - `.png`, `.jpg`, `.jpeg`, `.tiff`

Ý nghĩa:

- sau này thêm `.odt`, `.odp`, `.ods` chỉ cần map vào family phù hợp
- giảm số lượng rule đặc biệt theo từng extension
- parser strategy dễ tái sử dụng hơn

### 16.6. Mỗi bước phải chạy độc lập được

Muốn vận hành hiệu quả, pipeline phải cho phép chạy lại từng bước mà không cần chạy lại toàn bộ.

Ví dụ cần hỗ trợ:

- parse lại file để sinh markdown mới
- split lại markdown mà không parse lại file gốc
- caption lại sections mà không split lại
- embed lại captions mà không caption lại
- reindex lại từ artifact đã có mà không ingest lại từ đầu

Đây là lý do phải lưu artifact trung gian:

- markdown artifact
- section artifact hoặc section metadata
- caption artifact hoặc caption payload

Lợi ích:

- debug nhanh
- giảm chi phí chạy lại
- rollback hoặc migrate dễ hơn
- phục vụ reprocessing hàng loạt khi đổi model

### 16.7. Mỗi bước phải có test contract riêng

Modular process không chỉ là chia file, mà còn là chia chuẩn kiểm thử.

Nên có các nhóm test:

- parser contract tests
- splitter contract tests
- captioner contract tests
- index contract tests
- retrieval contract tests

Ví dụ:

- mọi parser phải pass cùng một bộ test output `MarkdownDocument`
- mọi `SectionIndex` phải pass cùng một bộ test `upsert/search/delete`
- mọi captioner phải đảm bảo không trả caption rỗng cho section hợp lệ

Lợi ích:

- thêm module mới vẫn an toàn
- team khác nhau cùng bám một chuẩn
- giảm rủi ro integration muộn

### 16.8. Mỗi bước phải có version hoặc schema rõ ràng

Khi hệ thống lớn lên, dữ liệu trung gian cần version hóa tối thiểu.

Ví dụ:

- `MarkdownDocument v1`
- `DocumentSection v1`
- `SectionIndex payload v1`

Không cần over-engineer từ đầu, nhưng cần có chỗ để nâng version khi:

- đổi cấu trúc section
- đổi schema caption
- đổi payload Qdrant

Lợi ích:

- migration rõ ràng
- tránh mix dữ liệu cũ và mới trong cùng pipeline
- support dual-read hoặc dual-write khi cần transition

### 16.9. Chỉ một composition root

Muốn pipeline tháo lắp tốt thì việc chọn implementation phải nằm ở một chỗ.

Chỗ đó là `bootstrap/container.py`.

Nó chịu trách nhiệm:

- chọn parser registry nào
- chọn caption provider nào
- chọn embedding provider nào
- chọn index backend nào
- chọn repository nào theo môi trường

Không nên để:

- `api/main.py` tự chọn implementation
- `pipeline/run.py` tự import implementation cụ thể
- mỗi module tự quyết định fallback riêng

### 16.10. Quy trình thêm một loại tài liệu mới

Đây là tiêu chí thực tế nhất để đo mức độ modular.

Khi thêm một định dạng mới, ví dụ `.odt`, quy trình mong muốn phải là:

1. xác định document family của `.odt`
2. tạo parser implementation mới hoặc map vào parser family sẵn có
3. đăng ký parser vào registry
4. thêm test contract cho file mẫu `.odt`
5. không cần sửa `RunIngestJob`
6. không cần sửa `SearchSections`
7. không cần sửa Qdrant index schema

Nếu thêm file mới mà phải sửa nhiều nơi trong application flow, thì thiết kế chưa đủ modular.

### 16.11. Quy trình thay provider mà không vỡ hệ thống

Ví dụ đổi từ OpenAI sang provider khác cho caption hoặc embedding:

1. implement `SectionCaptioner` mới hoặc `EmbeddingProvider` mới
2. update wiring trong `bootstrap/container.py`
3. chạy lại test contract
4. không sửa parser, splitter, search use case

Nếu thay provider mà phải sửa business flow, thì hệ thống đang vi phạm Dependency Inversion.

### 16.12. Quy trình reprocess hàng loạt

Để làm việc hiệu quả với hàng nghìn tài liệu, phải support quy trình reprocess theo từng lớp:

- reparse toàn bộ file
- resplit toàn bộ markdown
- recaption toàn bộ sections
- reembed toàn bộ captions
- reindex toàn bộ records

Mỗi loại reprocess cần có input artifact rõ ràng và không phụ thuộc lại vào các bước trước nếu không cần.

Đây là chìa khóa để:

- đổi prompt caption
- đổi embedding model
- sửa split rule
- migrate schema index

### 16.13. Checklist đánh giá một module có đủ tháo lắp hay chưa

Một module mới chỉ được xem là đủ modular khi trả lời được `có` cho các câu hỏi sau:

1. Module này có đúng một trách nhiệm chính không?
2. Nó có input/output chuẩn hóa rõ ràng không?
3. Nó có thể thay bằng implementation khác qua cùng một port không?
4. Nó có thể test độc lập không?
5. Nó có thể chạy lại độc lập không?
6. Nó có buộc sửa orchestrator khi thay đổi không?

Nếu câu 6 là `có`, thì module đó vẫn đang gắn quá chặt vào core flow.

## 17. Quy tắc implementation

Trong đợt refactor này:

- Không tiếp tục dùng chunk 512 token làm retrieval unit
- Không để song song 2 parser runtime lâu dài
- Không để API search trả chunk schema cũ khi đã chuyển search mới
- Không embed raw section text nếu target đã chốt là caption-first
- Không gộp nhiều lý do thay đổi vào cùng một module mới
- Không tạo interface lớn chỉ để "trông có vẻ abstraction"

Cho phép transition tạm thời:

- có thể giữ wrapper compatibility trong 1-2 phase đầu
- có thể có dual-write tạm thời nếu cần migration index

## 18. Definition of done

Refactor được xem là hoàn tất khi:

1. Mỗi file ingest thành công tạo ra 1 markdown artifact
2. Mỗi markdown được split thành sections có nghĩa
3. Mỗi section có caption
4. Qdrant search trên caption vectors
5. `/search` trả `section_content + caption + markdown_s3_uri`
6. Parser runtime cũ không còn là entrypoint chính
7. Chunk-centric retrieval schema cũ được loại bỏ hoặc đóng băng rõ ràng

## 19. Các quyết định đã chốt

- Target mới là `caption -> section -> file`
- Markdown là canonical output
- Section là retrieval unit
- Caption là embedding unit
- Search response phải trả full section + markdown URI
- Refactor đi theo hướng clean architecture nhẹ
- Giữ ingestion flow tổng quát, đổi đơn vị retrieval và boundary module
- Toàn bộ thiết kế mới phải bám SOLID ở mức thực dụng, không chỉ tách thư mục hình thức

## 20. Nguyên tắc dependency direction

Đây là nguyên tắc bắt buộc để hệ thống không gãy khi thay strategy ở tầng dưới.

```text
API
  ->
Application use cases
  ->
Ports / Interfaces
  ->
Infrastructure implementations
```

Chiều phụ thuộc chỉ được đi theo một hướng:

- `api/` được phép phụ thuộc vào `application/`
- `application/` được phép phụ thuộc vào `domain/` và `ports/`
- `infrastructure/` được phép phụ thuộc vào `ports/` và `domain/`
- `domain/` không được phụ thuộc vào `application/`, `api/`, `infrastructure/`

Không được phép:

- `application/` import trực tiếp SDK như `openai`, `boto3`, `qdrant_client`
- `domain/` import FastAPI, SQLAlchemy, hoặc provider cụ thể
- `api/` tự chọn strategy xử lý tài liệu

Ý nghĩa:

- thay implementation mà không sửa use case
- business rule không bị kéo lệch theo vendor
- module dễ test và dễ thay thế hơn

## 21. Bảng chuẩn: pipeline step -> interface -> strategy

Mỗi bước trong pipeline phải đi qua đúng một abstraction ổn định. Tầng dưới có thể đổi strategy liên tục, nhưng pipeline không được gãy.

| Pipeline step | Interface ổn định | Ví dụ strategy / implementation |
|---|---|---|
| Đọc file nguồn | `DocumentReader` | `S3DocumentReader`, `LocalDocumentReader` |
| Parse sang Markdown | `DocumentParser` | `PdfMarkdownParser`, `DocxMarkdownParser`, `ImageMarkdownParser` |
| Lưu Markdown | `MarkdownStore` | `S3MarkdownStore`, `LocalMarkdownStore` |
| Chia section | `SectionSplitter` | `HeadingSectionSplitter`, `HybridSectionSplitter` |
| Sinh caption | `SectionCaptioner` | `OpenAICaptioner`, `OpenRouterCaptioner` |
| Embed caption | `EmbeddingProvider` | `OpenAIEmbeddingProvider`, `MockEmbeddingProvider` |
| Ghi index | `SectionIndex` | `QdrantSectionIndex`, `InMemorySectionIndex` |
| Cập nhật document state | `DocumentRepository` | `PostgresDocumentRepository`, `FileDocumentRepository` |
| Claim ingest | `IngestClaimRepository` | `PostgresIngestClaimRepository`, `InMemoryIngestClaimRepository` |
| Ghi job log | `JobLogRepository` | `PostgresJobLogRepository`, `FileJobLogRepository` |

Nguyên tắc:

- pipeline chỉ gọi interface ở cột giữa
- strategy ở cột phải được phép thay đổi
- dữ liệu đi qua các bước phải giữ đúng contract

## 22. Data contracts giữa các bước

Đây là bộ contract tối thiểu nên được chuẩn hóa sớm để mọi team cùng dựa vào.

### 22.1. `SourceDocument`

Chứa thông tin file nguồn:

- `doc_id`
- `source_uri`
- `file_name`
- `file_type`
- `document_type`
- `source_last_modified`

### 22.2. `MarkdownDocument`

Chứa kết quả parse chuẩn:

- `doc_id`
- `source_uri`
- `markdown_text`
- `markdown_uri` nếu đã lưu
- `language`
- `metadata`

### 22.3. `DocumentSection`

Chứa một section hoàn chỉnh:

- `section_id`
- `doc_id`
- `heading`
- `heading_path`
- `order`
- `section_content`
- `markdown_uri`
- `source_uri`

### 22.4. `SectionCaption`

Chứa kết quả tóm tắt semantic:

- `section_id`
- `doc_id`
- `caption`
- `caption_model`

### 22.5. `SectionEmbedding`

Chứa vector của caption:

- `section_id`
- `doc_id`
- `caption`
- `embedding`
- `embedding_model`

### 22.6. `IndexedSection`

Chứa payload hoàn chỉnh để search:

- `section_id`
- `doc_id`
- `caption`
- `section_content`
- `markdown_s3_uri`
- `source_s3_uri`
- `heading`
- `heading_path`
- `section_order`
- `document_type`
- `language`

Nguyên tắc bắt buộc:

- `IndexedSection` phải luôn giữ cả `markdown_s3_uri` và `source_s3_uri`
- pipeline không được làm mất liên kết về file gốc sau khi đã sinh Markdown artifact
- search layer phải có đủ dữ liệu để trả cả bản đã xử lý và bản raw

Nguyên tắc:

- không để mỗi module tự định nghĩa shape riêng
- contract phải là nguồn sự thật chung cho parser, index, search, tests

## 23. Quản lý artifact trung gian

Để pipeline thực sự tháo lắp và reprocess được, cần coi artifact trung gian là first-class.

### 23.1. Artifact bắt buộc

- raw source document
- markdown artifact
- section artifact hoặc section metadata
- caption artifact hoặc caption payload

### 23.2. Quy tắc artifact

- mỗi artifact phải truy vết được về `doc_id`
- artifact phải có version hoặc metadata schema tối thiểu
- artifact phải có thể dùng lại để chạy bước sau mà không cần chạy lại từ đầu

### 23.3. Lợi ích

- giảm chi phí khi đổi prompt caption
- giảm chi phí khi đổi embedding model
- debug được parse/split/caption riêng lẻ
- dễ reindex hàng loạt khi đổi schema index

### 23.4. Ownership và quyền truy cập cho Markdown artifact

Với `Option 1 - Optimal`, vùng lưu Markdown artifact phải do chính team này sở hữu.

Điều đó có nghĩa là:

- bucket hoặc prefix derived dùng cho Markdown là tài sản vận hành của pipeline này
- chỉ service account hoặc ứng dụng thuộc team này có quyền `write`
- các hệ thống hoặc đội khác nếu cần sử dụng chỉ nên có quyền `read`
- không cho hệ thống bên ngoài ghi trực tiếp vào vùng Markdown artifact

Nguyên tắc này cần được giữ rõ vì:

- tránh ghi đè hoặc làm bẩn canonical Markdown
- tránh xung đột ownership với dữ liệu của đội khác
- giữ cho quá trình debug, reprocess, retention và audit rõ ràng

Mô hình quyền khuyến nghị:

- Team pipeline này: `read/write/delete` theo phạm vi vận hành đã thống nhất
- Consumer nội bộ khác: `read-only`
- Hệ thống ngoài scope: không có quyền ghi

Nói ngắn gọn:

- raw source có thể là dữ liệu dùng chung
- nhưng derived Markdown của pipeline này phải có ownership riêng
- bên ngoài chỉ đọc, không ghi

### 23.5. Các phương án triển khai storage cho Markdown artifact

Thiết kế cần hỗ trợ nhiều mức triển khai khác nhau, để hệ thống linh hoạt theo hạ tầng thực tế.

#### Option 1 - Optimal

Markdown artifact được lưu ở bucket riêng hoặc vùng lưu trữ riêng do team này sở hữu hoàn toàn.

Ví dụ:

- raw input: `s3://shared-raw-bucket/raw/...`
- markdown output: `s3://rag-derived-bucket/markdown/{doc_id}.md`

Đặc điểm:

- ownership rõ ràng
- quyền ghi chỉ thuộc team pipeline này
- hệ thống bên ngoài nếu cần chỉ được đọc
- retention, lifecycle, cleanup dễ quản lý riêng
- giảm tối đa nguy cơ xung đột với đội khác

Quyền truy cập khuyến nghị:

- team pipeline này: `read/write/delete`
- consumer nội bộ khác: `read-only`
- hệ thống ngoài scope: không có quyền ghi

Khi nào nên dùng:

- môi trường production
- hệ thống có nhiều đội cùng dùng S3
- cần audit, retention và ownership rõ

#### Option 2 - Acceptable

Markdown artifact dùng chung bucket với các đội khác, nhưng phải có prefix riêng hoàn toàn cho pipeline này.

Ví dụ:

- raw input: `s3://shared-bucket/raw/...`
- markdown output: `s3://shared-bucket/rag-derived/markdown/{doc_id}.md`

Điều kiện để option này chấp nhận được:

- prefix này thuộc ownership của team pipeline này
- không đội nào khác được ghi lẫn vào prefix đó
- naming convention ổn định và có thể truy vết theo `doc_id`
- retention hoặc lifecycle có thể áp riêng theo prefix nếu hạ tầng hỗ trợ

Đặc điểm:

- rẻ và dễ triển khai hơn Option 1
- vẫn giữ được tách biệt logic giữa raw và derived
- chấp nhận được khi chưa có điều kiện tách bucket riêng

Quyền truy cập khuyến nghị:

- team pipeline này: `read/write/delete` trong prefix được cấp
- consumer nội bộ khác: `read-only` trong prefix đó
- hệ thống ngoài scope: không có quyền ghi vào prefix

Khi nào nên dùng:

- production giai đoạn đầu
- hạ tầng chưa cho tách bucket riêng
- cần giải pháp nhanh nhưng vẫn có boundary rõ

#### Option 3 - Temporary / Dev

Markdown artifact lưu ở local filesystem, MinIO hoặc bucket test dùng cho dev/test.

Ví dụ:

- `data/processed-markdown/{doc_id}.md`
- `s3://local-dev-bucket/rag-derived/markdown/{doc_id}.md`

Đặc điểm:

- dễ setup
- phù hợp local development và integration test
- không phù hợp làm chuẩn production

Quyền truy cập:

- chủ yếu phục vụ dev/test nội bộ
- không dùng làm chuẩn ownership cho môi trường nhiều đội cùng khai thác

Khi nào nên dùng:

- local development
- CI/integration test
- giai đoạn spike hoặc thử nghiệm ban đầu

### 23.6. Nguyên tắc chọn storage option

Core pipeline không được phụ thuộc vào việc đang dùng Option 1, 2 hay 3.

Điều đó có nghĩa là:

- `RunIngestJob` chỉ biết gọi `MarkdownStore.save(...)`
- `SearchSections` chỉ biết trả `markdown_s3_uri` hoặc `markdown_uri` theo contract
- lựa chọn storage implementation phải nằm ở `bootstrap/container.py`

Không được để:

- pipeline tự kiểm tra đang dùng bucket riêng hay prefix chung
- application layer hardcode S3 path strategy
- API layer tự ghép URI markdown

### 23.7. Quy tắc ownership và retention theo từng option

#### Với Option 1

- ownership: team pipeline này sở hữu hoàn toàn
- retention: đặt lifecycle riêng cho derived Markdown
- khuyến nghị: bên ngoài chỉ đọc, không ghi

#### Với Option 2

- ownership: sở hữu theo prefix, không theo toàn bucket
- retention: nếu hạ tầng hỗ trợ, đặt lifecycle riêng cho prefix
- khuyến nghị: chỉ team này được ghi trong prefix đó

#### Với Option 3

- ownership: phục vụ dev/test, không coi là chuẩn production
- retention: tùy môi trường test, có thể xóa ngắn hạn
- khuyến nghị: không dùng làm ví dụ chuẩn cho production docs

## 24. Quy trình làm việc giữa các team

Thiết kế modular chỉ hiệu quả nếu ownership rõ ràng.

### 24.1. Team Parser

Được phép sửa:

- parser contracts liên quan tới parse
- parser strategies
- parser registry
- parser test fixtures

Không được tự ý sửa:

- search response schema
- Qdrant payload contract
- caption prompt strategy

### 24.2. Team Search

Được phép sửa:

- `SectionIndex`
- retrieval ranking
- threshold
- search response mapping

Không được tự ý sửa:

- parse logic
- markdown split rules
- source scanner behavior

### 24.3. Team AI

Được phép sửa:

- caption prompt
- caption model
- embedding provider
- evaluation logic

Không được tự ý sửa:

- section indexing schema nếu chưa thống nhất với team Search
- document repository contracts

### 24.4. Team Platform

Được phép sửa:

- S3/local readers
- markdown storage
- repository implementations
- bootstrap/container
- infra deployment

Không được tự ý sửa:

- business flow trong use cases
- parse/split/caption rules

### 24.5. Team API

Được phép sửa:

- request/response model
- endpoint wiring
- auth, rate limiting, operational endpoints

Không được tự ý sửa:

- parser strategies
- index implementations
- embedding behavior

## 25. Quy trình review PR theo thiết kế mới

Mọi PR lớn nên được review qua checklist này:

1. PR này đang thay đổi layer nào?
2. Có làm vỡ dependency direction không?
3. Có thêm responsibility mới vào module vốn không nên gánh không?
4. Có tạo interface quá lớn hoặc quá mơ hồ không?
5. Strategy mới có bám đúng contract hiện tại không?
6. Có test contract cho bước bị đổi không?
7. Có làm use case phải biết thêm implementation detail không?
8. Có yêu cầu sửa orchestrator chỉ vì thay provider/strategy không?

Nếu câu 8 là `có`, phải xem lại thiết kế.

## 26. Checklist thêm loại tài liệu mới

Khi onboarding một loại tài liệu mới, ví dụ `.odt`, checklist chuẩn phải là:

1. Xác định document family
2. Quyết định parser strategy nào xử lý
3. Nếu cần, thêm parser implementation mới
4. Đăng ký vào parser registry
5. Viết file mẫu và parser contract test
6. Xác minh output là `MarkdownDocument` hợp lệ
7. Không sửa `RunIngestJob`
8. Không sửa `SearchSections`
9. Không sửa `SectionIndex` contract

Nếu cần sửa quá các bước trên, hệ thống đang chưa modular đủ mức.

## 27. Checklist thay provider hoặc chiến lược mới

Ví dụ đổi caption provider, embedding provider, hoặc splitter strategy:

1. Giữ nguyên port hiện tại
2. Thêm implementation mới ở `infrastructure/`
3. Đăng ký/wire trong `bootstrap/container.py`
4. Chạy lại contract tests
5. Chạy sample integration test
6. Không sửa use case lõi trừ khi contract thực sự thay đổi

Đây là tiêu chí để biết Dependency Inversion có đang được giữ đúng hay không.

## 28. Cấu trúc thư mục mục tiêu chi tiết

```text
domain/
  documents/
    models.py
    statuses.py
    policies.py
  markdown/
    models.py
  sections/
    models.py
    policies.py
  retrieval/
    models.py

application/
  ingest/
    run_ingest_job.py
  search/
    search_sections.py
  scan/
    scan_source_documents.py
  status/
    get_document_status.py

ports/
  document_reader.py
  document_parser.py
  markdown_store.py
  section_splitter.py
  section_captioner.py
  embedding_provider.py
  section_index.py
  document_repository.py
  ingest_claim_repository.py
  job_log_repository.py

infrastructure/
  readers/
    s3_reader.py
    local_reader.py
  parsers/
    registry.py
    pdf_parser.py
    docx_parser.py
    html_parser.py
    image_parser.py
  stores/
    s3_markdown_store.py
    local_markdown_store.py
  splitters/
    heading_splitter.py
  captioners/
    openai_captioner.py
    mock_captioner.py
  embedders/
    openai_embedder.py
    mock_embedder.py
  indexes/
    qdrant_section_index.py
    memory_section_index.py
  repositories/
    postgres_document_repository.py
    postgres_ingest_claim_repository.py
    postgres_job_log_repository.py
    file_document_repository.py

bootstrap/
  container.py

api/
  main.py
  schemas.py
```

## 29. Trạng thái chuyển đổi từ repo hiện tại

Đây là cách hiểu thực tế khi bắt đầu refactor:

- `pipeline/run.py`
  - đang là orchestrator cũ
  - về đích sẽ bị thay bằng `application/ingest/run_ingest_job.py`

- `pipeline/parsers/`
  - là hạt giống đúng cho parser mới
  - cần được nâng thành runtime parser chính thức

- `pipeline/03_chunk.py`
  - sẽ bị thay bằng section splitter

- `pipeline/04_embed.py`
  - sẽ đổi semantic từ `embed chunk` sang `embed caption`

- `pipeline/05_index.py`
  - sẽ đổi từ chunk payload sang section payload

- `retrieval/service.py`
  - sẽ tiến hóa thành `SearchSections`

- `utils/stores.py`
  - sẽ bị tách nhỏ theo các ports/repositories/index implementations

## 30. Kết luận thiết kế

Kiến trúc đích của repo này không chỉ là đổi từ `chunk retrieval` sang `caption-section retrieval`.
Điểm quan trọng hơn là:

- biến pipeline thành một workflow ổn định
- tách từng bước qua interface rõ ràng
- cho phép tầng dưới thay strategy liên tục
- giữ cho hệ thống không gãy khi mở rộng loại tài liệu, provider, index backend, hoặc storage backend

Nói ngắn gọn:

- `core giữ workflow`
- `ports giữ contract`
- `infrastructure giữ strategy`
- `bootstrap chọn implementation`

Đây là nền bắt buộc để nhiều team có thể cùng phát triển repo này lâu dài mà không kéo nhau sửa chung một chỗ.

## 31. Bổ sung contract cho Search API

Để khóa rõ hành vi của hệ thống sau refactor, Search API phải luôn trả đủ hai loại URI:

- `markdown_s3_uri`: trỏ tới file Markdown đã xử lý, dùng làm canonical artifact
- `source_s3_uri`: trỏ tới file raw gốc, dùng để kiểm tra chéo hoặc quay lại tài liệu ban đầu khi cần

Ý nghĩa vận hành:

- caller dùng `section_content` để trả lời nhanh
- caller dùng `markdown_s3_uri` để đọc toàn bộ bản đã chuẩn hóa
- caller dùng `source_s3_uri` để đối chiếu lại file gốc khi cần chắc chắn hơn

Nguyên tắc bắt buộc:

- pipeline không được làm mất `source_s3_uri` sau khi đã sinh Markdown artifact
- `IndexedSection` phải luôn chứa cả `markdown_s3_uri` và `source_s3_uri`
- search response cuối cùng phải trả cả hai trường này cho consumer

## 32. Verify kiến trúc theo tiêu chuẩn chatbot nội bộ cho tập đoàn lớn

Phần này chốt lại việc kiến trúc mới có phù hợp hay không với bài toán chatbot phục vụ khoảng 6000 nhân viên trong môi trường yêu cầu cao về chất lượng.

### 32.1. Kết luận tổng quan

Hướng kiến trúc `Markdown -> Section -> Caption -> Search` là phù hợp hơn rõ rệt so với kiến trúc chunk 512 token cũ vì:

- trả về section hoàn chỉnh thay vì mảnh text kỹ thuật
- giữ được canonical artifact là Markdown
- cho phép AI team đọc nhanh qua caption nhưng vẫn quay lại full context
- dễ mở rộng loại tài liệu và strategy xử lý

Tuy nhiên, để đủ chuẩn cho môi trường tập đoàn lớn, kiến trúc không chỉ cần đúng về retrieval model mà còn phải bổ sung các ràng buộc enterprise bắt buộc ở các mục dưới đây.

### 32.2. Vì sao phù hợp với chatbot 6000 nhân viên

Trong môi trường nội bộ lớn, người dùng thường hỏi:

- chính sách
- quy trình
- quyền lợi
- hạn mức
- điều kiện áp dụng
- luồng nghiệp vụ liên phòng ban

Các câu hỏi này đòi context hoàn chỉnh theo section, không phù hợp với chunk token cắt giữa chừng.

Kiến trúc mới phù hợp hơn vì:

- retrieval unit là section có nghĩa
- câu trả lời có thể kèm cả bản đã xử lý và bản gốc
- parser output được chuẩn hóa thành Markdown nên dễ debug và tái xử lý
- support tốt cho tài liệu dài, nhiều heading, nhiều policy

### 32.3. Các tiêu chí chất lượng bắt buộc

Để dùng cho tập đoàn lớn, hệ thống phải đảm bảo ít nhất các tiêu chí sau:

#### A. Trả lời phải có căn cứ

Search response phải luôn có:

- `section_content`
- `caption`
- `markdown_s3_uri`
- `source_s3_uri`
- `doc_id`
- `score`

Không được chỉ trả câu trả lời suy diễn mà thiếu đường dẫn truy vết về tài liệu.

#### B. Có khả năng kiểm tra chéo

Caller phải có thể:

- đọc section ngay
- mở full Markdown đã xử lý
- quay lại raw source document

Điều này giảm rủi ro hallucination ở lớp ứng dụng phía trên.

#### C. Kiểm soát freshness và version

Mỗi artifact nên truy được:

- parser version
- caption model version
- embedding model version
- source last modified
- thời điểm index gần nhất

Nếu không có các trường này, rất khó điều tra khi câu trả lời sai do dữ liệu cũ hoặc model cũ.

#### D. Có access control rõ

Trong môi trường nội bộ lớn, không phải mọi tài liệu đều nên được mọi nhân viên search thấy.

Vì vậy kiến trúc sau này phải sẵn sàng gắn:

- `document_type`
- `owner_scope`
- `department_scope`
- `access_tags`

vào `IndexedSection` hoặc metadata store.

#### E. Có khả năng đánh giá chất lượng retrieval

Phải có bộ eval hoặc ít nhất tập câu hỏi chuẩn để đo:

- precision top-k
- recall ở mức section
- chất lượng caption
- độ khớp giữa câu hỏi và section được trả

Không nên chỉ dựa vào cảm giác khi test thủ công.

#### F. Có observability và audit trail

Cần theo dõi được:

- file nào được parse
- markdown nào được sinh
- section nào được tạo
- caption nào được sinh
- model nào đã dùng
- query nào match section nào

Điều này đặc biệt quan trọng khi phục vụ số lượng người dùng lớn.

### 32.4. Kiến trúc mới đã đáp ứng tốt ở đâu

Kiến trúc hiện đề xuất đã đi đúng hướng ở các điểm:

- retrieval theo section thay vì chunk
- Markdown là canonical artifact
- có cả `markdown_s3_uri` và `source_s3_uri`
- có modular process đủ để thêm loại tài liệu mới
- có ports/interfaces để thay strategy mà không gãy pipeline
- có ownership rõ cho derived artifacts

### 32.5. Những năng lực còn phải bổ sung trong implementation

Đây là các năng lực chưa thể coi là “có đủ” chỉ bằng docs hiện tại, nhưng phải được đưa vào roadmap refactor nếu muốn production-grade:

- metadata versioning cho parser/caption/embed/index
- access control metadata ở mức document/section
- search evaluation dataset và regression checks
- observability theo `doc_id`, `section_id`, `request_id`
- retention và lifecycle rõ cho raw/markdown/index artifacts
- cơ chế reprocess chọn lọc khi parser hoặc caption strategy đổi
- migration strategy cho collection schema mới

### 32.6. Kết luận verify

Kết luận cuối cùng:

- về hướng sản phẩm và retrieval model: kiến trúc mới là phù hợp
- về khả năng xây dựng và mở rộng lâu dài: kiến trúc mới là đúng hướng
- về mức độ sẵn sàng cho môi trường tập đoàn lớn: cần coi các mục enterprise ở phần này là bắt buộc, không phải tùy chọn

Nói ngắn gọn:

- kiến trúc mới đúng
- nhưng để đạt chuẩn chất lượng cao cho 6000 nhân viên, implementation phải bám thêm các ràng buộc enterprise đã nêu

## 33. Logging và observability bắt buộc

Phần này là yêu cầu bắt buộc cho production-grade system. Với chatbot nội bộ quy mô lớn, nếu không có logging và observability chặt thì rất khó:

- debug câu trả lời sai
- truy vết tài liệu nào đã tạo ra kết quả
- xác định lỗi nằm ở parser, splitter, captioner, embedding hay index
- phân biệt lỗi dữ liệu với lỗi model hoặc lỗi hạ tầng

### 33.1. Mục tiêu của logging

Hệ thống log phải cho phép trả lời nhanh các câu hỏi sau:

1. File nào vừa được ingest?
2. Markdown nào đã được sinh từ file đó?
3. Bao nhiêu section được tạo?
4. Caption nào được sinh cho section nào?
5. Model nào đã dùng để caption và embed?
6. Query nào đã match section nào?
7. Vì sao một query trả kết quả sai hoặc thiếu?
8. Lỗi xảy ra ở bước nào trong pipeline?

### 33.2. Correlation IDs bắt buộc

Mọi log trong hệ thống cần bám ít nhất một trong các ID sau:

- `doc_id`
- `section_id`
- `request_id`
- `job_id` nếu có

Nguyên tắc:

- ingest logs luôn phải có `doc_id`
- section-level processing logs phải có `section_id`
- search request logs phải có `request_id`
- nếu log liên quan đến một file và một request cụ thể, nên có đủ cả `doc_id` và `request_id`

### 33.3. Những điểm phải log trong pipeline ingest

Ít nhất phải log ở các điểm sau:

#### A. Khi bắt đầu ingest

Log:

- `doc_id`
- `source_s3_uri`
- `file_type`
- `document_type`
- `scan_trigger` hoặc nguồn kích hoạt

#### B. Sau khi parse

Log:

- `doc_id`
- parser strategy đã dùng
- parser version
- markdown length
- markdown artifact URI
- thời gian parse

#### C. Sau khi split section

Log:

- `doc_id`
- splitter strategy
- số section tạo ra
- các section quá ngắn hoặc bị loại nếu có
- thời gian split

#### D. Sau khi caption

Log:

- `doc_id`
- số section đã caption
- caption model
- caption strategy version
- section lỗi nếu có
- thời gian caption

Không nên log toàn bộ caption đầy đủ ở mức info nếu nội dung nhạy cảm; chỉ log checksum, preview ngắn hoặc log đầy đủ ở môi trường debug được kiểm soát.

#### E. Sau khi embed

Log:

- `doc_id`
- embedding model
- số vector tạo ra
- dimension
- thời gian embed

#### F. Sau khi index

Log:

- `doc_id`
- số section được index
- index backend
- collection/index name
- thời gian index

#### G. Khi kết thúc job

Log:

- `doc_id`
- trạng thái cuối
- tổng thời gian
- số section cuối cùng
- lỗi nếu có

### 33.4. Những điểm phải log trong search flow

Ít nhất phải log ở các điểm sau:

#### A. Khi nhận query

Log:

- `request_id`
- query length
- caller context nếu có
- top_k

Không nên log toàn bộ query nguyên văn ở mọi môi trường nếu có dữ liệu nhạy cảm; cần có policy rõ cho production.

#### B. Sau khi embed query

Log:

- `request_id`
- embedding model
- thời gian embed query

#### C. Sau khi vector search

Log:

- `request_id`
- số candidate lấy về
- threshold đang áp dụng
- top matched `doc_id` / `section_id`
- thời gian search

#### D. Khi trả kết quả

Log:

- `request_id`
- số result cuối
- `section_id` top 1
- `doc_id` top 1
- tổng latency

### 33.5. Cấu trúc log khuyến nghị

Nên dùng structured logging thay vì log text tự do.

Ví dụ field chuẩn:

- `timestamp`
- `level`
- `event`
- `doc_id`
- `section_id`
- `request_id`
- `job_id`
- `source_s3_uri`
- `markdown_s3_uri`
- `parser_strategy`
- `splitter_strategy`
- `caption_model`
- `embedding_model`
- `index_backend`
- `duration_ms`
- `status`
- `error_type`
- `error_message`

### 33.6. Event names khuyến nghị

Để team dễ đọc log, nên chuẩn hóa event names:

- `ingest_started`
- `parse_completed`
- `markdown_saved`
- `sections_split`
- `captions_generated`
- `embeddings_generated`
- `sections_indexed`
- `ingest_completed`
- `ingest_failed`
- `search_received`
- `query_embedded`
- `vector_search_completed`
- `search_completed`
- `search_failed`

### 33.7. Logging để dễ fix bug

Muốn fix bug nhanh, log phải giúp tái dựng được lineage:

`source_s3_uri -> markdown_s3_uri -> section_id -> caption -> vector -> search result`

Nghĩa là khi một user báo:

- câu trả lời sai
- thiếu thông tin
- không tìm ra policy đúng

thì team phải lần ngược được:

1. query nào đã chạy
2. match vào section nào
3. section đó sinh ra từ markdown nào
4. markdown đó sinh ra từ raw file nào
5. parser/splitter/captioner/model nào đã dùng lúc đó

### 33.8. Phân biệt log nghiệp vụ và log vận hành

Nên tách rõ:

- log nghiệp vụ
  - ingest/search/result/status
- log vận hành
  - retry, timeout, connection error, storage fallback, degraded mode

Lý do:

- đội sản phẩm và AI quan tâm log nghiệp vụ
- đội platform quan tâm log vận hành

### 33.9. Không log bừa dữ liệu nhạy cảm

Trong môi trường tập đoàn lớn, phải có nguyên tắc:

- không log toàn bộ nội dung tài liệu ở mức info
- không log full section/caption mặc định nếu có nguy cơ chứa dữ liệu nhạy cảm
- dùng preview ngắn, checksum hoặc gated debug mode
- phải phân biệt môi trường dev, staging, prod

### 33.10. Metrics tối thiểu đi kèm log

Ngoài log, cần có metrics tối thiểu:

- số file ingest thành công/thất bại
- thời gian parse trung bình
- thời gian split/caption/embed/index
- số section trung bình trên mỗi tài liệu
- tỉ lệ caption lỗi
- search latency
- query embed latency
- tỉ lệ search không trả kết quả

### 33.11. Kết luận logging

Logging trong hệ thống này không phải phụ trợ, mà là một phần của kiến trúc.

Nếu thiếu logging theo `doc_id`, `section_id`, `request_id` và lineage giữa raw -> markdown -> section -> search result, thì hệ thống sẽ rất khó:

- giữ chất lượng ổn định
- debug production issues
- giải thích với nghiệp vụ vì sao câu trả lời sai
- mở rộng an toàn khi số tài liệu và số người dùng tăng lên

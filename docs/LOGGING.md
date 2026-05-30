# Logging

## Mục tiêu

Logging phải đủ chặt để truy dấu toàn bộ lineage của một tài liệu và một kết quả search trong kiến trúc mới.

Lineage chuẩn:

`source_s3_uri -> markdown_s3_uri -> section_id -> caption -> vector -> search result`

## Field bắt buộc

Các log quan trọng nên luôn cố gắng mang theo:

- `job_id`
- `doc_id`
- `section_id`
- `request_id`
- `source_s3_uri`
- `markdown_s3_uri`
- `parser_version`
- `caption_model`
- `embedding_model`

## Event ingest tối thiểu

- `ingest.parse.completed`
- `ingest.markdown.saved`
- `ingest.sections.split`
- `ingest.captions.embedded`
- `ingest.failed`

## Event search tối thiểu

- `search.requested`
- `search.completed`

## Ghi chú triển khai hiện tại

Runtime hiện tại đã bắt đầu ghi các mốc chính trong [pipeline/run.py](D:/Training/e-commerce events/pipeline/run.py:1), nhưng phần metrics, tracing phân tán và chuẩn event schema vẫn còn nên làm tiếp.

Phần còn thiếu hợp lý cho phase sau:

- structured logging đồng nhất cho mọi module
- metrics theo số section, thời gian caption, thời gian index
- correlation ID xuyên suốt từ scanner đến API search

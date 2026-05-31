# notes/ — Note đóng băng (point-in-time)

> **Type:** note (frozen) · các file ở đây là **ảnh chụp tại thời điểm viết**, KHÔNG cập nhật sau đó.

## Quy ước

- **Note ≠ reference.** File trong `notes/` ghi lại *suy nghĩ/plan/đánh giá tại một thời điểm*. Chúng stale ngay khi code đổi — và **không sao**, đừng sửa để "đồng bộ".
- Khi một plan đã thực hiện xong hoặc một đánh giá đã lỗi thời → vẫn giữ ở đây làm lịch sử quyết định, không xóa, không sửa.
- Trạng thái *hiện tại* của dự án sống ở [../STATUS.md](../STATUS.md), không phải ở đây.
- Muốn thay đổi cách hệ thống hoạt động → viết code + cập nhật **reference doc** (`ARCHITECTURE.md`, `PIPELINE.md`...), rồi nếu cần ghi lại lý do thì thêm một note mới ở đây với ngày.

## Danh mục

| Note | Ngày viết | Nội dung | Trạng thái |
|---|---|---|---|
| [ASYNC_REFACTOR.md](./ASYNC_REFACTOR.md) | 2026-05-31 | Kế hoạch chuyển pipeline sang async thuần (11 bước) | Đang thực hiện dở — mới xong AI/app/api, I/O chưa. Xem [../STATUS.md](../STATUS.md) #3 |
| [ASYNC_PROCESSING_OPTIMIZATION.md](./ASYNC_PROCESSING_OPTIMIZATION.md) | 2026-05-31 | Phân tích bottleneck async + hướng tối ưu P0–P3 | Phân tích, chưa triển khai phần lớn |
| [MOSA_ASSESSMENT.md](./MOSA_ASSESSMENT.md) | 2026-05-31 | Đánh giá repo theo Modular Open Systems Approach | Snapshot đánh giá |
| [CAPTION_SECTION_ARCHITECTURE.md](./CAPTION_SECTION_ARCHITECTURE.md) | 2026-05-30 | Design doc chi tiết refactor Markdown→Section→Caption (đổi tên từ `REFATOR_...`) | Đã thực hiện — kiến trúc hiện tại |
| [REFACTOR.md](./REFACTOR.md) | 2026-05-29 | Narrative refactor sang clean architecture | Đã thực hiện |
| [REQUIREMENT_REALITY_CHECK.md](./REQUIREMENT_REALITY_CHECK.md) | 2026-05-30 | Đối chiếu yêu cầu vs hiện thực | Snapshot |
| [DE_PIPELINE_RECOMMENDATIONS.md](./DE_PIPELINE_RECOMMENDATIONS.md) | 2026-05-30 | Khuyến nghị pipeline DE | Tham chiếu cho các note khác |
| [BATCH_EMBEDDER.md](./BATCH_EMBEDDER.md) | 2026-05-31 | Thiết kế + risk + logging + runbook của BatchEmbedder | Component WIP chưa commit — sẽ nâng lên reference khi merge |

> Khi async/BatchEmbedder được commit và ổn định, cân nhắc đưa `BATCH_EMBEDDER.md` (phần logging/`stats()`/checklist vận hành) lên thành reference ở `docs/`.

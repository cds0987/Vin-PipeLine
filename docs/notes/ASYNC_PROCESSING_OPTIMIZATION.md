# Async Processing Optimization

Tài liệu này mô tả:

- luồng xử lý asynchronous hiện tại
- giới hạn của thiết kế hiện tại
- các bottleneck chính
- hướng tối ưu theo mức ưu tiên

Phạm vi tài liệu là runtime xử lý ingest/search của repo hiện tại, không bàn sang chatbot layer phía trên.

## Kết luận ngắn

Hệ thống hiện tại đang dùng mô hình:

- **background scanner thread**
- **manual scan enqueue trực tiếp vào dispatcher**
- **document-level concurrency bằng dispatcher + bounded queue + worker threads**
- **stage-level processing vẫn tuần tự trong từng document**

Thiết kế này đủ đơn giản để chạy được, nhưng sẽ sớm gặp trần khi:

- số lượng document tăng
- document lớn hơn
- OCR/caption latency cao
- số lượng upload dày hơn
- freshness yêu cầu chặt hơn

Nếu muốn tối ưu thực sự, điểm cần đổi không chỉ là tăng `SCAN_MAX_WORKERS`, mà là **tách scan, dispatch, ingest execution, và retry/failure policy thành các lớp rõ hơn**.

## 1. Luồng hiện tại

## 1.1 Background scanner

Khi service start:

- app build `Container`
- nếu `USE_S3=true` và `SCAN_INTERVAL_SECONDS > 0`
- tạo một background thread chạy `_scanner_loop()`

Luồng:

```text
service start
  ->
build container
  ->
start dispatcher workers
  ->
start scanner thread
  ->
loop:
  scan
  enqueue jobs
  sleep(interval)
```

Nguồn:

- [api/main.py](../../api/main.py)

## 1.2 Manual `/scan`

`POST /scan` chạy như sau:

1. acquire `_scan_lock`
2. gọi `scan_documents.execute()`
3. nếu có jobs:
   - gọi `app.state.dispatcher.enqueue_jobs(...)`
4. trả response ngay

Nghĩa là HTTP request không chờ ingest hoàn tất; nó chỉ enqueue job vào dispatcher nội bộ.

Luồng:

```text
POST /scan
  ->
discover jobs
  ->
enqueue jobs
  ->
return immediately
```

## 1.3 Chạy nhiều document song song

`_JobDispatcher` dùng:

- `queue.Queue` bounded
- danh sách `threading.Thread` workers
- `max_workers = settings.SCAN_MAX_WORKERS`
- dedupe `doc_id` giữa `queued` và `running`

Mỗi document là một task độc lập.

Luồng:

```text
jobs[]
  ->
dispatcher.enqueue_jobs()
  ->
bounded queue
  ->
N worker threads
  ->
each thread runs one ingest job
```

Đây là chỗ concurrent chính của hệ thống hiện tại.

## 1.4 Backlog model hiện tại

Hệ thống hiện đã có backlog model cơ bản trong dispatcher:

- `queued`
- `running`
- queue bounded theo capacity
- dedupe theo `doc_id`

`/health` hiện expose snapshot:

- `queue_depth`
- `queued_jobs`
- `running_jobs`

Điểm này quan trọng vì đây không còn là khoảng trống kiến trúc; nó đã được implement ở mức nền tảng.

## 1.5 Bên trong từng ingest job

Mỗi job chạy tuần tự:

1. claim ingest
2. read file
3. parse
4. normalize markdown
5. save markdown
6. split sections
7. caption sections
8. embed sections
9. index sections
10. update metadata / logs

Luồng:

```text
one document
  ->
read
  ->
parse
  ->
store markdown
  ->
split
  ->
caption
  ->
embed
  ->
index
  ->
done
```

Điều quan trọng:

- có song song giữa **nhiều document**
- không có song song đáng kể giữa **các stage của một document**

## 1.6 Search flow

`POST /search` là synchronous:

1. nhận query
2. embed query
3. vector search
4. map result
5. trả response

Không có queue, background execution, hay async pipeline riêng cho search.

Lưu ý:

- `SearchSections` đã có LRU cache cho query embedding
- cache này chỉ giúp query lặp, không đổi bản chất synchronous của request path

## 2. Vấn đề của thiết kế hiện tại

## 2.1 Scan và execute đã được tách ở mức cơ bản, nhưng mới chỉ trong một process

Điểm đã tốt:

- scanner chỉ làm discovery + enqueue
- dispatcher chịu trách nhiệm queue + worker execution
- `/scan` manual cũng chỉ discover rồi enqueue

Điểm còn hạn chế:

- mọi thứ vẫn nằm trong cùng process/pod
- discovery và execution chưa scale độc lập được theo nghĩa distributed
- chưa có external queue hay retry scheduler riêng

## 2.2 Document-level concurrency chưa giải quyết document lớn

Thread pool giúp chạy nhiều file cùng lúc, nhưng một file lớn vẫn đi qua chuỗi:

- parse
- OCR
- caption
- embed
- index

theo kiểu blocking trong một worker.

Hậu quả:

- file lớn chiếm worker lâu
- file nhỏ đứng chờ sau file lớn
- throughput không tuyến tính khi tăng worker

## 2.3 Caption/OCR là long-latency stages nhưng chưa có execution strategy riêng

Các stage đắt nhất hiện là:

- OCR
- caption generation
- query embedding

Nhưng hiện chúng vẫn sống trong cùng execution path đơn giản như các stage rẻ hơn.

Hậu quả:

- job bị kéo dài bởi external API latency
- retry/failure xử lý còn thô
- không có adaptive throttling riêng cho AI-bound work

## 2.4 Backlog model đã có phần đầu, nhưng chưa đủ cho production orchestration mạnh

Hiện tại hệ thống đã có:

- `queued`
- `running`
- queue depth
- dedupe theo `doc_id`

Nhưng vẫn chưa có rõ cho:

- `retry_scheduled`
- `dead-letter / exhausted`
- delayed retry
- priority queue
- poison document handling

Nghĩa là backlog model không còn là số 0; nó đã có nền tảng, nhưng chưa đủ sâu cho production orchestration mạnh.

## 2.5 Freshness bị khóa bởi scan interval

Nếu đang dùng polling scanner:

- độ trễ thấp nhất để phát hiện document mới bị khóa bởi `SCAN_INTERVAL_SECONDS`

Khi volume lớn hơn:

- scan interval ngắn thì tốn chi phí list/check
- scan interval dài thì freshness kém

Đây là tradeoff nền tảng của polling architecture.

## 2.6 Failure handling còn thiên về per-call, chưa phải workflow orchestration

Hiện tại có:

- timeout theo job
- logging
- một số retry ở provider layer

Nhưng chưa có workflow-level handling rõ cho:

- retry stage nào
- retry lại toàn job hay chỉ stage
- backoff theo loại lỗi
- poison document / dead-letter

## 3. Bottleneck chính

## 3.1 Discovery bottleneck

S3 scan/polling sẽ là bottleneck đầu tiên khi:

- bucket lớn
- prefix nhiều
- upload thường xuyên

## 3.2 AI-bound bottleneck

OCR/caption/embed là bottleneck kế tiếp vì:

- phụ thuộc network + provider latency
- chịu rate limit
- biến động mạnh theo document shape

## 3.3 Worker starvation

Nếu worker pool nhỏ và file lớn nhiều:

- long-running jobs sẽ giữ thread quá lâu
- small jobs mất fairness

## 3.4 Index consistency path

Index/update metadata hiện ở cuối flow.
Nếu lỗi ở giai đoạn cuối:

- compute tốn gần hết rồi mới fail
- recovery cost cao

## 4. Mục tiêu tối ưu đúng

Không nên đặt mục tiêu mơ hồ là "async hơn".

Mục tiêu đúng nên là:

1. giảm time-to-visible cho document mới
2. tăng throughput ingest
3. giảm tail latency do OCR/caption
4. tránh worker starvation
5. tách discovery khỏi execution
6. làm retry/failure policy rõ hơn
7. mở đường cho scale ngang sau này

## 5. Hướng tối ưu theo mức ưu tiên

## P0. Giữ nguyên kiến trúc tổng thể nhưng làm execution khỏe hơn

Đây là bước ít rủi ro nhất.

### P0.1 Đã xong: tách scan khỏi execute trong code path

Hiện tại code đã có:

```text
scanner
  ->
job candidates
  ->
dispatcher
  ->
workers
```

Ý nghĩa:

- scanner không còn trực tiếp execute ingest job
- dispatcher đã là lớp trung gian chính thức

Phần còn lại cần làm tiếp không còn là "tách scan khỏi execute", mà là làm dispatcher và execution policy thông minh hơn.

### P0.2 Thêm execution states rõ ràng

Ít nhất nên có:

- `queued`
- `running`
- `indexed`
- `failed`
- `retry_scheduled`

Hiện tại status model thiên về kết quả cuối, chưa đủ rõ cho async execution lifecycle.

### P0.3 Tách concurrency limits theo loại việc

Không nên chỉ có một `SCAN_MAX_WORKERS`.

Nên tách ít nhất:

- max concurrent document jobs
- max concurrent OCR calls
- max concurrent caption calls
- max concurrent embed calls

Lợi ích:

- tránh AI calls bóp nghẹt toàn hệ thống
- dễ điều chỉnh theo cost/rate-limit

### P0.4 Đã xong: queue nội bộ trong process

Hiện tại code đã có:

- in-memory bounded queue
- dispatcher
- worker threads consume từ queue

Target cũ này đã trở thành hiện trạng.

Giá trị còn lại của hướng này là:

- dùng nó như nền để phát triển tiếp retry states, throttling, fairness, và priority policy

## P1. Tối ưu stage-level bên trong ingest job

## P1.1 Caption batching/concurrency

Caption hiện là stage rất đắt.

Có thể tối ưu bằng:

- batch nhiều section
- parallel caption với semaphore
- cache caption theo content hash

Target:

- không để document 30 sections = 30 round-trips tuần tự nếu không cần

## P1.2 OCR policy theo loại tài liệu

Không phải document nào cũng cần strategy OCR giống nhau.

Nên tách policy:

- text-first parse
- OCR only when required
- page-level timeout / skip policy

Mục tiêu:

- tránh để một document khó OCR khóa worker quá lâu

## P1.3 Early size guard

Cần chặn sớm:

- file quá lớn
- section quá dài
- page count quá lớn

để tránh worker bị giữ quá lâu cho document gần như không thể xử lý tốt.

## P1.4 Idempotent checkpoints

Nếu markdown đã có và source chưa đổi:

- không parse lại

Nếu caption của section đã có theo content hash:

- không caption lại

Nếu embedding cùng model đã tồn tại:

- không embed lại

Điều này giảm rất mạnh compute thừa.

## P2. Chuyển từ polling sang event-friendly architecture

Đây là bước quan trọng nếu muốn freshness tốt hơn.

## P2.1 Scanner không nên là source trigger duy nhất

Nên chuẩn bị cho mô hình:

- S3 event
- object-created notification
- event log table
- hoặc ingest request được đẩy vào queue

Polling có thể giữ như fallback, không nên là trigger chính lâu dài nếu scale lớn.

## P2.2 Discovery pipeline và execution pipeline tách riêng

Target:

```text
document event
  ->
job registry / queue
  ->
workers
  ->
ingest pipeline
```

Khi đó:

- discovery có thể scale riêng
- executor có thể scale riêng
- backlog nhìn thấy rõ

## P2.3 Retry scheduler riêng

Retry không nên chỉ nằm trong provider call.

Nên có retry workflow-level:

- transient error -> delayed retry
- permanent parse error -> failed terminal
- poison document -> quarantine

## P3. Chuẩn bị cho scale ngang thật sự

## P3.1 Từ in-process queue sang external queue

Khi một instance không đủ:

- chuyển sang queue ngoài như Redis/SQS/RabbitMQ/PubSub

Khi đó:

- scanner/producer và worker/consumer tách độc lập
- scale ngang thực sự khả thi

## P3.2 Stateless API, stateful workers

Target rõ hơn:

- API layer: nhẹ, stateless
- worker layer: xử lý ingest
- metadata/index/storage: state bên ngoài

Đây là mô hình tốt hơn cho async workload lớn.

## P3.3 Priority lanes

Khi volume tăng, nên có ưu tiên:

- fast-lane cho file nhỏ
- normal lane
- heavy lane cho OCR-heavy docs

Lợi ích:

- tránh file nặng làm chết fairness toàn hệ thống

## 6. Kiến trúc async mục tiêu đề xuất

## 6.1 Biểu đồ so sánh dễ hiểu

Có 2 cách nghĩ rất khác nhau về "async pipeline".

## Cách 1. Nhiều file song song, mỗi file tự đi hết quy trình

Đây là kiểu hệ thống hiện tại đang dùng.

```text
Scan ra 6 file

Worker 1:
  File 1 -> read -> parse -> split -> caption -> embed -> index

Worker 2:
  File 2 -> read -> parse -> split -> caption -> embed -> index

Worker 3:
  File 3 -> read -> parse -> split -> caption -> embed -> index

Queue:
  File 4, File 5, File 6 chờ worker rảnh
```

Nhìn như đời thường:

- mỗi worker là một người tự làm trọn gói một bộ hồ sơ
- người A xử lý hồ sơ 1 từ đầu tới cuối
- người B xử lý hồ sơ 2 từ đầu tới cuối
- người C xử lý hồ sơ 3 từ đầu tới cuối

### Ưu điểm

- dễ hiểu
- dễ code
- dễ debug
- mỗi file có một execution context rõ ràng
- failure của một file ít làm rối file khác
- phù hợp giai đoạn đầu

### Nhược điểm

- một file nặng sẽ chiếm worker rất lâu
- OCR/caption chậm sẽ kéo dài nguyên worker đó
- khó tối ưu riêng từng stage
- khó cân bằng tải theo loại việc
- throughput tăng chậm khi có nhiều file lớn

## Cách 2. Pipeline băng chuyền theo stage

Đây là kiểu "file 2 vào bước sau ngay khi file 1 đang ở bước tiếp theo" mà nhiều người hình dung khi nói async pipeline.

```text
Scan
  ->
Read Queue
  ->
Parse Queue
  ->
Split Queue
  ->
Caption Queue
  ->
Embed Queue
  ->
Index Queue

Ví dụ tại một thời điểm:

Read worker:
  File 4

Parse worker:
  File 3

Split worker:
  File 2

Caption worker:
  File 1
```

Nhìn như đời thường:

- dây chuyền nhà máy
- người 1 chỉ đọc file
- người 2 chỉ parse
- người 3 chỉ split
- người 4 chỉ caption
- người 5 chỉ embed
- người 6 chỉ index

Mỗi file đi tiếp sang công đoạn sau ngay khi xong công đoạn trước.

### Ưu điểm

- tận dụng tài nguyên tốt hơn nếu các stage có thời gian rất khác nhau
- stage nào chậm sẽ lộ rõ thành bottleneck riêng
- dễ đặt concurrency limit theo từng loại việc
- rất hợp khi OCR/caption/embed có cost và latency khác nhau
- thuận lợi cho scale lớn hơn về sau

### Nhược điểm

- phức tạp hơn nhiều
- khó debug hơn
- phải quản lý queue và trạng thái ở từng stage
- retry khó hơn vì phải quyết định retry từ stage nào
- idempotency quan trọng hơn nhiều
- observability phải tốt hơn mới vận hành nổi

## So sánh trực quan

## Hiện tại: mỗi file chiếm một worker

```text
Time ->

Worker 1: [File 1: read][parse][split][caption][embed][index]
Worker 2: [File 2: read][parse][split][caption][embed][index]
Worker 3: [File 3: read][parse][split][caption][embed][index]
```

Ý nghĩa:

- file 1, 2, 3 chạy cùng lúc
- nhưng mỗi file tự ôm hết cả hành trình trong một worker

## Băng chuyền stage-by-stage

```text
Time ->

Read   : [File 1][File 2][File 3][File 4]
Parse  :         [File 1][File 2][File 3][File 4]
Split  :                 [File 1][File 2][File 3]
Caption:                         [File 1][File 2]
Embed  :                                 [File 1]
Index  :                                         [File 1]
```

Ý nghĩa:

- File 2 không chờ File 1 xong toàn bộ
- File 2 chỉ chờ File 1 nhường chỗ ở stage liên quan
- toàn hệ giống băng chuyền hơn là "mỗi worker tự làm hết"

## Nên chọn cái nào?

## Chọn cách hiện tại khi:

- hệ thống còn nhỏ hoặc trung bình
- muốn rollout nhanh
- muốn giữ code dễ hiểu
- chưa có đủ observability để vận hành pipeline nhiều stage

## Chọn băng chuyền stage-by-stage khi:

- OCR/caption/embed rất chậm và không cân xứng
- volume file tăng rõ
- cần freshness tốt hơn
- muốn scale riêng từng stage
- sẵn sàng chấp nhận complexity vận hành cao hơn

## Kết luận thực dụng

Với repo này, cách hiện tại vẫn hợp lý hơn ở giai đoạn này vì:

- đã có song song giữa nhiều file
- mới chỉ vừa tách `scan -> dispatch -> execute`
- observability và failure policy chưa đủ mạnh để nhảy ngay sang pipeline nhiều stage

Nếu phải đi từng bước:

1. Giữ mô hình hiện tại
2. Tối ưu mạnh caption/OCR concurrency bên trong
3. Tách concurrency limit theo stage
4. Chỉ chuyển sang pipeline băng chuyền khi throughput/freshness thật sự đòi hỏi

## Option A. Tối ưu nhẹ, ít phá kiến trúc hiện tại

```text
scanner/manual scan
  ->
dispatcher
  ->
in-memory bounded queue
  ->
worker threads
  ->
RunIngestJob
```

Khi nào dùng:

- muốn cải thiện nhanh
- chưa muốn thêm infra mới

Ưu điểm:

- ít thay đổi
- dễ rollout

Nhược điểm:

- vẫn giới hạn trong một process/pod

## Option B. Tối ưu trung hạn, đáng làm hơn

```text
scanner/event source
  ->
job queue
  ->
ingest workers
  ->
stage policies (OCR/caption/embed)
  ->
index + metadata
```

Khi nào dùng:

- cần throughput cao hơn
- cần freshness tốt hơn
- cần scale ngang

Ưu điểm:

- scalable hơn nhiều
- observability/backlog tốt hơn

Nhược điểm:

- thêm complexity vận hành

## 7. Khuyến nghị thực tế

Nếu làm theo thứ tự hợp lý, nên đi như sau:

## Giai đoạn 1

- tách `scan -> dispatch -> execute`
- thêm bounded queue nội bộ
- thêm trạng thái `queued/running/retry_scheduled`
- tách concurrency limits cho OCR/caption/embed

Đây là phần đáng làm sớm nhất.

## Giai đoạn 2

- thêm checkpoint/idempotent re-use
- caption cache
- OCR policy rõ hơn
- size/page/section guard

Đây là phần giảm chi phí và tail latency rất mạnh.

## Giai đoạn 3

- chuyển trigger sang event-friendly
- thêm retry scheduler rõ ràng
- chuẩn bị external queue

Đây là phần dành cho scale lớn hơn.

## Giai đoạn 4

- tách worker service khỏi API service nếu cần
- scale ngang thật sự
- thêm priority lanes

## 8. Điều không nên làm

Không nên tối ưu sai hướng bằng các cách sau:

- chỉ tăng `SCAN_MAX_WORKERS` rồi coi như xong
- nhét thêm nhiều thread hơn cho mọi loại task
- giữ polling scanner làm trigger chính mãi mãi
- retry vô điều kiện mọi lỗi
- fallback âm thầm cho workload production-critical

Những cách này thường chỉ dời bottleneck sang chỗ khác.

## 9. Kết luận cuối

Luồng async hiện tại không sai.
Nó phù hợp cho giai đoạn đầu vì đơn giản và dễ vận hành.

Nhưng nếu mục tiêu là:

- ingest nhanh hơn
- xử lý nhiều document hơn
- freshness tốt hơn
- scale production tốt hơn

thì bước tối ưu đúng là:

- **tách discovery khỏi execution**
- **đưa backlog/queue thành first-class concept**
- **tách concurrency policy theo loại stage**
- **chuẩn bị dịch chuyển từ polling sang event-driven**

Nếu phải chốt một câu:

> Hệ thống hiện tại là async ở mức orchestration document, nhưng chưa phải async architecture mạnh ở mức pipeline execution.

## File tham chiếu chính

- [api/main.py](../../api/main.py)
- [app/application/ingest/run_ingest_job.py](../../app/application/ingest/run_ingest_job.py)
- [app/application/search/search_sections.py](../../app/application/search/search_sections.py)
- [docs/DE_PIPELINE_RECOMMENDATIONS.md](./DE_PIPELINE_RECOMMENDATIONS.md)
- [docs/RISKS.md](../RISKS.md)

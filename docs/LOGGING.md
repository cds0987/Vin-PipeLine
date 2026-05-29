# LOGGING.md — AI Workflow Logging System

## Mục đích

Track 4 chỉ số theo thời gian:
1. Token per task (trend giảm = agent ngày càng precise)
2. Rework rate (trend giảm = prompt/design ngày càng đúng)
3. Principle violation frequency (trend giảm = agent học được rules)
4. Module hotspot (module bị touch nhiều = chưa ổn định)

---

## Schema — Task Log

### Fields bắt buộc (thiếu 1 → log vô nghĩa)

| Field | Type | Câu hỏi mà field này trả lời |
|---|---|---|
| `task_id` | `YYYY-MM-DD-NNN` | Unique key để reference |
| `date` | `YYYY-MM-DD` | Trend theo thời gian |
| `agent` | enum: `claude` / `codex-1` / `codex-2` | Agent nào đang tốt hơn? |
| `tokens_in` | int (nghìn, làm tròn) | Input prompt có bloat không? |
| `tokens_out` | int (nghìn, làm tròn) | Output có verbose không? |
| `rework` | bool | Task này có phải làm lại không? |
| `outcome` | enum: `done` / `partial` / `failed` | Task hoàn thành mức nào? |

### Fields optional (có thì tốt, không có không sao)

| Field | Type | Ghi khi nào |
|---|---|---|
| `rework_reason` | enum (xem bên dưới) | Khi `rework: true` |
| `principle_violations` | list[enum] | Khi agent vi phạm rule |
| `modules_touched` | list[str] | Khi task span nhiều files |
| `notes` | ≤ 1 câu | Chỉ khi có thứ không capture được bởi enum |

### Enum values

**rework_reason:**
- `prompt_ambiguous` — yêu cầu không đủ rõ
- `scope_creep` — agent làm ngoài yêu cầu
- `wrong_assumption` — agent tự đoán thay vì hỏi
- `infra_mismatch` — code đúng nhưng không match môi trường
- `test_gap` — test thiếu, bug slip qua
- `design_conflict` — conflict với existing architecture

**principle_violations** (từ AGENTS.md):
- `two_flows` — vi phạm nguyên tắc 2 luồng
- `sdk_in_pipeline` — import SDK vào `pipeline/`
- `hardcoded_config` — hardcode URL/key/model
- `docs_not_updated` — thay đổi contract nhưng không update docs
- `health_not_updated` — thêm dependency không hook vào `/health`
- `read_before_code` — code mà không đọc docs/code liên quan trước

---

## Luồng log

```
Task bắt đầu
    │
    ▼
Agent làm việc
    │
    ▼
Task kết thúc (done/partial/failed)
    │
    ▼
Agent copy template/task_log.md
Agent điền tất cả fields bắt buộc + relevant optional fields
Agent lưu vào logs/tasks/YYYY-MM/YYYY-MM-DD-NNN.md
    │
    ▼
Human đọc (optional, chỉ khi rework:true hoặc có violation)
```

**Agent tự điền:** tất cả fields
**Human làm gì:** đọc sprint review cuối sprint, không cần đọc từng task log

---

## Storage structure

```
logs/
├── tasks/
│   ├── 2026-05/
│   │   ├── 2026-05-29-001.md
│   │   └── 2026-05-29-002.md
│   └── 2026-06/
└── sprints/
    ├── 2026-S1.md    (sprint 1)
    └── 2026-S2.md
```

**Scale trigger:** khi `logs/tasks/` vượt 500 files → migrate sang SQLite.
Dấu hiệu cần migrate: `grep` mất > 5 giây hoặc sprint review cần join nhiều trường.

---

## Review cadence

### Sau mỗi task (agent tự làm, < 60 giây)
- Điền task log
- Không cần human action trừ khi `rework: true`

### Sau mỗi sprint (human làm, 15-20 phút)
- Mở `templates/sprint_review.md`, copy, điền
- Lưu vào `logs/sprints/YYYY-SN.md`
- Trả lời 5 câu hỏi bằng số cụ thể

### 3 câu hỏi để rút insight từ log

1. **"Principle nào bị vi phạm nhiều nhất sprint này?"**
   → Nếu cùng 1 violation xuất hiện ≥ 3 lần → update AGENTS.md hoặc prompt template

2. **"Token trend của từng agent đang đi đâu?"**
   → Nếu tokens_in tăng → prompt bị bloat; nếu tokens_out tăng → agent verbose hơn cần thiết

3. **"Module nào bị touch nhiều nhất?"**
   → Touch ≥ 5 lần trong 1 sprint = interface chưa ổn định, cần redesign trước khi tiếp tục

### Khi nào update AGENTS.md / prompt template

| Trigger | Action |
|---|---|
| Cùng 1 `principle_violation` xuất hiện ≥ 3 lần trong sprint | Thêm rule rõ hơn vào AGENTS.md |
| Cùng 1 `rework_reason` xuất hiện ≥ 3 lần | Sửa prompt template tương ứng |
| Token trung bình tăng 2 sprint liên tiếp | Review và trim prompt — tìm thứ agent không cần |
| Rework rate > 30% trong sprint | Sprint retrospective — tìm root cause trước khi tiếp tục |

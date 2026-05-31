# CLAUDE.md — DE Vector Search Engine

**Đọc `docs/AGENTS.md` trước khi làm bất cứ việc gì.** Đó là entry point duy nhất: off-limits list, navigation map, working principles, và Definition of Done.

## Quick orientation

- Hai luồng duy nhất: **S3 scanner → pipeline** (vào) và **`POST /search`** (ra)
- `pipeline/` chỉ được import 5 interface — không được import SDK cụ thể vào đây
- Mọi thay đổi API contract hoặc DB schema → cập nhật `docs/PIPELINE.md` trước khi merge

## Chạy nhanh (không cần infra)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m pytest -q
```

## Navigation

| Cần biết | File |
|---|---|
| Rules, off-limits, DoD đầy đủ | `docs/AGENTS.md` |
| **Dự án đang ở đâu** — WIP, backlog, deployment state | `docs/STATUS.md` |
| Kiến trúc + diagram + design principles | `docs/ARCHITECTURE.md` |
| Chi tiết pipeline, schema DB, API, env vars | `docs/PIPELINE.md` |
| Cách chạy local, docker, test commands | `docs/SETUP.md` |
| Production risks + hardening backlog | `docs/RISKS.md` |
| Test structure + coverage backlog | `docs/TESTS.md` |
| Thứ đã bị bỏ — không dùng làm reference | `docs/LEGACY.md` |

from __future__ import annotations

import api.main as api_main


def test_scan_endpoint_rejects_parallel_scan(api_client):
    acquired = api_main._scan_lock.acquire(blocking=False)
    assert acquired
    try:
        response = api_client.post("/scan", json={})
    finally:
        if api_main._scan_lock.locked():
            api_main._scan_lock.release()

    assert response.status_code == 409
    assert response.json()["detail"] == "scan already in progress"

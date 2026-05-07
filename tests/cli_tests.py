"""
UnifiedDataMCP local smoke tests.

Usage:
    python tests/cli_tests.py
    python tests/cli_tests.py --base-url http://localhost:8000 --api-token mytoken
"""

import argparse
import json
import os
import sys
import time

try:
    import requests
except ImportError:
    print("[ERROR] `requests` is required. Install it with: pip install requests")
    sys.exit(1)


DEFAULT_BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
DEFAULT_API_TOKEN = os.getenv("API_TOKEN", os.getenv("API_SECRET", ""))
REQUEST_TIMEOUT = 30
JOB_POLL_MAX_RETRIES = int(os.getenv("JOB_POLL_MAX_RETRIES", "24"))
JOB_POLL_INTERVAL = int(os.getenv("JOB_POLL_INTERVAL", "5"))

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
WARN = "WARN"

results: list[dict] = []


def _log(step: int, name: str, status: str, detail: str = "") -> None:
    icon = {PASS: "[OK]", FAIL: "[FAIL]", SKIP: "[SKIP]", WARN: "[WARN]"}.get(status, "[?]")
    msg = f"{icon} Step {step:02d}: {name} - {status}"
    if detail:
        msg += f"\n   {detail}"
    print(msg)
    results.append({"step": step, "name": name, "status": status, "detail": detail})


def _url(path: str) -> str:
    return f"{DEFAULT_BASE_URL}{path}"


def _headers(with_auth: bool = True) -> dict:
    headers = {"Content-Type": "application/json"}
    if with_auth and DEFAULT_API_TOKEN:
        headers["Authorization"] = f"Bearer {DEFAULT_API_TOKEN}"
    return headers


def _print_json(data) -> str:
    return json.dumps(data, indent=2, default=str)[:500]


def test_health() -> None:
    try:
        response = requests.get(_url("/health"), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        _log(1, "Health Check", PASS if payload.get("status") == "ok" else FAIL, _print_json(payload))
    except Exception as e:
        _log(1, "Health Check", FAIL, str(e))


def test_debug_tools() -> None:
    if not DEFAULT_API_TOKEN:
        _log(2, "Debug Tools List", SKIP, "API_TOKEN not set")
        return
    try:
        response = requests.get(_url("/debug/tools"), headers=_headers(), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        tools = payload.get("tools", [])
        required = {"extract_analytical_to_csv", "stage_sql_to_railway_async"}
        missing = required.difference(tools)
        if missing:
            _log(2, "Debug Tools List", FAIL, f"Missing tools: {sorted(missing)}")
        else:
            _log(2, "Debug Tools List", PASS, f"tool_count={payload.get('tool_count')}")
    except Exception as e:
        _log(2, "Debug Tools List", FAIL, str(e))


def test_debug_tcp() -> None:
    if not DEFAULT_API_TOKEN:
        _log(3, "SQL Server TCP Connectivity", SKIP, "API_TOKEN not set")
        return
    try:
        response = requests.get(_url("/debug/tcp"), headers=_headers(), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if payload.get("ok"):
            _log(3, "SQL Server TCP Connectivity", PASS, f"resolved={payload.get('resolved_addresses')}")
        else:
            _log(3, "SQL Server TCP Connectivity", FAIL, payload.get("error", _print_json(payload)))
    except Exception as e:
        _log(3, "SQL Server TCP Connectivity", FAIL, str(e))


def test_debug_odbc() -> None:
    if not DEFAULT_API_TOKEN:
        _log(4, "SQL Server ODBC Connection", SKIP, "API_TOKEN not set")
        return
    try:
        response = requests.get(_url("/debug/odbc"), headers=_headers(), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if payload.get("ok"):
            _log(4, "SQL Server ODBC Connection", PASS, f"server={payload.get('server')}")
        else:
            _log(4, "SQL Server ODBC Connection", FAIL, payload.get("error", _print_json(payload)))
    except Exception as e:
        _log(4, "SQL Server ODBC Connection", FAIL, str(e))


def test_debug_sql() -> None:
    if not DEFAULT_API_TOKEN:
        _log(5, "SQL Server Query Test", SKIP, "API_TOKEN not set")
        return
    try:
        response = requests.get(_url("/debug/sql"), headers=_headers(), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if payload.get("ok") and payload.get("value") == 1:
            _log(5, "SQL Server Query Test", PASS)
        else:
            _log(5, "SQL Server Query Test", FAIL, payload.get("error", _print_json(payload)))
    except Exception as e:
        _log(5, "SQL Server Query Test", FAIL, str(e))


def test_extract_sql() -> dict:
    if not DEFAULT_API_TOKEN:
        _log(6, "REST API Extract SQL to CSV", SKIP, "API_TOKEN not set")
        return {}
    try:
        response = requests.post(
            _url("/extract/sql"),
            headers=_headers(),
            json={"query": "SELECT 1 AS test_column"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("job_id") and payload.get("status") == "started":
            _log(6, "REST API Extract SQL to CSV", PASS, f"job_id={payload['job_id']}")
            return payload
        _log(6, "REST API Extract SQL to CSV", FAIL, _print_json(payload))
        return {}
    except Exception as e:
        _log(6, "REST API Extract SQL to CSV", FAIL, str(e))
        return {}


def poll_job(job_id: str | None, step: int, name: str) -> dict:
    if not job_id:
        _log(step, name, SKIP, "No job_id")
        return {}
    for attempt in range(1, JOB_POLL_MAX_RETRIES + 1):
        try:
            response = requests.get(_url(f"/job/{job_id}"), timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
            status = payload.get("status")
            if status in ("completed", "success"):
                _log(step, name, PASS, f"completed after {attempt} poll(s)")
                return payload
            if status == "failed":
                _log(step, name, FAIL, _print_json(payload))
                return payload
            time.sleep(JOB_POLL_INTERVAL)
        except Exception as e:
            _log(step, name, FAIL, str(e))
            return {}
    _log(step, name, FAIL, f"Timed out after {JOB_POLL_MAX_RETRIES} polls")
    return {}


def test_download(job_payload: dict) -> None:
    result = job_payload.get("result") or {}
    file_id = result.get("file_id")
    download_url = result.get("download_url", "")
    token = download_url.split("token=")[-1] if "token=" in download_url else ""
    if not file_id or not token:
        _log(8, "File Download with Token", SKIP, "file_id/token missing from job result")
        return
    try:
        response = requests.get(_url(f"/download/{file_id}?token={token}"), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "csv" in content_type or response.text.startswith("test_column"):
            _log(8, "File Download with Token", PASS, f"Content-Type={content_type[:50]}")
        else:
            _log(8, "File Download with Token", FAIL, f"Unexpected Content-Type={content_type}")
    except Exception as e:
        _log(8, "File Download with Token", FAIL, str(e))


def test_sharepoint_auth() -> None:
    if not DEFAULT_API_TOKEN:
        _log(9, "SharePoint Token Test", SKIP, "API_TOKEN not set")
        return
    try:
        response = requests.get(_url("/test-sharepoint"), headers=_headers(), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") == "success":
            _log(9, "SharePoint Token Test", PASS)
        else:
            _log(9, "SharePoint Token Test", FAIL, payload.get("error", _print_json(payload)))
    except Exception as e:
        _log(9, "SharePoint Token Test", FAIL, str(e))


def test_load_to_railway() -> None:
    if not DEFAULT_API_TOKEN:
        _log(10, "Sync SQL to Railway Pipeline", SKIP, "API_TOKEN not set")
        return
    try:
        response = requests.post(
            _url("/load-to-railway"),
            headers=_headers(),
            json={"query": "SELECT 1 AS col_a, 2 AS col_b", "table_name": "smoke_test_staging"},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") == "success" and isinstance(payload.get("rows_loaded"), int):
            _log(10, "Sync SQL to Railway Pipeline", PASS, f"rows_loaded={payload['rows_loaded']}")
        else:
            _log(10, "Sync SQL to Railway Pipeline", FAIL, _print_json(payload))
    except Exception as e:
        _log(10, "Sync SQL to Railway Pipeline", FAIL, str(e))


def test_load_to_railway_async() -> dict:
    if not DEFAULT_API_TOKEN:
        _log(11, "Async SQL to Railway Pipeline", SKIP, "API_TOKEN not set")
        return {}
    try:
        response = requests.post(
            _url("/load-to-railway/async"),
            headers=_headers(),
            json={"query": "SELECT 1 AS col_a, 2 AS col_b", "table_name": "smoke_test_staging_async"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("job_id") and payload.get("status") == "started":
            _log(11, "Async SQL to Railway Pipeline", PASS, f"job_id={payload['job_id']}")
            return payload
        _log(11, "Async SQL to Railway Pipeline", FAIL, _print_json(payload))
        return {}
    except Exception as e:
        _log(11, "Async SQL to Railway Pipeline", FAIL, str(e))
        return {}


def test_debug_railway() -> None:
    if not DEFAULT_API_TOKEN:
        _log(13, "Railway DB Connectivity", SKIP, "API_TOKEN not set")
        return
    try:
        response = requests.get(_url("/debug/railway"), headers=_headers(), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if payload.get("ok"):
            _log(13, "Railway DB Connectivity", PASS, f"value={payload.get('value')}")
        else:
            _log(13, "Railway DB Connectivity", WARN, payload.get("error", _print_json(payload)))
    except Exception as e:
        _log(13, "Railway DB Connectivity", FAIL, str(e))


def run_all_tests(stop_on_failure: bool = False) -> None:
    global results
    results = []

    print(f"\n{'=' * 60}")
    print(" UnifiedDataMCP - Local Smoke Tests")
    print(f" Target: {DEFAULT_BASE_URL}")
    print(f" API Token: {'set' if DEFAULT_API_TOKEN else 'NOT SET (auth tests will skip)'}")
    print(f"{'=' * 60}\n")

    def maybe_stop():
        return stop_on_failure and results and results[-1]["status"] == FAIL

    test_health()
    if maybe_stop():
        return
    test_debug_tools()
    if maybe_stop():
        return
    test_debug_tcp()
    if maybe_stop():
        return
    test_debug_odbc()
    if maybe_stop():
        return
    test_debug_sql()
    if maybe_stop():
        return

    extract_job = test_extract_sql()
    if maybe_stop():
        return
    extract_result = poll_job(extract_job.get("job_id"), 7, "Extract SQL Job Poll")
    if maybe_stop():
        return
    test_download(extract_result)
    if maybe_stop():
        return

    test_sharepoint_auth()
    if maybe_stop():
        return
    test_load_to_railway()
    if maybe_stop():
        return

    async_job = test_load_to_railway_async()
    if maybe_stop():
        return
    poll_job(async_job.get("job_id"), 12, "Async SQL to Railway Job Poll")
    if maybe_stop():
        return

    test_debug_railway()

    passed = sum(1 for r in results if r["status"] == PASS)
    failed = sum(1 for r in results if r["status"] == FAIL)
    skipped = sum(1 for r in results if r["status"] == SKIP)
    warned = sum(1 for r in results if r["status"] == WARN)

    print(f"\n{'=' * 60}")
    print(f" Results: {passed} passed, {failed} failed, {skipped} skipped, {warned} warnings")
    print(f"{'=' * 60}\n")

    if failed:
        print("[FAILED] Smoke tests failed. Review the errors above before deploying.")
        sys.exit(1)
    print("[SUCCESS] All executed smoke tests passed.")


def test_smoke_suite() -> None:
    run_all_tests()
    failures = [r for r in results if r["status"] == FAIL]
    if failures:
        raise AssertionError(f"{len(failures)} smoke test(s) failed: {[f['name'] for f in failures]}")


def main() -> None:
    global DEFAULT_BASE_URL, DEFAULT_API_TOKEN

    parser = argparse.ArgumentParser(description="UnifiedDataMCP local smoke tests")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Server base URL")
    parser.add_argument("--api-token", default=DEFAULT_API_TOKEN, help="Bearer token")
    parser.add_argument("--stop-on-failure", action="store_true", help="Stop on first failure")
    args = parser.parse_args()

    DEFAULT_BASE_URL = args.base_url.rstrip("/")
    DEFAULT_API_TOKEN = args.api_token

    run_all_tests(stop_on_failure=args.stop_on_failure)


if __name__ == "__main__":
    main()

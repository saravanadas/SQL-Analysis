"""
UnifiedDataMCP — Local Smoke Test Suite (Phase 1)

This script exercises every REST endpoint defined in src/api/routes.py
and the debug endpoints in src/main.py against a running local server.

Usage:
    # 1. Start your server (Docker or uvicorn)
    # 2. Run the tests
    python tests/cli_tests.py

    # Override defaults via CLI
    python tests/cli_tests.py --base-url http://localhost:8000 --api-token mytoken

    # Or with pytest
    pytest tests/cli_tests.py -v

Env vars:
    BASE_URL      Target server URL (default: http://localhost:8000)
    API_TOKEN     Bearer token for authenticated endpoints
"""

import argparse
import json
import os
import sys
import time
from typing import Optional

try:
    import requests
except ImportError:
    print("[ERROR] `requests` is required. Install it with: pip install requests")
    sys.exit(1)


# ───────────────────────────────────────────────
# Configuration
# ───────────────────────────────────────────────
DEFAULT_BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
DEFAULT_API_TOKEN = os.getenv("API_TOKEN", os.getenv("API_SECRET", ""))
REQUEST_TIMEOUT = 30  # seconds
JOB_POLL_MAX_RETRIES = 12
JOB_POLL_INTERVAL = 5  # seconds

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

results: list[dict] = []


def _log(step: int, name: str, status: str, detail: str = "") -> None:
    """Record and print a test result."""
    icon = {"PASS": "[OK]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}.get(status, "[?]")
    msg = f"{icon} Step {step:02d}: {name} — {status}"
    if detail:
        msg += f"\n   {detail}"
    print(msg)
    results.append({"step": step, "name": name, "status": status, "detail": detail})


def _url(path: str) -> str:
    """Build a full URL from a path."""
    return f"{DEFAULT_BASE_URL}{path}"


def _headers(with_auth: bool = True) -> dict:
    """Return request headers, optionally including the Bearer token."""
    h = {"Content-Type": "application/json"}
    if with_auth and DEFAULT_API_TOKEN:
        h["Authorization"] = f"Bearer {DEFAULT_API_TOKEN}"
    return h


def _print_json(data: dict) -> str:
    """Pretty-print a small JSON snippet for debug output."""
    return json.dumps(data, indent=2, default=str)[:400]


# ═══════════════════════════════════════════════
# Test Implementations
# ═══════════════════════════════════════════════

def test_health() -> None:
    """Step 01: GET /health — must return {"status":"ok"}"""
    try:
        r = requests.get(_url("/health"), timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        if payload.get("status") == "ok":
            _log(1, "Health Check", PASS)
        else:
            _log(1, "Health Check", FAIL, f"Unexpected body: {_print_json(payload)}")
    except Exception as e:
        _log(1, "Health Check", FAIL, str(e))


def test_debug_tools() -> None:
    """Step 02: GET /debug/tools — must list >= 14 tools."""
    if not DEFAULT_API_TOKEN:
        _log(2, "Debug Tools List", SKIP, "API_TOKEN not set")
        return
    try:
        r = requests.get(_url("/debug/tools"), headers=_headers(), timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        tool_count = payload.get("tool_count", 0)
        if tool_count >= 14:
            _log(2, "Debug Tools List", PASS, f"tool_count={tool_count}")
        else:
            _log(2, "Debug Tools List", FAIL, f"tool_count={tool_count}, expected >= 14")
    except Exception as e:
        _log(2, "Debug Tools List", FAIL, str(e))


def test_debug_tcp() -> None:
    """Step 03: GET /debug/tcp — TCP connectivity to SQL Server host."""
    if not DEFAULT_API_TOKEN:
        _log(3, "SQL Server TCP Connectivity", SKIP, "API_TOKEN not set")
        return
    try:
        r = requests.get(_url("/debug/tcp"), headers=_headers(), timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        if payload.get("ok") is True:
            resolved = payload.get("resolved_addresses", [])
            _log(3, "SQL Server TCP Connectivity", PASS, f"resolved={resolved}")
        else:
            err = payload.get("error", payload)
            _log(3, "SQL Server TCP Connectivity", FAIL, f"Server says: {err}")
    except Exception as e:
        _log(3, "SQL Server TCP Connectivity", FAIL, str(e))


def test_debug_odbc() -> None:
    """Step 04: GET /debug/odbc — full ODBC connection + @@SERVERNAME."""
    if not DEFAULT_API_TOKEN:
        _log(4, "SQL Server ODBC Connection", SKIP, "API_TOKEN not set")
        return
    try:
        r = requests.get(_url("/debug/odbc"), headers=_headers(), timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        if payload.get("ok") is True:
            server = payload.get("server", "unknown")
            _log(4, "SQL Server ODBC Connection", PASS, f"server={server}")
        else:
            err = payload.get("error", payload)
            _log(4, "SQL Server ODBC Connection", FAIL, f"Server says: {err}")
    except Exception as e:
        _log(4, "SQL Server ODBC Connection", FAIL, str(e))


def test_debug_sql() -> None:
    """Step 05: GET /debug/sql — simple pyodbc SELECT 1."""
    if not DEFAULT_API_TOKEN:
        _log(5, "SQL Server Query Test", SKIP, "API_TOKEN not set")
        return
    try:
        r = requests.get(_url("/debug/sql"), headers=_headers(), timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        if payload.get("ok") is True and payload.get("value") == 1:
            _log(5, "SQL Server Query Test", PASS)
        else:
            err = payload.get("error", payload)
            _log(5, "SQL Server Query Test", FAIL, f"Server says: {err}")
    except Exception as e:
        _log(5, "SQL Server Query Test", FAIL, str(e))


def test_extract_sql() -> dict:
    """Step 06: POST /extract/sql — trigger async extraction job.
    Returns the job_id dict so the next test can poll it."""
    if not DEFAULT_API_TOKEN:
        _log(6, "REST API Extract SQL to CSV", SKIP, "API_TOKEN not set")
        return {}
    payload = {"query": "SELECT 1 AS test_column"}
    try:
        r = requests.post(
            _url("/extract/sql"),
            headers=_headers(),
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        job_id = data.get("job_id")
        status = data.get("status")
        if job_id and status == "started":
            _log(6, "REST API Extract SQL to CSV", PASS, f"job_id={job_id}")
            return data
        else:
            _log(6, "REST API Extract SQL to CSV", FAIL, f"Unexpected body: {_print_json(data)}")
            return {}
    except Exception as e:
        _log(6, "REST API Extract SQL to CSV", FAIL, str(e))
        return {}


def test_job_status(job_id: Optional[str]) -> None:
    """Step 07: GET /job/{job_id} — poll until completion."""
    if not job_id:
        _log(7, "Job Status Poll", SKIP, "No job_id from previous step")
        return
    url = _url(f"/job/{job_id}")
    for attempt in range(1, JOB_POLL_MAX_RETRIES + 1):
        try:
            r = requests.get(url, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            job_status = data.get("status", "unknown")
            if job_status in ("completed", "success"):
                _log(7, "Job Status Poll", PASS, f"completed after {attempt} poll(s)")
                return
            if job_status == "failed":
                _log(7, "Job Status Poll", FAIL, f"Job failed: {_print_json(data)}")
                return
            time.sleep(JOB_POLL_INTERVAL)
        except Exception as e:
            _log(7, "Job Status Poll", FAIL, str(e))
            return
    _log(7, "Job Status Poll", FAIL, f"Timed out after {JOB_POLL_MAX_RETRIES} polls")


def test_download(job_result: Optional[dict]) -> None:
    """Step 08: GET /download/{file_id}?token={token} — verify CSV download."""
    if not job_result:
        _log(8, "File Download with Token", SKIP, "No job result from Step 06")
        return
    result = job_result.get("result", {})
    file_id = result.get("file_id")
    token = result.get("download_url", "").split("token=")[-1] if result.get("download_url") else ""
    if not file_id or not token:
        _log(8, "File Download with Token", SKIP, "file_id/token missing from job result")
        return
    url = _url(f"/download/{file_id}?token={token}")
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "")
        if "csv" in content_type or r.text.startswith("test_column"):
            _log(8, "File Download with Token", PASS, f"Content-Type={content_type[:30]}")
        else:
            _log(8, "File Download with Token", FAIL, f"Unexpected Content-Type={content_type}")
    except Exception as e:
        _log(8, "File Download with Token", FAIL, str(e))


def test_sharepoint_auth() -> None:
    """Step 09: GET /test-sharepoint — SharePoint token acquisition."""
    if not DEFAULT_API_TOKEN:
        _log(9, "SharePoint Token Test", SKIP, "API_TOKEN not set")
        return
    try:
        r = requests.get(_url("/test-sharepoint"), headers=_headers(), timeout=REQUEST_TIMEOUT)
        # This endpoint returns 200 even on auth failure (to prevent leaking internals),
        # so we inspect the JSON body.
        if r.status_code == 401:
            _log(9, "SharePoint Token Test", FAIL, "Unauthorized (401)")
            return
        r.raise_for_status()
        payload = r.json()
        if payload.get("status") == "success":
            _log(9, "SharePoint Token Test", PASS)
        else:
            err = payload.get("error", payload)
            _log(9, "SharePoint Token Test", FAIL, f"Server says: {err}")
    except Exception as e:
        _log(9, "SharePoint Token Test", FAIL, str(e))


def test_load_to_railway() -> None:
    """Step 10: POST /load-to-railway — SQL Server → Railway pipeline."""
    if not DEFAULT_API_TOKEN:
        _log(10, "SQL to Railway Pipeline", SKIP, "API_TOKEN not set")
        return
    payload = {"query": "SELECT 1 AS col_a, 2 AS col_b", "table_name": "smoke_test_staging"}
    try:
        r = requests.post(
            _url("/load-to-railway"),
            headers=_headers(),
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "success" and isinstance(data.get("rows_loaded"), int):
            _log(10, "SQL to Railway Pipeline", PASS, f"rows_loaded={data['rows_loaded']}")
        else:
            _log(10, "SQL to Railway Pipeline", FAIL, f"Unexpected body: {_print_json(data)}")
    except Exception as e:
        _log(10, "SQL to Railway Pipeline", FAIL, str(e))


def test_debug_railway() -> None:
    """Step 11: GET /debug/railway — test Railway PostgreSQL connectivity via SELECT 1."""
    if not DEFAULT_API_TOKEN:
        _log(11, "Railway DB Connectivity", SKIP, "API_TOKEN not set")
        return
    try:
        r = requests.get(_url("/debug/railway"), headers=_headers(), timeout=REQUEST_TIMEOUT)
        if r.status_code == 401:
            _log(11, "Railway DB Connectivity", FAIL, "Unauthorized (401)")
            return
        r.raise_for_status()
        payload = r.json()
        if payload.get("ok"):
            _log(11, "Railway DB Connectivity", PASS, f"value={payload.get('value')}")
        else:
            err = payload.get("error", payload)
            _log(11, "Railway DB Connectivity", WARN, f"DB connection failed: {err}")
    except Exception as e:
        _log(11, "Railway DB Connectivity", FAIL, str(e))


# ═══════════════════════════════════════════════
# Pytest compatibility
# ═══════════════════════════════════════════════

def test_smoke_suite() -> None:
    """Meta-test that can be invoked via pytest."""
    run_all_tests()
    failures = [r for r in results if r["status"] == FAIL]
    if failures:
        raise AssertionError(f"{len(failures)} smoke test(s) failed: {[f['name'] for f in failures]}")


# ═══════════════════════════════════════════════
# Main runner
# ═══════════════════════════════════════════════

def run_all_tests(stop_on_failure: bool = False) -> None:
    """Execute the full Phase 1 smoke test sequence."""
    global results
    results = []

    print(f"\n{'='*60}")
    print(f" UnifiedDataMCP — Local Smoke Tests")
    print(f" Target: {DEFAULT_BASE_URL}")
    print(f" API Token: {'set' if DEFAULT_API_TOKEN else 'NOT SET (auth tests will skip)'}")
    print(f"{'='*60}\n")

    # Ordered list of test callables
    tests = [
        test_health,
        test_debug_tools,
        test_debug_tcp,
        test_debug_odbc,
        test_debug_sql,
        lambda: test_job_status(test_extract_sql().get("job_id")),
        lambda: test_download(results[-2].get("detail") if results else None),
        test_sharepoint_auth,
        test_load_to_railway,
        test_railway_db_query,
    ]

    # NOTE: Steps 6 & 7 are chained (extract → poll).
    # We handle them explicitly so we can pass job_id correctly.
    test_health()
    if stop_on_failure and results[-1]["status"] == FAIL:
        return

    test_debug_tools()
    if stop_on_failure and results[-1]["status"] == FAIL:
        return

    test_debug_tcp()
    if stop_on_failure and results[-1]["status"] == FAIL:
        return

    test_debug_odbc()
    if stop_on_failure and results[-1]["status"] == FAIL:
        return

    test_debug_sql()
    if stop_on_failure and results[-1]["status"] == FAIL:
        return

    job_info = test_extract_sql()
    if stop_on_failure and results[-1]["status"] == FAIL:
        return

    test_job_status(job_info.get("job_id"))
    if stop_on_failure and results[-1]["status"] == FAIL:
        return

    test_download(job_info)
    if stop_on_failure and results[-1]["status"] == FAIL:
        return

    test_sharepoint_auth()
    if stop_on_failure and results[-1]["status"] == FAIL:
        return

    test_load_to_railway()
    if stop_on_failure and results[-1]["status"] == FAIL:
        return

    test_railway_db_query()

    # ── Summary ──
    passed = sum(1 for r in results if r["status"] == PASS)
    failed = sum(1 for r in results if r["status"] == FAIL)
    skipped = sum(1 for r in results if r["status"] == SKIP)

    print(f"\n{'='*60}")
    print(f" Results: {passed} passed, {failed} failed, {skipped} skipped")
    print(f"{'='*60}\n")

    if failed:
        print("[FAILED] Smoke tests FAILED. Review the errors above before deploying.")
        sys.exit(1)
    else:
        print("[SUCCESS] All executed smoke tests passed. Ready for Railway deployment!")


def main() -> None:
    global DEFAULT_BASE_URL, DEFAULT_API_TOKEN

    parser = argparse.ArgumentParser(description="UnifiedDataMCP Local Smoke Tests")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Server base URL")
    parser.add_argument("--api-token", default=DEFAULT_API_TOKEN, help="Bearer token")
    parser.add_argument(
        "--stop-on-failure", action="store_true", help="Stop immediately on first failure"
    )
    args = parser.parse_args()

    DEFAULT_BASE_URL = args.base_url.rstrip("/")
    DEFAULT_API_TOKEN = args.api_token

    run_all_tests(stop_on_failure=args.stop_on_failure)


if __name__ == "__main__":
    main()

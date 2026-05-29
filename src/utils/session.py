import re
import threading
import uuid
from contextlib import contextmanager


_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TABLE_LOCKS: dict[str, threading.Lock] = {}
_TABLE_LOCKS_GUARD = threading.Lock()


def create_session_id() -> str:
    """Create a stable identifier the agent can pass across MCP tool calls."""
    return str(uuid.uuid4())


def sanitize_session_id(session_id: str | None) -> str:
    """
    Convert a user/agent session id into a safe PostgreSQL identifier suffix.

    Empty session ids are treated as no session. Hyphens and other characters
    are normalized so UUIDs can be used directly.
    """
    if not session_id:
        return ""

    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", session_id.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_").lower()
    return cleaned[:48]


def resolve_session_table_name(table_name: str, session_id: str | None = None) -> str:
    """
    Return the physical table name for a request.

    No session id means preserve the existing shared table behavior. Supplying
    a session id creates an isolated table name such as:
    ap_invoices_s_123e4567_e89b_12d3
    """
    if not _IDENTIFIER_RE.fullmatch(table_name or ""):
        raise ValueError("Invalid table name")

    suffix = sanitize_session_id(session_id)
    if not suffix:
        return table_name

    physical_name = f"{table_name}_s_{suffix}"
    if len(physical_name) > 63:
        physical_name = f"{table_name[:40]}_s_{suffix[:20]}"
    return physical_name


@contextmanager
def table_write_lock(table_name: str):
    """
    Serialize writes to the same physical table inside this app process.

    Different session-suffixed tables can load in parallel; only the same table
    is protected from overlapping replace/append sequences.
    """
    with _TABLE_LOCKS_GUARD:
        lock = _TABLE_LOCKS.setdefault(table_name, threading.Lock())

    lock.acquire()
    try:
        yield
    finally:
        lock.release()

# STABILIZATION: 2026-05-04 — Full job tracking with thread-safe status
import threading
import uuid
from datetime import datetime
from typing import Callable, Any, Dict


class BackgroundJobManager:
    """Thread-safe in-memory job tracker. Added 2026-05-04."""

    def __init__(self):
        self._jobs: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def submit_job(self, job_id: str, func: Callable, *args, **kwargs) -> str:
        """Submit a job to run in a background thread. 2026-05-04."""
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "status": "pending",
                "result": None,
                "error": None,
                "created_at": datetime.utcnow().isoformat(),
                "completed_at": None,
            }

        def _worker():
            with self._lock:
                self._jobs[job_id]["status"] = "running"
            try:
                result = func(*args, **kwargs)
                with self._lock:
                    self._jobs[job_id]["status"] = "completed"
                    self._jobs[job_id]["result"] = result
            except Exception as e:
                with self._lock:
                    self._jobs[job_id]["status"] = "failed"
                    self._jobs[job_id]["error"] = str(e)
            finally:
                with self._lock:
                    self._jobs[job_id]["completed_at"] = datetime.utcnow().isoformat()

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        return job_id

    def get_job(self, job_id: str) -> dict:
        """Get job status. 2026-05-04."""
        with self._lock:
            return self._jobs.get(job_id, {"status": "not_found"}).copy()

    def list_jobs(self) -> list:
        """List all jobs. 2026-05-04."""
        with self._lock:
            return [j.copy() for j in self._jobs.values()]

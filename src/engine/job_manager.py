import threading
import uuid
import logging
import json
from sqlalchemy import text
from src.config.database import get_engine  # make sure this exists

logger = logging.getLogger(__name__)

class JobManager:

    def __init__(self):
        self.engine = get_engine()
        self._ensure_schema()

    def _ensure_schema(self):
        with self.engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    created_date TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            conn.execute(text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS result TEXT"))
            conn.execute(text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS error TEXT"))
            conn.execute(text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS created_date TIMESTAMPTZ DEFAULT NOW()"))

    def create_job(self, func, *args):
        job_id = str(uuid.uuid4())

        logger.info(f"[JOB {job_id}] Creating job")

        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO jobs (job_id, status)
                VALUES (:job_id, 'running')
            """), {"job_id": job_id})

        threading.Thread(
            target=self.run_job,
            args=(job_id, func, args),
            daemon=True
        ).start()

        return job_id

    def run_job(self, job_id, func, args):
        try:
            logger.info(f"[JOB {job_id}] Started")

            result = func(*args)

            with self.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE jobs
                    SET status = 'completed',
                        result = :result
                    WHERE job_id = :job_id
                """), {
                    "job_id": job_id,
                    "result": json.dumps(result)
                })

            logger.info(f"[JOB {job_id}] Completed")

        except Exception as e:
            logger.error(f"[JOB {job_id}] Failed: {str(e)}")

            with self.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE jobs
                    SET status = 'failed',
                        error = :error
                    WHERE job_id = :job_id
                """), {
                    "job_id": job_id,
                    "error": str(e)
                })

    def get_job(self, job_id):
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT job_id, status, result, error, created_date
                FROM jobs
                WHERE job_id = :job_id
            """), {"job_id": job_id}).fetchone()

        if not result:
            return {"error": "Job not found"}

        import json

        return {
            "job_id": result.job_id,
            "status": result.status,
            "result": json.loads(result.result) if result.result else None,
            "error": result.error,
            "created_at": str(result.created_date)
        }

    def list_jobs(self):
        with self.engine.connect() as conn:
            results = conn.execute(text("""
                SELECT job_id, status, result, error, created_date
                FROM jobs
                ORDER BY created_date DESC
            """)).fetchall()

        return [
            {
                "job_id": row.job_id,
                "status": row.status,
                "result": json.loads(row.result) if row.result else None,
                "error": row.error,
                "created_at": str(row.created_date)
            }
            for row in results
        ]

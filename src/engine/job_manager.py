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
                SELECT job_id, status, result, error, created_at
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
            "created_at": str(result.created_at)
        }

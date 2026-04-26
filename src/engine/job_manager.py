import threading
import uuid
import logging
import time  #  ADDED

logger = logging.getLogger(__name__)


class JobManager:

    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()

    def create_job(self, func, *args):
        job_id = str(uuid.uuid4())

        logger.info(f"[JOB {job_id}] Creating job")  #  ADDED

        with self.lock:
            self.jobs[job_id] = {
                "status": "running",
                "result": None,
                "error": None,
                "created_at": time.time()  #  ADDED (timestamp for cleanup)
            }

        threading.Thread(
            target=self.run_job,
            args=(job_id, func, args),
            daemon=True
        ).start()

        #  ADDED: Trigger cleanup on new job creation
        self.cleanup_jobs()

        return job_id

    def run_job(self, job_id, func, args):
        start_time = time.time()  #  ADDED

        try:
            logger.info(f"[JOB {job_id}] Started with args={args}")  #  IMPROVED

            result = func(*args)

            duration = round(time.time() - start_time, 2)  #  ADDED

            with self.lock:
                self.jobs[job_id]["status"] = "completed"
                self.jobs[job_id]["result"] = result

            logger.info(f"[JOB {job_id}] Completed successfully in {duration}s")  #  IMPROVED

        except Exception as e:
            duration = round(time.time() - start_time, 2)  #  ADDED

            logger.error(f"[JOB {job_id}] Failed after {duration}s: {str(e)}")

            with self.lock:
                self.jobs[job_id]["status"] = "failed"
                self.jobs[job_id]["error"] = str(e)

    def get_job(self, job_id):
        logger.info(f"[JOB {job_id}] Status requested")  #  ADDED

        job = self.jobs.get(job_id)

        if not job:
            logger.warning(f"[JOB {job_id}] Not found")  #  ADDED
            return {"error": "Job not found"}

        return job

    def cleanup_jobs(self, max_jobs=1000, max_age_minutes=60):
        """
        Cleans up old jobs to prevent memory leaks.
        Keeps:
        - Latest N jobs (max_jobs)
        - Jobs newer than max_age_minutes
        """
        now = time.time()

        with self.lock:
            #  Step 1: Remove jobs older than max_age_minutes
            filtered_jobs = {
                job_id: job
                for job_id, job in self.jobs.items()
                if now - job.get("created_at", now) < max_age_minutes * 60
            }

            #  Step 2: Keep only latest max_jobs
            if len(filtered_jobs) > max_jobs:
                filtered_jobs = dict(list(filtered_jobs.items())[-max_jobs:])

            removed_count = len(self.jobs) - len(filtered_jobs)

            self.jobs = filtered_jobs

        if removed_count > 0:
            logger.info(f"[JOB CLEANUP] Removed {removed_count} old jobs")

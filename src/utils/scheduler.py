from apscheduler.schedulers.background import BackgroundScheduler
from src.tools.sharepoint_tools import sharepoint_to_railway
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

scheduler = BackgroundScheduler()

def start_scheduler():
    """
    Starts daily SharePoint ingestion job
    """

    scheduler.add_job(
        func=lambda: sharepoint_to_railway(
            folder_path="Finance/Reports",   # change as needed
            table_name="finance_reports"
        ),
        trigger="interval",
        hours=24
    )

    scheduler.start()

    logger.info("Scheduler started (runs every 24 hours)")

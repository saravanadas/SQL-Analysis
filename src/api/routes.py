from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from src.engine.job_manager import JobManager
from src.services.sql_server_client import SQLServerClient
from src.services.file_manager import FileManager
from fastapi.responses import FileResponse
from src.utils.security import validate_token, generate_token  #  UPDATED IMPORT
from src.utils.logger import setup_logger
from src.tools.database_tools import load_sql_to_railway
from src.services.sharepoint_client import SharePointClient

router = APIRouter()
job_manager = JobManager()
file_manager = FileManager()
logger = setup_logger(__name__)

class LoadRequest(BaseModel):
    query: str
    table_name: str


@router.post("/load-to-railway")
def load_to_railway_api(request: LoadRequest):
    """
    API to trigger SQL Server → Railway DB pipeline.
    """
    try:
        result = load_sql_to_railway(request.query, request.table_name)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
class SQLRequest(BaseModel):
    query: str


def process_sql_job(query):
    """
    Background job to execute SQL and generate CSV
    """
    try:
        client = SQLServerClient()

        generator = client.execute_query_to_dataframe(query)

        file_id = file_manager.generate_file_id()
        file_path = file_manager.get_file_path(file_id)

        file_manager.write_csv_stream(file_path, generator)

        logger.info(f"[JOB] Completed successfully. file_id={file_id}")

        # =========================
        # GENERATE SECURE DOWNLOAD TOKEN  ADDED
        # =========================
        token = generate_token(file_id)

        return {
            "file_id": file_id,

            # Include token in download URL for secure access   UPDATED
            "download_url": f"/download/{file_id}?token={token}"
        }

    except Exception as e:
        logger.error(f"[JOB] Failed: {str(e)}")
        raise


@router.post("/extract/sql")
def extract_sql(req: SQLRequest):
    """
    Starts async SQL extraction job
    """
    try:
        if not req.query or not req.query.strip():
            raise HTTPException(status_code=400, detail="Query cannot be empty")

        job_id = job_manager.create_job(process_sql_job, req.query)

        logger.info(f"[API] Job created: {job_id}")

        return {
            "job_id": job_id,
            "status": "started"
        }

    except Exception as e:
        logger.error(f"[API] extract_sql failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/job/{job_id}")
def job_status(job_id: str):
    """
    Get job status and result
    """
    job = job_manager.get_job(job_id)

    if "error" in job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job
    
@router.get("/test-sharepoint")
def test_sharepoint():
    sp = SharePointClient()
    
    # List files in root
    files = sp.list_files_in_drive()

    return {
        "status": "success",
        "file_count": len(files),
        "files": files[:5]  # show only first 5
    }


@router.get("/download/{file_id}")
def download(file_id: str, token: str):
    """
    Download generated CSV file
    """
    try:
       

        if not validate_token(file_id, token):
            raise HTTPException(status_code=403, detail="Invalid or expired token")
            
        file_path = file_manager.get_file(file_id)

        if not file_path:
            raise HTTPException(status_code=404, detail="File not found or expired")
            
        logger.info(f"[API] File download: {file_id}")

        return FileResponse(
            path=file_path,
            filename=f"{file_id}.csv",
            media_type="text/csv"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Download failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Download failed")

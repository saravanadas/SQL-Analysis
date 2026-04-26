import os
import pandas as pd
from datetime import datetime
from src.config.settings import settings
from src.utils.logger import setup_logger
import csv
import uuid
import time

logger = setup_logger(__name__)


class FileManager:
    """
    Handles local file generation, storage, and retrieval mechanisms 
    for the Code Interpreter capabilities of the MCP.
    """

    def __init__(self):
        self.output_dir = settings.output_dir

        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            logger.info(f"Created output directory at {self.output_dir}")

    def generate_csv_from_dataframe(self, df: pd.DataFrame, base_filename: str) -> str:
        """
        Converts a Pandas DataFrame to a well-structured CSV file.
        Adds a timestamp to avoid naming collisions.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{base_filename}_{timestamp}.csv"
        filepath = os.path.join(self.output_dir, filename)

        # Generate CSV. index=False prevents pandas row numbers from bleeding into data
        df.to_csv(filepath, index=False, encoding='utf-8')
        logger.info(f"CSV generated: {filepath}")

        return filepath

    def get_file_content_base64(self, filepath: str) -> str:
        """
        Reads a file and converts it to base64 for reliable transmission 
        over the MCP JSON-RPC protocol to the LLM client.
        """
        import base64
        with open(filepath, "rb") as f:
            encoded = base64.b64encode(f.read()).decode('utf-8')
        return encoded

    # ✅ NEW: Generate unique file ID
    def generate_file_id(self) -> str:
        return str(uuid.uuid4())

    # ✅ NEW: Get file path using file_id
    def get_file_path(self, file_id: str) -> str:
        return os.path.join(self.output_dir, f"{file_id}.csv")

    # ✅ NEW: Get file if exists (used in download API)
    def get_file(self, file_id: str) -> str:
        path = self.get_file_path(file_id)
        return path if os.path.exists(path) else None

    # ✅ NEW: Cleanup old files (important for Railway disk limits)
    def cleanup_old_files(self, hours: int = 1):
        now = time.time()

        for file in os.listdir(self.output_dir):
            path = os.path.join(self.output_dir, file)

            if os.path.isfile(path):
                file_age = now - os.stat(path).st_mtime

                if file_age > hours * 3600:
                    try:
                        os.remove(path)
                        logger.info(f"Deleted old file: {path}")
                    except Exception as e:
                        logger.error(f"Failed to delete file {path}: {str(e)}")

    # ✅ FIXED: Proper streaming CSV writer inside class
    def write_csv_stream(self, file_path: str, data_generator):
        """
        Writes CSV in streaming mode using generator (memory efficient).
        """
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = None
            fieldnames = None

            for chunk in data_generator:

                # Skip completely empty chunks
                if chunk is None or len(chunk) == 0:
                    continue

                # Convert DataFrame → list of dicts if needed
                if isinstance(chunk, pd.DataFrame):
                    records = chunk.to_dict(orient="records")
                else:
                    records = chunk

                # Skip if no records after conversion
                if not records:
                    continue

                # Initialize writer safely
                if writer is None:
                    fieldnames = list(records[0].keys())
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()

                # Handle schema mismatch safely (optional protection)
                for row in records:
                    if set(row.keys()) != set(fieldnames):
                        # Normalize row to match header
                        row = {key: row.get(key, None) for key in fieldnames}
                    writer.writerow(row)

        logger.info(f"CSV stream written: {file_path}")
        return file_path

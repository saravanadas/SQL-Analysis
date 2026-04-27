from fastmcp import FastMCP
from src.services.sharepoint_client import SharePointClient
from src.services.file_manager import FileManager
from src.utils.logger import setup_logger
from src.utils.security import generate_token
from src.config.settings import settings
import os
import pandas as pd
from src.services.railway_db_client import RailwayDBClient

logger = setup_logger(__name__)

# =========================================================
# FIX: Lazy initialization
# =========================================================

def get_sp_client():
    return SharePointClient()

def get_file_manager():
    return FileManager()

def get_railway_client():
    return RailwayDBClient()


def register_sharepoint_tools(mcp: FastMCP):
    """Registers SharePoint file management tools to the FastMCP instance."""

    @mcp.tool()
    def list_sharepoint_files(folder_path: str = "") -> str:
        """
        Lists all files and folders in a specific SharePoint directory.
        """
        try:
            sp_client = get_sp_client()
            items = sp_client.list_files(folder_path)

            if not items:
                return "No files found in the specified directory."
                
            result = "SharePoint Files:\n"
            for item in items:
                item_type = "Folder" if "folder" in item else "File"
                result += f"- [{item_type}] {item['name']} (ID: {item['id']})\n"
                
            return result

        except Exception as e:
            logger.error(f"Error listing SharePoint files: {str(e)}")
            raise


    @mcp.tool()
    def download_sharepoint_file(file_id: str, file_name: str) -> str:
        """
        Downloads a file from SharePoint and provides a secure download link.
        """
        try:
            sp_client = get_sp_client()
            file_manager = get_file_manager()

            # Generate unique local file ID
            local_id = file_manager.generate_file_id()
            extension = os.path.splitext(file_name)[1]
            dest_path = file_manager.get_file_path(local_id, extension)

            logger.info(f"Downloading SharePoint file: {file_name} (ID: {file_id})")

            # Fetch download URL from Graph API
            file_metadata = sp_client.get_file_metadata(file_id)

            if "@microsoft.graph.downloadUrl" not in file_metadata:
                raise Exception("Download URL not found for file")

            download_url_sp = file_metadata["@microsoft.graph.downloadUrl"]

            # Download file content
            content = sp_client.download_file(download_url_sp)

            # Save file locally
            with open(dest_path, "wb") as f:
                f.write(content)

            # Generate secure download link for user
            token = generate_token(local_id)
            final_url = f"{settings.app_base_url}/download/{local_id}?token={token}"

            return f"File '{file_name}' downloaded successfully.\n\nDownload Link:\n{final_url}"

        except Exception as e:
            logger.error(f"Download failed for file_id={file_id}: {str(e)}")
            raise


    @mcp.tool()
    def download_sharepoint_folder(folder_path: str = "") -> str:
        """
        Downloads all files from a SharePoint folder and provides download links.
        """
        try:
            sp_client = get_sp_client()
            file_manager = get_file_manager()

            items = sp_client.list_files(folder_path)

            if not items:
                return "No files found in the specified directory."

            download_links = []

            for item in items:
                if "file" not in item:
                    continue

                file_name = item["name"]
                if "@microsoft.graph.downloadUrl" not in item:
                    continue

                download_url_sp = item["@microsoft.graph.downloadUrl"]

                # Save locally
                local_id = file_manager.generate_file_id()
                extension = os.path.splitext(file_name)[1]
                dest_path = file_manager.get_file_path(local_id, extension)

                content = sp_client.download_file(download_url_sp)
                with open(dest_path, "wb") as f:
                    f.write(content)

                # Generate link
                token = generate_token(local_id)
                link = f"{settings.app_base_url}/download/{local_id}?token={token}"
                download_links.append(f"- {file_name}: {link}")

            if not download_links:
                return "No files were available for download in this folder."

            return "Successfully downloaded files from SharePoint:\n" + "\n".join(download_links)

        except Exception as e:
            logger.error(f"Folder download failed: {str(e)}")
            raise


    # =========================================================
    # NEW: SharePoint → Railway ingestion pipeline
    # =========================================================
    @mcp.tool()
    def sharepoint_to_railway(folder_path: str, table_name: str) -> str:
        """
        Downloads files from SharePoint, parses them (CSV/Excel),
        and loads the data into Railway DB.

        Args:
            folder_path: SharePoint folder path
            table_name: Target table in Railway DB

        Returns:
            Status message with total rows loaded
        """
        try:
            sp_client = get_sp_client()
            file_manager = get_file_manager()
            railway_client = get_railway_client()

            railway_client.ensure_tracking_table()
            
            items = sp_client.list_files(folder_path)

            if not items:
                return "No files found in the specified directory."

            total_rows = 0
            first_chunk = True

            for item in items:
                
                file_name = item["name"]

                # ✅ NEW: skip already processed files
                if railway_client.is_file_processed(file_name):
                    logger.info(f"Skipping already processed file: {file_name}")
                    continue

                # Skip folders
                if "file" not in item:
                    continue

                # Only process CSV / Excel files
                if not (file_name.lower().endswith(".csv") or file_name.lower().endswith(".xlsx")):
                    logger.info(f"Skipping unsupported file: {file_name}")
                    continue

                if "@microsoft.graph.downloadUrl" not in item:
                    logger.warning(f"No download URL for file: {file_name}")
                    continue

                download_url = item["@microsoft.graph.downloadUrl"]

                logger.info(f"Processing SharePoint file: {file_name}")

                # Download file
                content = sp_client.download_file(download_url)

                # FIX: unique temp file (prevents overwrite)
                temp_file_id = file_manager.generate_file_id()
                temp_path = os.path.join(file_manager.output_dir, f"{temp_file_id}_{file_name}")

                with open(temp_path, "wb") as f:
                    f.write(content)

                # =========================
                # PARSE FILE
                # =========================
                from src.utils.data_validator import validate_dataframe

                if file_name.lower().endswith(".csv"):
                    df = pd.read_csv(temp_path)
                    df = validate_dataframe(df)
                else:
                    df = pd.read_excel(temp_path)
                    df = validate_dataframe(df)

                if df.empty:
                    logger.warning(f"Skipping empty file: {file_name}")
                    continue

                logger.info(f"Loaded {len(df)} rows from {file_name}")

                # =========================
                # LOAD TO RAILWAY
                # =========================
                if first_chunk:
                    inserted = railway_client.insert_dataframe_chunked(
                        df,
                        table_name,
                        mode="replace"
                    )
                    first_chunk = False
                else:
                    inserted = railway_client.insert_dataframe_chunked(
                        df,
                        table_name,
                        mode="append"
                    )

                total_rows += inserted
                
                # NEW: mark file processed
                railway_client.mark_file_processed(file_name)

                # Progress tracking
                logger.info(f"Total rows processed so far: {total_rows}")

            return f"Successfully loaded {total_rows} rows into '{table_name}' from SharePoint."

        except Exception as e:
            logger.error(f"SharePoint → Railway pipeline failed: {str(e)}")
            raise

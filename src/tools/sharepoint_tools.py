import os
from mcp.server.fastmcp import FastMCP
from src.services.sharepoint_client import SharePointClient
from src.services.file_manager import FileManager
from src.utils.logger import setup_logger
import pandas as pd
from src.services.railway_db_client import RailwayDBClient

logger = setup_logger(__name__)

sp_client = SharePointClient()
file_manager = FileManager()
railway_client = RailwayDBClient()


def register_sharepoint_tools(mcp: FastMCP):
    """Registers SharePoint file management tools to the FastMCP instance."""

    @mcp.tool()
    def list_sharepoint_files(folder_path: str = "") -> str:
        """
        Lists all files and folders in a specific SharePoint directory.
        
        Args:
            folder_path: The relative path inside the SharePoint Document Library. Leave empty for root.
            
        Returns:
            A formatted string listing item names and their unique IDs.
        """
        try:
            # UPDATED: handle pagination inside client
            items = sp_client.list_files(folder_path)

            if not items:
                return "No files found in the specified directory."
                
            result = "SharePoint Files:\n"
            for item in items:
                item_type = "Folder" if "folder" in item else "File"
                result += f"- [{item_type}] {item['name']} (ID: {item['id']})\n"
                
            logger.info(f"Listed {len(items)} SharePoint items from '{folder_path}'")
            return result

        except Exception as e:
            logger.error(f"Error listing SharePoint files: {str(e)}")
            raise


    @mcp.tool()
    def download_sharepoint_file(file_id: str, file_name: str) -> str:
        """
        Downloads a file from SharePoint using its ID and saves it locally.
        
        Args:
            file_id: The unique Microsoft Graph ID of the file.
            file_name: What to name the file locally (including extension).
            
        Returns:
            A status string indicating the file path.
        """
        try:
            # Generate destination path
            dest_path = os.path.join(file_manager.output_dir, file_name)

            logger.info(f"Downloading SharePoint file: {file_name} (ID: {file_id})")

            # UPDATED: first get metadata (to fetch download URL)
            file_metadata = sp_client.get_file_metadata(file_id)

            if "@microsoft.graph.downloadUrl" not in file_metadata:
                raise Exception("Download URL not found for file")

            download_url = file_metadata["@microsoft.graph.downloadUrl"]

            # Download file content
            content = sp_client.download_file(download_url)

            # Save file locally
            with open(dest_path, "wb") as f:
                f.write(content)

            logger.info(f"File saved to {dest_path}")

            return f"File successfully downloaded to {dest_path}."

        except Exception as e:
            logger.error(f"Download failed for file_id={file_id}: {str(e)}")
            raise


    @mcp.tool()
    def download_sharepoint_folder(folder_path: str = "") -> str:
        """
        Downloads all files from a SharePoint folder.
        
        Args:
            folder_path: The relative folder path.
            
        Returns:
            Summary of downloaded files.
        """
        try:
            items = sp_client.list_files(folder_path)

            if not items:
                return "No files found in the specified directory."

            downloaded_count = 0

            for item in items:
                # Skip folders
                if "file" not in item:
                    continue

                file_name = item["name"]

                # Get download URL
                if "@microsoft.graph.downloadUrl" not in item:
                    continue

                download_url = item["@microsoft.graph.downloadUrl"]

                # FIX: prevent overwrite
                file_id_local = file_manager.generate_file_id()
                dest_path = os.path.join(file_manager.output_dir, f"{file_id_local}_{file_name}")

                logger.info(f"Downloading file from folder: {file_name}")

                content = sp_client.download_file(download_url)

                with open(dest_path, "wb") as f:
                    f.write(content)

                downloaded_count += 1

            logger.info(f"Downloaded {downloaded_count} files from '{folder_path}'")

            return f"Downloaded {downloaded_count} files from SharePoint folder."

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
            railway_client.ensure_tracking_table()
            
            items = sp_client.list_files(folder_path)

            if not items:
                return "No files found in the specified directory."

            total_rows = 0
            first_chunk = True

            for item in items:
                
                file_name = item["name"]

                # Skip already processed files
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
                
                # Mark file processed
                railway_client.mark_file_processed(file_name)

                # Progress tracking
                logger.info(f"Total rows processed so far: {total_rows}")

            return f"Successfully loaded {total_rows} rows into '{table_name}' from SharePoint."

        except Exception as e:
            logger.error(f"SharePoint → Railway pipeline failed: {str(e)}")
            raise

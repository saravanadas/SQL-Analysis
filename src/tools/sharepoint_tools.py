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

def _download_sharepoint_file_to_path(sp_client, file_manager, file_id: str, file_name: str):
    file_metadata = sp_client.get_file_metadata(file_id)

    if "@microsoft.graph.downloadUrl" not in file_metadata:
        raise Exception("Download URL not found for file")

    extension = os.path.splitext(file_name)[1]
    local_id = file_manager.generate_file_id()
    dest_path = file_manager.get_file_path(local_id, extension)
    content = sp_client.download_file(file_metadata["@microsoft.graph.downloadUrl"])

    with open(dest_path, "wb") as f:
        f.write(content)

    return local_id, dest_path

def _extract_pdf_pages(pdf_path: str):
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    pages = []

    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append({
            "page_number": index,
            "page_text": text.strip()
        })

    return pages


def register_sharepoint_tools(mcp: FastMCP):
    """Registers SharePoint file management tools to the FastMCP instance."""

    @mcp.tool()
    def search_sharepoint_pdfs_recursive(
        folder_path: str,
        batch_number: str = "",
        max_items: int = 1000
    ) -> str:
        """
        Recursively searches SharePoint under a folder and returns PDF files.
        Excel files and files ending with report.pdf are ignored.
        """
        try:
            sp_client = get_sp_client()
            items = sp_client.list_files_recursive(folder_path, max_items=max_items)

            matches = []
            batch_filter = batch_number.strip().lower()

            for item in items:
                if "file" not in item:
                    continue

                file_name = item["name"]
                file_name_lower = file_name.lower()
                item_path = item.get("_path", file_name)

                if not file_name_lower.endswith(".pdf"):
                    continue
                if file_name_lower.endswith("report.pdf"):
                    continue
                if batch_filter and batch_filter not in item_path.lower():
                    continue

                matches.append({
                    "name": file_name,
                    "id": item["id"],
                    "path": item_path
                })

            if not matches:
                return "No matching PDF files found."

            result = f"Found {len(matches)} matching PDF file(s):\n"
            for match in matches[:100]:
                result += f"- {match['path']} (ID: {match['id']})\n"

            if len(matches) > 100:
                result += f"\n... and {len(matches) - 100} more files."

            return result

        except Exception as e:
            logger.error(f"Recursive SharePoint PDF search failed: {str(e)}")
            raise


    @mcp.tool()
    def extract_sharepoint_pdf_text(file_id: str, file_name: str, max_preview_chars: int = 6000) -> str:
        """
        Downloads a SharePoint PDF and extracts server-side text from its pages.
        Returns a preview suitable for agent parsing.
        """
        try:
            sp_client = get_sp_client()
            file_manager = get_file_manager()

            local_id, pdf_path = _download_sharepoint_file_to_path(
                sp_client,
                file_manager,
                file_id,
                file_name
            )
            pages = _extract_pdf_pages(pdf_path)
            combined = "\n\n".join(
                f"--- Page {page['page_number']} ---\n{page['page_text']}"
                for page in pages
            )

            token = generate_token(local_id)
            download_url = f"{settings.app_base_url}/download/{local_id}?token={token}"
            preview = combined[:max_preview_chars]

            if len(combined) > max_preview_chars:
                preview += f"\n\n... truncated {len(combined) - max_preview_chars} characters."

            return (
                f"Extracted text from '{file_name}' ({len(pages)} page(s)).\n"
                f"Download Link:\n{download_url}\n\n"
                f"{preview}"
            )

        except Exception as e:
            logger.error(f"SharePoint PDF text extraction failed for file_id={file_id}: {str(e)}")
            raise


    @mcp.tool()
    def stage_sharepoint_pdf_text_to_railway(
        file_id: str,
        file_name: str,
        sharepoint_path: str = "",
        table_name: str = "sharepoint_pdf_text"
    ) -> str:
        """
        Downloads a SharePoint PDF, extracts page text, and stores it in PostgreSQL.
        This gives the agent a server-side PDF extraction path for reconciliation.
        """
        try:
            sp_client = get_sp_client()
            file_manager = get_file_manager()
            railway_client = get_railway_client()

            _, pdf_path = _download_sharepoint_file_to_path(
                sp_client,
                file_manager,
                file_id,
                file_name
            )
            pages = _extract_pdf_pages(pdf_path)

            rows = [
                {
                    "file_id": file_id,
                    "file_name": file_name,
                    "sharepoint_path": sharepoint_path,
                    "page_number": page["page_number"],
                    "page_text": page["page_text"],
                }
                for page in pages
            ]

            inserted = railway_client.store_pdf_text_rows(rows, table_name=table_name)

            return (
                f"Stored {inserted} PDF page text row(s) for '{file_name}' "
                f"into PostgreSQL table '{table_name}'."
            )

        except Exception as e:
            logger.error(f"SharePoint PDF staging failed for file_id={file_id}: {str(e)}")
            raise


    @mcp.tool()
    def stage_invoice_lines_to_railway(
        rows: list[dict],
        table_name: str = "sharepoint_invoice_lines",
        mode: str = "append"
    ) -> str:
        """
        Stores parsed invoice line dictionaries into PostgreSQL.
        Use this after the agent extracts invoice number, PO, quantity,
        unit price, line amount, and source PDF details from PDF text.
        """
        try:
            if mode not in {"append", "replace"}:
                raise ValueError("mode must be 'append' or 'replace'")

            if not rows:
                return "No invoice rows provided."

            railway_client = get_railway_client()
            df = pd.DataFrame(rows)
            inserted = railway_client.insert_dataframe_chunked(df, table_name, mode=mode)

            return f"Stored {inserted} invoice line row(s) into PostgreSQL table '{table_name}'."

        except Exception as e:
            logger.error(f"Invoice line staging failed: {str(e)}")
            raise


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

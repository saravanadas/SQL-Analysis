import requests
from src.config.settings import settings
from src.utils.logger import setup_logger
# from src.utils.retry import retry   # ❌ Removed (causing delay + 502)

logger = setup_logger(__name__)

class SharePointClient:
    """
    Client for interacting with SharePoint via Microsoft Graph API.
    """

    def __init__(self):
        self.client_id = settings.sp_client_id
        self.client_secret = settings.sp_client_secret
        self.tenant_id = settings.sp_tenant_id

        self.base_url = "https://graph.microsoft.com/v1.0"
        self.token = self._get_access_token()

    def _get_access_token(self):
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }

        # ✅ Reduced timeout to avoid Railway 502
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()

        token = response.json()["access_token"]
        logger.info("SharePoint access token acquired")
        return token

    def _headers(self):
        """
        Returns headers with a valid access token.
        Automatically refreshes token if needed.
        """
        if not self.token:
            self.token = self._get_access_token()

        return {
            "Authorization": f"Bearer {self.token}"
        }

    def list_files(self, folder_path: str = ""):
        """
        List files in a SharePoint folder (with pagination support)
        LIMITED to avoid timeout in Railway
        """

        site_id = settings.sp_site_id
        drive_id = settings.sp_drive_id   

        # Handle root vs subfolder
        if folder_path:
            url = f"{self.base_url}/sites/{site_id}/drives/{drive_id}/root:/{folder_path}:/children"
        else:
            url = f"{self.base_url}/sites/{site_id}/drives/{drive_id}/root/children"

        files = []

        # ✅ LIMIT results to avoid timeout
        max_items = 20

        while url and len(files) < max_items:
            logger.info(f"[DEBUG] Calling SharePoint API: {url}")

            # ✅ Timeout added
            response = requests.get(url, headers=self._headers(), timeout=10)

            # 🔁 Auto token refresh
            if response.status_code == 401:
                logger.info("Token expired. Refreshing...")
                self.token = self._get_access_token()
                response = requests.get(url, headers=self._headers(), timeout=10)

            response.raise_for_status()

            data = response.json()
            files.extend(data.get("value", []))

            # pagination
            url = data.get("@odata.nextLink")

        logger.info(f"Retrieved {len(files)} files from SharePoint")
        return files

    def download_file(self, download_url: str):
        """
        Download file content from SharePoint
        """

        # ✅ Timeout reduced
        response = requests.get(download_url, timeout=15)

        if response.status_code == 401:
            logger.info("Token expired. Refreshing...")
            self.token = self._get_access_token()
            response = requests.get(download_url, timeout=15)

        response.raise_for_status()
        return response.content
        
    def get_file_metadata(self, file_id: str):
        """
        Fetch metadata for a file (used to get download URL)
        """

        url = f"{self.base_url}/sites/{settings.sp_site_id}/drives/{settings.sp_drive_id}/items/{file_id}"

        # ✅ Timeout added
        response = requests.get(url, headers=self._headers(), timeout=10)

        if response.status_code == 401:
            logger.info("Token expired. Refreshing...")
            self.token = self._get_access_token()
            response = requests.get(url, headers=self._headers(), timeout=10)

        response.raise_for_status()
        
        return response.json()

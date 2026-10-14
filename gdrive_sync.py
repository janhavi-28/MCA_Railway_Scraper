#!/usr/bin/env python3
"""
Google Drive Cloud Auto-Sync Module for MCA 2026 Corporate Scraper
==================================================================
Periodically syncs companies_2026_enriched.csv to a specified Google Drive folder.
Supports Service Account JSON file or GDRIVE_CREDENTIALS_JSON environment variable.
Updates the existing file in-place rather than creating duplicates.
"""

import os
import json
from pathlib import Path
from typing import Optional

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    GDRIVE_AVAILABLE = True
except ImportError:
    GDRIVE_AVAILABLE = False


class GDriveSync:
    """Manages secure headless file uploads to Google Drive using a Service Account."""

    SCOPES = ["https://www.googleapis.com/auth/drive"]

    def __init__(
        self,
        folder_id: Optional[str] = None,
        credentials_json: Optional[str] = None,
        credentials_file: Optional[Path] = Path("gdrive_credentials.json")
    ):
        self.folder_id = folder_id or os.getenv("GDRIVE_FOLDER_ID", "").strip()
        self.credentials_json = credentials_json or os.getenv("GDRIVE_CREDENTIALS_JSON", "").strip()
        self.credentials_file = credentials_file
        self._service = None
        self._file_id = None
        self._init_service()

    def _init_service(self):
        if not GDRIVE_AVAILABLE:
            return

        creds = None
        try:
            # Method 1: Environment variable with raw JSON string (Railway)
            if self.credentials_json:
                info = json.loads(self.credentials_json)
                creds = service_account.Credentials.from_service_account_info(
                    info, scopes=self.SCOPES
                )
            # Method 2: Local JSON credentials file
            elif self.credentials_file and Path(self.credentials_file).exists():
                creds = service_account.Credentials.from_service_account_file(
                    str(self.credentials_file), scopes=self.SCOPES
                )

            if creds:
                self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        except Exception as e:
            print(f"⚠️ Google Drive init failed: {e}")
            self._service = None

    @property
    def is_configured(self) -> bool:
        return self._service is not None and bool(self.folder_id)

    def sync_file(self, file_path: Path) -> bool:
        """Upload or update file in Google Drive in-place."""
        if not self.is_configured:
            return False

        file_path = Path(file_path)
        if not file_path.exists():
            return False

        filename = file_path.name
        try:
            # 1. Find existing file in target folder
            if not self._file_id:
                query = f"name = '{filename}' and '{self.folder_id}' in parents and trashed = false"
                response = self._service.files().list(
                    q=query, spaces="drive", fields="files(id, name)"
                ).execute()
                files = response.get("files", [])
                if files:
                    self._file_id = files[0]["id"]

            media = MediaFileUpload(str(file_path), mimetype="text/csv", resumable=True)

            # 2. Update existing file or create new one
            if self._file_id:
                self._service.files().update(
                    fileId=self._file_id,
                    media_body=media
                ).execute()
                print(f"☁️ [Google Drive] Successfully synced {filename} (ID: {self._file_id})")
            else:
                file_metadata = {
                    "name": filename,
                    "parents": [self.folder_id]
                }
                created = self._service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields="id"
                ).execute()
                self._file_id = created.get("id")
                print(f"☁️ [Google Drive] Created new backup {filename} (ID: {self._file_id})")

            return True

        except Exception as e:
            print(f"⚠️ [Google Drive] Sync failed: {e}")
            return False


if __name__ == "__main__":
    # Test script standalone
    syncer = GDriveSync()
    if syncer.is_configured:
        print("✅ Google Drive Sync configured properly!")
        target = Path("companies_2026_enriched.csv")
        if target.exists():
            syncer.sync_file(target)
    else:
        print("ℹ️ Google Drive Sync is not configured yet.")
        print("   Required: GDRIVE_FOLDER_ID and Service Account credentials JSON.")

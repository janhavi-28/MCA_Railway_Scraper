"""
Thread-safe, async-friendly logging system for MCA company enrichment.
Maintains separate audit logs:
- logs/success.log
- logs/errors.log
- logs/not_found.log
"""

import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)

SUCCESS_LOG_PATH = LOGS_DIR / "success.log"
ERRORS_LOG_PATH = LOGS_DIR / "errors.log"
NOT_FOUND_LOG_PATH = LOGS_DIR / "not_found.log"

# Setup root console logger
console_formatter = logging.Formatter(
    fmt="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(console_formatter)
console_handler.setLevel(logging.INFO)

logger = logging.getLogger("mca_enricher")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(console_handler)


def log_success(cin: str, company_name: str, website: str, email: str, web_conf: str, email_conf: str, notes: str = "") -> None:
    """Log an enriched company to logs/success.log."""
    timestamp = datetime.now().isoformat()
    entry = (
        f"[{timestamp}] SUCCESS | CIN: {cin} | Company: {company_name} | "
        f"Website: {website} (Confidence: {web_conf}) | "
        f"Email: {email} (Confidence: {email_conf}) | Notes: {notes}\n"
    )
    with open(SUCCESS_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(entry)
    logger.info(f"Enriched: {company_name} [{cin}] -> {website} | {email}")


def log_error(cin: str, company_name: str, stage: str, error_msg: str, exc_info: Optional[str] = None) -> None:
    """Log an unhandled error or fatal exception to logs/errors.log."""
    timestamp = datetime.now().isoformat()
    entry = (
        f"[{timestamp}] ERROR | CIN: {cin} | Company: {company_name} | "
        f"Stage: {stage} | Reason: {error_msg}"
    )
    if exc_info:
        entry += f"\nTraceback:\n{exc_info}"
    entry += "\n"
    with open(ERRORS_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(entry)
    logger.error(f"Error [{stage}] for {company_name} [{cin}]: {error_msg}")


def log_not_found(cin: str, company_name: str, reason: str) -> None:
    """Log a failed lookup/discovery to logs/not_found.log."""
    timestamp = datetime.now().isoformat()
    entry = (
        f"[{timestamp}] NOT_FOUND | CIN: {cin} | Company: {company_name} | "
        f"Reason: {reason}\n"
    )
    with open(NOT_FOUND_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(entry)
    logger.warning(f"Not Found for {company_name} [{cin}]: {reason}")

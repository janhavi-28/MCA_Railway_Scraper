"""
MCA 2025-26 Company Enrichment Scraper Package v2.
"""

from .config import OUTPUT_COLUMNS, NOT_FOUND
from .search import SearchEngine
from .validator import validate_website
from .extractor import (
    extract_emails_from_html,
    pick_best_email,
    extract_contact_page,
    extract_linkedin,
    extract_instagram,
)
from .enricher import CompanyEnricher
from .runner import BatchPipeline

__version__ = "2.0.0"

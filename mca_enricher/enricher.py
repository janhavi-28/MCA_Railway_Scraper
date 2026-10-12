"""
Core enrichment pipeline v2.

Pipeline per company:
  Search → Validate Website → Crawl Pages → Extract Email / Contact / LinkedIn / Instagram

Output columns (strict order):
  Company | Website | Email | Contact Form | Instagram | LinkedIn
"""

import asyncio
import traceback
from typing import Dict, Any
import aiohttp

from .config import NOT_FOUND
from .search import SearchEngine
from .validator import validate_website
from .crawler import WebsiteCrawler
from .extractor import (
    extract_emails_from_html,
    pick_best_email,
    extract_contact_page,
    extract_linkedin,
    extract_instagram,
)
from .logger import logger


class CompanyEnricher:
    """Enriches a single MCA company record."""

    def __init__(self, search_engine: SearchEngine):
        self.search_engine = search_engine

    def _empty_result(self, company_name: str) -> Dict[str, str]:
        return {
            "Company":      company_name,
            "Website":      NOT_FOUND,
            "Email":        NOT_FOUND,
            "Contact Form": NOT_FOUND,
            "Instagram":    NOT_FOUND,
            "LinkedIn":     NOT_FOUND,
        }

    async def enrich(
        self,
        company_data: Dict[str, Any],
        session: aiohttp.ClientSession,
    ) -> Dict[str, str]:
        """Run full enrichment for one company row."""

        # ── Flexible column mapping ──────────────────────────────────────────
        company_name = str(
            company_data.get("Company Name") or
            company_data.get("company_name", "")
        ).strip()

        cin = str(
            company_data.get("CIN") or
            company_data.get("cin", "")
        ).strip()

        state = str(
            company_data.get("State") or
            company_data.get("Company State") or
            company_data.get("state", "")
        ).strip()

        industry = str(
            company_data.get("Industry") or
            company_data.get("Company Industrial Classification") or
            company_data.get("industry", "")
        ).strip()

        address = str(
            company_data.get("Address") or
            company_data.get("Company Address") or
            company_data.get("address", "")
        ).strip()

        result = self._empty_result(company_name)

        if not company_name:
            return result

        try:
            crawler = WebsiteCrawler(session)

            # ── Step 1: Search ───────────────────────────────────────────────
            candidates = await self.search_engine.discover_company_urls(
                session, company_name, cin=cin
            )
            if not candidates:
                logger.debug(f"[{cin}] No search candidates: {company_name}")
                return result

            # ── Step 2: Validate each candidate ─────────────────────────────
            verified_url    = None
            verified_conf   = None

            for candidate in candidates:
                cand_url = candidate["url"]
                html, _status = await crawler.fetch_html_aiohttp(cand_url)
                if not html:
                    continue

                is_valid, conf, notes = validate_website(
                    html=html,
                    target_url=cand_url,
                    company_name=company_name,
                    cin=cin,
                    state=state,
                    address=address,
                    industry=industry,
                )

                if is_valid:
                    verified_url  = cand_url
                    verified_conf = conf
                    logger.debug(
                        f"[{cin}] Website verified [{conf}]: {cand_url} ({notes})"
                    )
                    break

            if not verified_url:
                logger.debug(
                    f"[{cin}] No valid website after checking {len(candidates)} candidates: {company_name}"
                )
                return result

            result["Website"] = verified_url

            # ── Step 3: Crawl key pages ──────────────────────────────────────
            crawled_pages, page_urls = await crawler.crawl_site(verified_url)
            if not crawled_pages:
                return result

            # ── Step 4: Email ────────────────────────────────────────────────
            all_emails = set()
            for page_html in crawled_pages.values():
                all_emails.update(extract_emails_from_html(page_html))

            result["Email"] = pick_best_email(all_emails, verified_url)

            # ── Step 5: Contact Form ─────────────────────────────────────────
            result["Contact Form"] = extract_contact_page(crawled_pages, verified_url, page_urls)

            # ── Step 6: LinkedIn (company page only) ─────────────────────────
            result["LinkedIn"] = extract_linkedin(crawled_pages, company_name=company_name)

            # ── Step 7: Instagram (official handle only) ─────────────────────
            result["Instagram"] = extract_instagram(crawled_pages, company_name=company_name)

            logger.info(
                f"[DONE] {company_name} | {verified_url} | {result['Email']} | "
                f"LI={result['LinkedIn']} | IG={result['Instagram']}"
            )

        except Exception as exc:
            tb = traceback.format_exc()
            logger.error(f"[{cin}] Enrichment error for '{company_name}': {exc}\n{tb}")

        return result

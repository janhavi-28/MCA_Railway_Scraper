"""
Search Engine Orchestrator for MCA Company Enrichment.
No paid APIs, no API keys used.

Strategy (in order):
  1. Bing HTML Search (Primary - reliable, good India localization)
  2. DuckDuckGo Search (Secondary fallback)
  3. Google HTML Search (Tertiary fallback)
  4. CIN-based search on MCA lookup sites to find website hints
"""

import asyncio
import base64
import random
import re
import urllib.parse
from typing import List, Dict, Optional
import aiohttp
from bs4 import BeautifulSoup
import tldextract

from .config import USER_AGENTS, BLACKLISTED_DOMAINS
from .logger import logger

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None


def extract_registered_domain(url: str) -> str:
    """Extract registered domain (e.g., 'example.com' from 'https://sub.example.com/page')."""
    try:
        ext = tldextract.extract(url)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}".lower()
        return ""
    except Exception:
        return ""


def is_blacklisted_domain(url: str) -> bool:
    """Check if the URL belongs to a blacklisted domain, directory, or aggregator profile."""
    if not url or not url.startswith("http"):
        return True

    reg_domain = extract_registered_domain(url)
    if not reg_domain or reg_domain in BLACKLISTED_DOMAINS:
        return True

    parsed = urllib.parse.urlparse(url)
    netloc = parsed.netloc.lower()
    for b in BLACKLISTED_DOMAINS:
        if netloc == b or netloc.endswith("." + b):
            return True

    # Generic MCA Aggregator Profile Detector
    path_lower = parsed.path.lower()
    aggregator_path_patterns = [
        r"^/(?:company|companies|company-profile|corporate|ind/corporate|mca-company-detail)",
        r"^/[a-zA-Z0-9_\-]+-[uUlL]\d{5}[a-zA-Z]{2}\d{4}[a-zA-Z]{3}\d{6}",
    ]
    for pattern in aggregator_path_patterns:
        if re.search(pattern, path_lower):
            return True

    return False


def clean_url(url: str) -> str:
    """Clean tracking params and normalize scheme."""
    try:
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qsl(parsed.query)
        clean_params = [
            (k, v) for k, v in query_params
            if not k.startswith("utm_") and k not in ("fbclid", "gclid", "ref", "source")
        ]
        new_query = urllib.parse.urlencode(clean_params)
        scheme = parsed.scheme if parsed.scheme in ("http", "https") else "https"
        clean = urllib.parse.urlunparse((
            scheme,
            parsed.netloc.lower(),
            parsed.path,
            parsed.params,
            new_query,
            ""
        ))
        return clean.rstrip("/")
    except Exception:
        return url


def decode_bing_url(bing_href: str) -> str:
    """Decodes Bing's redirect link containing u=a1<base64> parameter to the real URL."""
    try:
        parsed = urllib.parse.urlparse(bing_href)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        if "u" in params and params["u"].startswith("a1"):
            raw_b64 = params["u"][2:]
            padding = len(raw_b64) % 4
            if padding:
                raw_b64 += "=" * (4 - padding)
            decoded = base64.b64decode(raw_b64).decode("utf-8", errors="ignore")
            if decoded.startswith("http"):
                return decoded
    except Exception:
        pass
    return bing_href


def _random_agent() -> str:
    return random.choice(USER_AGENTS)


class SearchEngine:
    """
    Search engine wrapper orchestrating Bing (Primary), DuckDuckGo (Secondary),
    and Google HTML (Tertiary) with rate limiting and automatic retry.
    """

    def __init__(self, request_delay: float = 1.0):
        self.request_delay = request_delay
        self._lock = asyncio.Lock()

    async def _bing_search(
        self, session: aiohttp.ClientSession, query: str, max_results: int = 6
    ) -> List[Dict[str, str]]:
        """Scrape Bing HTML search results (India localized). Primary engine."""
        results: List[Dict[str, str]] = []
        encoded_query = urllib.parse.quote_plus(query)
        url = (
            f"https://www.bing.com/search"
            f"?q={encoded_query}&count={max_results * 2}&cc=IN&setlang=en-in&first=1"
        )
        headers = {
            "User-Agent": _random_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        try:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=12)
            ) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")
                    for li in soup.select("li.b_algo"):
                        a_tag = li.select_one("h2 a")
                        if not a_tag or not a_tag.get("href"):
                            continue
                        raw_href = a_tag["href"]
                        target_url = decode_bing_url(raw_href)
                        if is_blacklisted_domain(target_url):
                            continue
                        snippet_tag = li.select_one(
                            "div.b_caption p, p.b_lineclamp2, p.b_lineclamp3, div.b_snippet"
                        )
                        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
                        title = a_tag.get_text(strip=True)
                        results.append({
                            "title": title,
                            "url": clean_url(target_url),
                            "snippet": snippet,
                            "source": "Bing",
                        })
                        if len(results) >= max_results:
                            break
                elif resp.status == 429:
                    logger.warning("Bing rate-limit (429). Backing off.")
                    await asyncio.sleep(5)
        except Exception as e:
            logger.debug(f"Bing search error for '{query}': {e}")

        return results

    async def _ddg_search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """Run DuckDuckGo search in a thread executor (Secondary fallback)."""
        if DDGS is None:
            return []

        def _fetch() -> List[Dict[str, str]]:
            results = []
            try:
                with DDGS() as ddgs:
                    for item in ddgs.text(query, max_results=max_results):
                        href = item.get("href", "")
                        if href and not is_blacklisted_domain(href):
                            results.append({
                                "title": item.get("title", ""),
                                "url": clean_url(href),
                                "snippet": item.get("body", ""),
                                "source": "DuckDuckGo",
                            })
            except Exception as e:
                logger.debug(f"DuckDuckGo error for '{query}': {e}")
            return results

        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _fetch), timeout=15
            )
        except asyncio.TimeoutError:
            logger.debug(f"DuckDuckGo timed out for '{query}'")
            return []

    async def _google_search(
        self, session: aiohttp.ClientSession, query: str, max_results: int = 5
    ) -> List[Dict[str, str]]:
        """Scrape Google HTML search results (Tertiary fallback)."""
        results: List[Dict[str, str]] = []
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://www.google.com/search?q={encoded_query}&num={max_results + 5}&hl=en&gl=IN"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        }

        try:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=12)
            ) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")
                    # Try multiple selector patterns Google uses
                    for selector in ["div.g", "div[data-sokoban-container]", "div.MjjYud"]:
                        blocks = soup.select(selector)
                        for block in blocks:
                            a_tag = block.select_one("a[href]")
                            if not a_tag:
                                continue
                            href = a_tag.get("href", "")
                            if not href.startswith("http") or "google.com" in href:
                                continue
                            if is_blacklisted_domain(href):
                                continue
                            title_tag = block.select_one("h3")
                            title = title_tag.get_text(strip=True) if title_tag else ""
                            snippet_tag = block.select_one("div.VwiC3b, span.aCOpRe, div[data-sncf]")
                            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
                            results.append({
                                "title": title,
                                "url": clean_url(href),
                                "snippet": snippet,
                                "source": "Google",
                            })
                            if len(results) >= max_results:
                                break
                        if results:
                            break
        except Exception as e:
            logger.debug(f"Google search error for '{query}': {e}")

        return results

    async def _startpage_search(
        self, session: aiohttp.ClientSession, query: str, max_results: int = 5
    ) -> List[Dict[str, str]]:
        """Scrape Startpage (privacy-friendly Google proxy) as quaternary fallback."""
        results: List[Dict[str, str]] = []
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://www.startpage.com/search?q={encoded_query}&language=english"
        headers = {
            "User-Agent": _random_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=12)
            ) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")
                    for a_tag in soup.select("a.result-link, a[data-testid='result-url-a']"):
                        href = a_tag.get("href", "")
                        if not href.startswith("http") or is_blacklisted_domain(href):
                            continue
                        results.append({
                            "title": a_tag.get_text(strip=True),
                            "url": clean_url(href),
                            "snippet": "",
                            "source": "Startpage",
                        })
                        if len(results) >= max_results:
                            break
        except Exception as e:
            logger.debug(f"Startpage search error for '{query}': {e}")
        return results

    async def search(
        self, session: aiohttp.ClientSession, query: str, max_results: int = 6
    ) -> List[Dict[str, str]]:
        """
        Execute search using a waterfall strategy:
          1. DuckDuckGo (Primary - high precision)
          2. Bing HTML (Secondary fallback)
          3. Google HTML (Tertiary fallback)
          4. Startpage (Quaternary fallback)
        Returns first non-empty result set.
        """
        async with self._lock:
            await asyncio.sleep(self.request_delay + random.uniform(0.1, 0.4))

        # 1. DuckDuckGo (Primary)
        results = await self._ddg_search(query, max_results=max_results)
        if results:
            return results

        # 2. Bing HTML (Secondary)
        logger.debug(f"DDG returned 0 for '{query}'. Trying Bing.")
        results = await self._bing_search(session, query, max_results=max_results)
        if results:
            return results

        # 3. Google HTML (Tertiary)
        logger.debug(f"Bing returned 0 for '{query}'. Trying Google.")
        results = await self._google_search(session, query, max_results=max_results)
        if results:
            return results

        # 4. Startpage (Quaternary)
        logger.debug(f"Google returned 0 for '{query}'. Trying Startpage.")
        results = await self._startpage_search(session, query, max_results=max_results)
        return results

    async def discover_company_urls(
        self,
        session: aiohttp.ClientSession,
        company_name: str,
        cin: str = "",
    ) -> List[Dict[str, str]]:
        """
        Adaptive multi-stage search strategy:
          Stage 1: '<Company Name> official website'
          Stage 2: '"<Company Name>"' (quoted exact name fallback)
          Stage 3: '<Core Brand> official website' (legal suffix stripped)
          Stage 4: '<CIN> official website' (CIN search fallback)
        """
        # Clean company name
        clean_name = re.sub(r"[\(\)\[\]]", " ", company_name).strip()

        # Extract core brand by stripping Indian company legal suffixes
        core_name = re.sub(
            r"\b(PRIVATE LIMITED|PVT\.?\s*LTD\.?|LIMITED|LTD\.?|LLP|OPC|PRODUCER COMPANY LIMITED)\b",
            "",
            clean_name,
            flags=re.IGNORECASE,
        ).strip()
        core_name = re.sub(r"\s+", " ", core_name).strip()

        seen_domains: set = set()
        all_candidates: List[Dict[str, str]] = []

        def _add_unique(results: List[Dict[str, str]]) -> List[Dict[str, str]]:
            unique = []
            for r in results:
                dom = extract_registered_domain(r["url"])
                if dom and dom not in seen_domains:
                    seen_domains.add(dom)
                    unique.append(r)
            return unique

        # Stage 1: Company name + official website
        q1 = f"{clean_name} official website"
        r1 = await self.search(session, q1, max_results=6)
        all_candidates.extend(_add_unique(r1))

        # Stage 2: Quoted exact name (if stage 1 returned few results)
        if len(all_candidates) < 2:
            q2 = f'"{clean_name}"'
            r2 = await self.search(session, q2, max_results=5)
            all_candidates.extend(_add_unique(r2))

        # Stage 3: Core brand name (stripped suffix) + official website
        if len(all_candidates) < 2 and core_name and core_name.lower() != clean_name.lower() and len(core_name) > 3:
            q3 = f"{core_name} official website"
            r3 = await self.search(session, q3, max_results=5)
            all_candidates.extend(_add_unique(r3))

        # Stage 4: CIN-based search
        if len(all_candidates) < 2 and cin and len(cin) >= 10:
            q4 = f"{cin} official website"
            r4 = await self.search(session, q4, max_results=4)
            all_candidates.extend(_add_unique(r4))

        return all_candidates

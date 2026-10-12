"""
High-performance asynchronous website crawler v2.
Uses aiohttp with realistic browser headers + Playwright fallback for JS-heavy / bot-blocked sites.
"""

import asyncio
import random
import re
import urllib.parse
from typing import Dict, List, Set, Optional, Tuple
import aiohttp
from bs4 import BeautifulSoup
import tldextract

from .config import (
    USER_AGENTS,
    REQUEST_TIMEOUT_SECONDS,
    PLAYWRIGHT_TIMEOUT_MS,
    CRAWL_SUBPATHS,
)
from .logger import logger

try:
    from playwright.async_api import async_playwright, Browser, Playwright
except ImportError:
    async_playwright = None
    Browser = None
    Playwright = None


def is_same_domain(base_url: str, target_url: str) -> bool:
    """Check if target_url belongs to the same registered domain as base_url."""
    try:
        base_ext = tldextract.extract(base_url)
        target_ext = tldextract.extract(target_url)
        return (base_ext.domain == target_ext.domain) and (base_ext.suffix == target_ext.suffix)
    except Exception:
        return False


def normalize_page_url(base_url: str, href: str) -> Optional[str]:
    """Resolve relative URLs and ensure HTTP/HTTPS."""
    try:
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            return None
        joined = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(joined)
        if parsed.scheme not in ("http", "https"):
            return None
        # Clean fragment
        clean = urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path,
            parsed.params,
            "",  # drop query for crawling static content
            ""   # drop fragment
        ))
        return clean.rstrip("/")
    except Exception:
        return None


def requires_javascript_rendering(html: str) -> bool:
    """
    Check if the HTML indicates an unrendered Single Page Application (SPA).
    """
    if not html:
        return True
    
    lower_html = html.lower()
    
    # Common SPA empty root indicators
    spa_indicators = [
        '<div id="root"></div>',
        '<div id="app"></div>',
        '<div id="__next"></div>',
        '<app-root></app-root>',
        "you need to enable javascript to run this app",
        "please enable javascript to continue",
        "javascript is required",
    ]
    for ind in spa_indicators:
        if ind in lower_html:
            return True

    # Very small HTML with script bundles
    if len(html) < 600 and ("bundle.js" in lower_html or "main.js" in lower_html or "app.js" in lower_html):
        return True

    return False


class PlaywrightManager:
    """Singleton manager for persistent Playwright Chromium browser."""
    _instance = None
    _lock = asyncio.Lock()

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    @classmethod
    async def get_browser(cls) -> Optional[Browser]:
        if async_playwright is None:
            return None
        async with cls._lock:
            if cls._instance is None:
                cls._instance = PlaywrightManager()
            if cls._instance._browser is None or not cls._instance._browser.is_connected():
                try:
                    cls._instance._playwright = await async_playwright().start()
                    cls._instance._browser = await cls._instance._playwright.chromium.launch(
                        headless=True,
                        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
                    )
                except Exception as e:
                    logger.warning(f"Could not initialize Playwright: {e}")
                    return None
            return cls._instance._browser

    @classmethod
    async def close_browser(cls):
        async with cls._lock:
            if cls._instance:
                if cls._instance._browser:
                    try:
                        await cls._instance._browser.close()
                    except Exception:
                        pass
                if cls._instance._playwright:
                    try:
                        await cls._instance._playwright.stop()
                    except Exception:
                        pass
                cls._instance = None


class WebsiteCrawler:
    """
    Crawls targeted company subpaths and extracts HTML pages.
    """

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def fetch_html_aiohttp(self, url: str) -> Tuple[Optional[str], int]:
        """Fetch page HTML using aiohttp with realistic browser headers and retries."""
        retries = 3
        for attempt in range(retries):
            # Rotate User-Agent on each attempt
            ua = random.choice(USER_AGENTS)
            headers = {
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            }
            try:
                timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
                async with self.session.get(
                    url, headers=headers, timeout=timeout,
                    ssl=False, allow_redirects=True
                ) as resp:
                    status = resp.status
                    if status == 200:
                        ct = resp.headers.get("Content-Type", "").lower()
                        if "text" in ct or "html" in ct or "xml" in ct:
                            html = await resp.text(errors="replace")
                            return html, status
                        # Non-HTML (PDF, etc.) — skip
                        return None, status
                    elif status in (301, 302, 307, 308):
                        # aiohttp follows redirects automatically; unexpected if we land here
                        return None, status
                    elif status == 403:
                        # Try Playwright to bypass bot-detection
                        logger.debug(f"403 on {url}, trying Playwright")
                        html = await self.fetch_html_playwright(url)
                        if html:
                            return html, 200
                        return None, 403
                    elif status == 429:
                        # Rate-limited — back off
                        wait = 3.0 * (attempt + 1)
                        logger.debug(f"429 on {url}, waiting {wait}s")
                        await asyncio.sleep(wait)
                        continue
                    else:
                        return None, status
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.debug(f"aiohttp error attempt {attempt+1} for {url}: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(1.5 * (attempt + 1))
                else:
                    return None, 0
            except Exception as e:
                logger.debug(f"Unexpected error fetching {url}: {e}")
                return None, 0
        return None, 0

    async def fetch_html_playwright(self, url: str) -> Optional[str]:
        """Render SPA pages using headless Chromium only when necessary."""
        browser = await PlaywrightManager.get_browser()
        if not browser:
            return None

        context = None
        page = None
        try:
            context = await browser.new_context(
                user_agent=USER_AGENTS[0],
                viewport={"width": 1280, "height": 800},
                ignore_https_errors=True
            )
            page = await context.new_page()
            # Fast timeout for SPA rendering
            await page.goto(url, wait_until="domcontentloaded", timeout=PLAYWRIGHT_TIMEOUT_MS)
            await page.wait_for_timeout(1000)
            content = await page.content()
            return content
        except Exception as e:
            logger.debug(f"Playwright render failed for {url}: {e}")
            return None
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            if context:
                try:
                    await context.close()
                except Exception:
                    pass

    async def crawl_site(self, root_url: str) -> Tuple[Dict[str, str], Dict[str, str]]:
        """
        Crawl key pages on the site:
        - Root/Home
        - Discovered navigation links (about, contact, team, etc.)
        - Fallback subpaths (/about, /contact, etc.)
        Returns tuple: (crawled_pages: {category: html}, page_urls: {category: url})
        """
        crawled_pages: Dict[str, str] = {}
        page_urls: Dict[str, str] = {}
        visited_urls: Set[str] = set()

        # Step 1: Fetch Root Page
        root_clean = root_url.rstrip("/")
        home_html, status = await self.fetch_html_aiohttp(root_clean)
        
        # Check if JavaScript rendering is needed for home page
        if not home_html or requires_javascript_rendering(home_html):
            logger.debug(f"Attempting Playwright JS rendering for {root_clean}")
            pw_html = await self.fetch_html_playwright(root_clean)
            if pw_html:
                home_html = pw_html

        if not home_html:
            return crawled_pages, page_urls

        crawled_pages["/"] = home_html
        page_urls["/"] = root_clean
        visited_urls.add(root_clean)

        # Step 2: Discover internal links from home HTML
        soup = BeautifulSoup(home_html, "html.parser")
        discovered_urls: Dict[str, str] = {} # {category: url}

        category_patterns = {
            "about": r"about(-?us)?|who-we-are|company",
            "leadership": r"leadership|team|management|founders|board",
            "contact": r"contact(-?us)?|get-in-touch|reach-us",
            "privacy": r"privacy(-?policy)?",
            "terms": r"terms(-?(and|of)-?conditions)?",
        }

        for a in soup.find_all("a", href=True):
            raw_href = a["href"]
            full_url = normalize_page_url(root_clean, raw_href)
            if not full_url or not is_same_domain(root_clean, full_url):
                continue

            lower_path = urllib.parse.urlparse(full_url).path.lower()
            for cat, pattern in category_patterns.items():
                if cat not in discovered_urls and re.search(pattern, lower_path):
                    discovered_urls[cat] = full_url

        # Step 3: Complement with standard crawl subpaths if not discovered
        urls_to_crawl: List[Tuple[str, str]] = []
        for cat, url in discovered_urls.items():
            if url not in visited_urls:
                urls_to_crawl.append((cat, url))

        # Add common default paths if key categories are still missing
        if "about" not in discovered_urls:
            urls_to_crawl.append(("about", f"{root_clean}/about"))
        if "contact" not in discovered_urls:
            urls_to_crawl.append(("contact", f"{root_clean}/contact"))
        if "leadership" not in discovered_urls:
            urls_to_crawl.append(("leadership", f"{root_clean}/team"))

        # Fetch in parallel with limit (max 5 subpages)
        tasks = []
        for cat, url in urls_to_crawl[:5]:
            if url not in visited_urls:
                visited_urls.add(url)
                tasks.append(self._fetch_subpage(cat, url))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, tuple) and len(res) == 3 and res[2]:
                    cat, actual_url, html = res
                    crawled_pages[cat] = html
                    page_urls[cat] = actual_url

        return crawled_pages, page_urls

    async def _fetch_subpage(self, category: str, url: str) -> Tuple[str, str, Optional[str]]:
        html, status = await self.fetch_html_aiohttp(url)
        return category, url, html

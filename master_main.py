#!/usr/bin/env python3
"""
Master Company Intelligence Agent
==================================
On-demand corporate intelligence scraper with 2-tier search:
1. Tier 1: Instant local database/cache lookup (0 ms)
   - Checks 'company_master_intelligence.csv'
   - Scans 'cleaned_csv/' and 'main_csv/' (over 3.2 million companies)
2. Tier 2: Headless live multi-source web scraping
   - Fast DuckDuckGo Search (ddgs) & Bing snippets
   - Wikipedia Corporate Infobox API
   - Official Website Deep Crawl (/contact, /about, /leadership)
   - Headless Playwright Google Maps Fallback

Output Schema (16 Columns):
1.  CIN
2.  Company Name
3.  Company Registration Date
4.  Company Class
5.  Company Industrial Classification
6.  Company State
7.  Company Address
8.  Authorized Capital
9.  Paidup Capital
10. Company Website
11. Company Email
12. Company Contact Form
13. Employee Strength
14. Key People (Director / CEO / Stakeholder)
15. Company LinkedIn
16. Company Instagram

Usage:
    python master_main.py                     # Interactive terminal search
    python master_main.py --company "Tata Motors"
    python master_main.py --company "Infosys" --no-cache
"""

import argparse
import asyncio
import csv
import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Set
import aiohttp
from bs4 import BeautifulSoup
import tldextract
from playwright.async_api import async_playwright, Browser, BrowserContext

# DDGS Search Engine
try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

# Ensure UTF-8 output on Windows console
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ── Configuration & Constants ─────────────────────────────────────────────────

CACHE_CSV_FILE = Path("company_master_intelligence.csv")
CLEANED_DIR    = Path("cleaned_csv")
MAIN_DIR       = Path("main_csv")

OUTPUT_COLUMNS = [
    "CIN",
    "Company Name",
    "Company Registration Date",
    "Company Class",
    "Company Industrial Classification",
    "Company State",
    "Company Address",
    "Authorized Capital",
    "Paidup Capital",
    "Company Website",
    "Company Email",
    "Company Contact Number",
    "Company Contact Form",
    "Employee Strength",
    "Key People (Director / CEO / Stakeholder)",
    "Company LinkedIn",
    "Company Instagram",
]

NOT_FOUND = "NOT_FOUND"


class ProxyManager:
    """Thread-safe proxy rotation manager loading from proxies.txt."""

    def __init__(self, proxy_file: Path = Path("proxies.txt")):
        self.proxy_file = proxy_file
        self._proxies: List[str] = []
        self._index = 0
        self.reload()

    def reload(self):
        proxies = []
        env_proxies = os.getenv("PROXIES_LIST")
        if env_proxies:
            for line in env_proxies.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("http://") or line.startswith("https://") or line.startswith("socks5://"):
                    proxies.append(line)
                else:
                    parts = line.split(":")
                    if len(parts) == 4:
                        ip, port, user, pwd = parts
                        proxies.append(f"http://{user}:{pwd}@{ip}:{port}")
                    elif len(parts) == 2:
                        ip, port = parts
                        proxies.append(f"http://{ip}:{port}")

        candidates = [self.proxy_file, Path("Webshare 10 proxies.txt")]
        for p_path in candidates:
            if p_path.exists():
                with open(p_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if line.startswith("http://") or line.startswith("https://") or line.startswith("socks5://"):
                            proxies.append(line)
                        else:
                            parts = line.split(":")
                            if len(parts) == 4:
                                ip, port, user, pwd = parts
                                proxies.append(f"http://{user}:{pwd}@{ip}:{port}")
                            elif len(parts) == 2:
                                ip, port = parts
                                proxies.append(f"http://{ip}:{port}")
        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for p in proxies:
            if p not in seen:
                seen.add(p)
                deduped.append(p)
        self._proxies = deduped

    def get_proxy(self) -> Optional[str]:
        if not self._proxies:
            return None
        p = self._proxies[self._index % len(self._proxies)]
        self._index += 1
        return p


PROXY_MANAGER = ProxyManager()



USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

CIN_REGEX = re.compile(r"\b([LUlu]\d{5}[A-Za-z]{2}\d{4}[A-Za-z]{3}\d{6})\b")
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
HEADCOUNT_REGEX = re.compile(
    r"\b(\d{1,3}(?:,\d{3})*(?:\s*\+|-\d{1,3}(?:,\d{3})*|\s*to\s*\d+)?\s*(?:employees|staff|team members|people|workforce))\b",
    re.IGNORECASE
)

def clean_phone_number(raw_num: str) -> Optional[str]:
    """Clean, format, and validate an Indian phone number (Mobile, Landline, Toll-Free)."""
    if not raw_num:
        return None
    val = str(raw_num).strip()

    # 1. Toll-Free 1800 / 1860 numbers
    m_toll = re.search(r"\b(1800[\s\-]?[0-9]{3}[\s\-]?[0-9]{3,4}|1860[\s\-]?[0-9]{3}[\s\-]?[0-9]{3,4})\b", val)
    if m_toll:
        return re.sub(r"[\s\-]+", "-", m_toll.group(1))

    # 2. Extract digits & leading +
    digits = re.sub(r"[^\d+]", "", val)
    if not digits:
        return None

    # Normalize country code
    if digits.startswith("+91"):
        body = digits[3:]
    elif digits.startswith("91") and len(digits) == 12 and digits[2] in "6789":
        body = digits[2:]
    elif digits.startswith("0") and len(digits) == 11 and digits[1] in "6789":
        body = digits[1:]
    else:
        body = digits.lstrip("0")

    # Mobile: 10 digits starting with 6, 7, 8, 9
    if len(body) == 10 and body[0] in "6789":
        # Discard fake numbers (9999999999, 1234567890)
        if len(set(body)) <= 2:
            return None
        return f"+91 {body[:5]} {body[5:]}"

    # Landline with STD code (10-11 digits)
    if 10 <= len(digits) <= 11 and digits.startswith("0"):
        return f"{digits[:3]}-{digits[3:]}" if len(digits) == 10 else f"{digits[:4]}-{digits[4:]}"

    return None

BLACKLISTED_WEBSITE_DOMAINS: Set[str] = {
    "falconebiz.com", "tofler.in", "thecompanycheck.com", "mca.gov.in",
    "indiafilings.com", "startuptalky.com", "crunchbase.com", "tracxn.com",
    "justdial.com", "indiamart.com", "tradeindia.com", "exportersindia.com",
    "allindiaitr.com", "buysellprivatelimited.com", "infomint.co.in",
    "alchetron.com", "wikipedia.org", "zoominfo.com", "rocketreach.co",
    "apollo.io", "carwale.com", "bikewale.com", "cardekho.com",
    "bikedekho.com", "zigwheels.com", "gaadi.com", "autoportal.com",
    "housing.com", "nobroker.in", "magicbricks.com", "99acres.com",
    "shiksha.com", "collegedunia.com", "planetexim.net", "bizidex.com",
    "sansadhan.com", "anekantprakashan.com", "webmd.com", "britannica.com",
    "dictionary.com", "oxfordlearnersdictionaries.com", "cambridge.org",
    "merriam-webster.com", "investopedia.com", "startupindia.gov.in",
    "mca21.gov.in", "zaubacorp.com", "quickcompany.in", "vakilsearch.com",
    "connect2india.com", "instafinancials.com", "corpintel.io",
    "mastersindia.co", "credhive.in", "edgeinsights.in", "gowox.com",
    "qorpiq.com", "neusourcestartup.com", "fundoodata.com", "companydetails.in",
    "instacompany.in", "corporatedir.com", "cybex.in", "volza.com",
    "company360.in", "legalkart.com", "f6s.com", "dnb.com", "kompass.com",
    "opencorporates.com", "globalindia.org", "mergedbiz.com",
    "glassdoor.com", "glassdoor.co.in", "ambitionbox.com", "indeed.com",
    "naukri.com", "internshala.com", "shine.com", "moneycontrol.com",
    "bseindia.com", "nseindia.com", "screener.in", "groww.in",
    "zerodha.com", "angelone.in", "finology.in", "economictimes.indiatimes.com",
    "timesofindia.indiatimes.com", "businessstandard.com", "livemint.com",
    "ndtv.com", "thehindubusinessline.com", "google.com", "google.co.in",
    "bing.com", "duckduckgo.com", "yahoo.com", "msn.com", "yandex.com",
    "amazon.in", "amazon.com", "flipkart.com", "sulekha.com", "yellowpages.in",
    "quikr.com", "olx.in", "dial4trade.com", "facebook.com", "youtube.com",
    "twitter.com", "x.com", "pinterest.com", "reddit.com", "quora.com",
    "medium.com", "github.com", "gitlab.com", "tiktok.com", "vimeo.com",
    "threads.net", "amarujala.com", "iadv.io", "insiderbiz.in", "registerkaro.in",
    "mycorporateinfo.com"
}

FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "rediffmail.com",
    "zoho.com", "protonmail.com", "icloud.com", "aol.com", "mail.com"
}

INDIAN_STATES = [
    "Maharashtra", "Karnataka", "Delhi", "Tamil Nadu", "Gujarat",
    "Telangana", "Uttar Pradesh", "West Bengal", "Haryana", "Rajasthan",
    "Kerala", "Madhya Pradesh", "Punjab", "Andhra Pradesh", "Bihar",
    "Odisha", "Assam", "Goa", "Uttarakhand", "Jharkhand", "Chhattisgarh",
    "Himachal Pradesh", "Jammu and Kashmir", "Chandigarh", "Puducherry"
]


GENERIC_WORDS = {
    "india", "global", "group", "holdings", "technologies", "enterprise",
    "international", "services", "solution", "solutions", "private",
    "limited", "trading", "venture", "ventures", "industries", "pvt", "ltd"
}


def normalize_company_name(name: str) -> str:
    """Normalize legal company name for robust cross-matching."""
    if not name:
        return ""
    cleaned = re.sub(r"[^\w\s]", " ", name.upper())
    cleaned = re.sub(
        r"\b(PRIVATE LIMITED|PVT\s*LTD|LIMITED|LTD|LLP|OPC|PRODUCER COMPANY LIMITED)\b",
        "",
        cleaned,
        flags=re.IGNORECASE
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def extract_registered_domain(url: str) -> str:
    """Extract base registered domain (e.g. 'tatamotors.com' from 'https://cv.tatamotors.com')."""
    try:
        ext = tldextract.extract(url)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}".lower()
    except Exception:
        pass
    return ""


def is_blacklisted_domain(url: str) -> bool:
    """Check if URL belongs to aggregator or directory."""
    if not url or not url.startswith("http"):
        return True
    dom = extract_registered_domain(url)
    if not dom or dom in BLACKLISTED_WEBSITE_DOMAINS:
        return True
    return False


INDIAN_LOCATIONS = {
    "chennai", "mumbai", "delhi", "newdelhi", "bengaluru", "bangalore",
    "hyderabad", "kolkata", "pune", "ahmedabad", "jaipur", "surat",
    "lucknow", "kanpur", "nagpur", "indore", "thane", "bhopal",
    "visakhapatnam", "patna", "vadodara", "ghaziabad", "ludhiana",
    "agra", "nashik", "faridabad", "meerut", "rajkot", "varanasi",
    "srinagar", "aurangabad", "dhanbad", "amritsar", "navi", "allahabad",
    "prayagraj", "ranchi", "howrah", "coimbatore", "jabalpur", "gwalior",
    "vijayawada", "jodhpur", "madurai", "raipur", "kota", "guwahati",
    "chandigarh", "solan", "baddi", "noida", "gurugram", "gurgaon",
    "kochi", "cochin", "trivandrum", "thiruvananthapuram", "mysore",
    "mysuru", "hubli", "dharwad", "belgaum", "belagavi", "mangalore",
    "mangaluru", "salem", "tiruchirappalli", "trichy", "tiruppur",
    "calicut", "kozhikode", "shimla", "dehradun", "haridwar", "panaji",
    # States
    "maharashtra", "karnataka", "tamilnadu", "tamil", "nadu", "gujarat",
    "telangana", "uttarpradesh", "uttar", "pradesh", "westbengal", "bengal",
    "haryana", "rajasthan", "kerala", "madhyapradesh", "madhya", "punjab",
    "andhrapradesh", "andhra", "bihar", "odisha", "orissa", "assam",
    "goa", "uttarakhand", "jharkhand", "chhattisgarh", "himachalpradesh",
    "himachal", "kashmir", "jammu", "puducherry", "pondicherry"
}


def get_distinctive_brand_tokens(company_name: str) -> List[str]:
    """Extract significant distinctive tokens from company legal name, stripping locations and generic terms."""
    norm = normalize_company_name(company_name).lower()
    GENERIC = {
        "india", "global", "group", "holdings", "technologies", "technology",
        "enterprise", "enterprises", "international", "services", "service",
        "solution", "solutions", "private", "limited", "trading", "venture",
        "ventures", "industries", "industry", "pvt", "ltd", "corp", "corporation",
        "consultancy", "consulting", "management", "systems", "system",
        "tech", "infotech", "software", "digital", "associates", "agency",
        "agencies", "co", "company", "commercial"
    } | INDIAN_LOCATIONS
    tokens = [t for t in norm.split() if len(t) >= 3 and t not in GENERIC]
    if not tokens:
        tokens = [t for t in norm.split() if len(t) >= 3 and t not in INDIAN_LOCATIONS]
    if not tokens:
        tokens = [t for t in norm.split() if len(t) >= 3]
    return tokens


def is_domain_relevant_to_company(domain: str, company_name: str) -> bool:
    """Verify that discovered domain matches the whole company brand without mixing with unrelated words."""
    tokens = get_distinctive_brand_tokens(company_name)
    if not tokens:
        return False

    # Extract only the domain body without the TLD suffix (e.g. 'learnindia' from 'learnindia.app')
    ext = tldextract.extract(domain)
    dom_stem = (ext.domain or "").lower().replace("-", "")
    if not dom_stem:
        dom_stem = domain.lower().replace(".", "").replace("-", "")

    full_brand = "".join(tokens)

    def _token_in_dom(token: str) -> bool:
        t_clean = token.lower()
        if t_clean in dom_stem:
            return True
        # Handle plural / singular stemming (e.g. granite vs granites, lab vs labs)
        if t_clean.endswith("s") and t_clean[:-1] in dom_stem:
            return True
        if (t_clean + "s") in dom_stem:
            return True
        return False

    # If company has multiple distinctive tokens (e.g. ['culmen', 'exim']), domain MUST match all tokens
    if len(tokens) > 1:
        return full_brand in dom_stem or all(_token_in_dom(t) for t in tokens)
    else:
        return _token_in_dom(tokens[0])


# ── Local Cache Manager ───────────────────────────────────────────────────────

class LocalIntelligenceCache:
    """Manages fast lookup and auto-updating in company_master_intelligence.csv."""

    def __init__(self, cache_file: Path = CACHE_CSV_FILE):
        self.cache_file = cache_file
        self.cache_by_name: Dict[str, Dict[str, str]] = {}
        self.cache_by_cin: Dict[str, Dict[str, str]] = {}
        self._load_cache()

    def _load_cache(self):
        if not self.cache_file.exists():
            with open(self.cache_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
                writer.writeheader()
            return

        try:
            with open(self.cache_file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = (row.get("Company Name") or "").strip().upper()
                    cin  = (row.get("CIN") or "").strip().upper()
                    if name:
                        self.cache_by_name[name] = row
                        norm_n = normalize_company_name(name)
                        if norm_n:
                            self.cache_by_name[norm_n] = row
                    if cin:
                        self.cache_by_cin[cin] = row
        except Exception as e:
            print(f"[CACHE] Warning loading cache: {e}")

    def lookup(self, query: str) -> Optional[Dict[str, str]]:
        """Check cache strictly by exact legal name, CIN, or exact normalized name."""
        q = query.strip().upper()
        if q in self.cache_by_name:
            return dict(self.cache_by_name[q])
        if q in self.cache_by_cin:
            return dict(self.cache_by_cin[q])

        norm_q = normalize_company_name(q)
        if norm_q and norm_q in self.cache_by_name:
            return dict(self.cache_by_name[norm_q])

        # Strict exact normalized equality across all cached items (no partial substring matching)
        for name, row in self.cache_by_name.items():
            norm_target = normalize_company_name(name)
            if norm_q and norm_target and norm_q == norm_target:
                return dict(row)
        return None

    def search_local_csvs(self, query: str) -> Optional[Dict[str, str]]:
        """Search cleaned_csv or main_csv. Strictly matches exact CIN, exact legal name, or exact normalized name."""
        search_dirs = [CLEANED_DIR, MAIN_DIR]
        q = query.strip().upper()
        norm_q = normalize_company_name(q)

        for s_dir in search_dirs:
            if not s_dir.exists():
                continue
            for csv_file in sorted(s_dir.glob("*.csv")):
                try:
                    with open(csv_file, "r", encoding="utf-8-sig", errors="replace") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            c_name = (row.get("Company Name") or "").strip().upper()
                            c_cin  = (row.get("CIN") or "").strip().upper()
                            norm_c = normalize_company_name(c_name)

                            # Strict match: exact legal name, exact CIN, or exact normalized name
                            if q == c_name or q == c_cin or (norm_q and norm_c and norm_q == norm_c):
                                return {
                                    "CIN": row.get("CIN", "").strip(),
                                    "Company Name": row.get("Company Name", "").strip(),
                                    "Company Registration Date": row.get("Company Registration Date", "").strip(),
                                    "Company Class": row.get("Company Class", "").strip(),
                                    "Company Industrial Classification": row.get("Company Industrial Classification", "").strip(),
                                    "Company State": row.get("Company State", "").strip(),
                                    "Company Address": row.get("Company Address", "").strip(),
                                    "Authorized Capital": row.get("Authorized Capital", "").strip(),
                                    "Paidup Capital": row.get("Paidup Capital", "").strip(),
                                    "Company Website": row.get("Company Website", "").strip(),
                                    "Company Email": row.get("Company Email", "").strip(),
                                    "Company Contact Form": row.get("Company Contact Form", "").strip(),
                                    "Employee Strength": row.get("Employee Strength", "").strip(),
                                    "Key People (Director / CEO / Stakeholder)": row.get("Key People (Director / CEO / Stakeholder)", "").strip(),
                                    "Company LinkedIn": row.get("Company LinkedIn", "").strip(),
                                    "Company Instagram": row.get("Company Instagram", "").strip(),
                                }
                except Exception:
                    continue
        return None

    def save_or_update(self, record: Dict[str, str]):
        """Persist new or updated record to company_master_intelligence.csv."""
        name = record.get("Company Name", "").strip().upper()
        cin  = record.get("CIN", "").strip().upper()
        norm_name = normalize_company_name(name)

        if name:
            self.cache_by_name[name] = record
        if norm_name:
            self.cache_by_name[norm_name] = record
        if cin:
            self.cache_by_cin[cin] = record

        existing_rows: List[Dict[str, str]] = []
        updated = False

        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        r_name = (row.get("Company Name") or "").strip().upper()
                        r_cin  = (row.get("CIN") or "").strip().upper()
                        r_norm = normalize_company_name(r_name)

                        # Match by CIN or normalized company name
                        if (cin and r_cin == cin) or (norm_name and r_norm == norm_name):
                            for k in OUTPUT_COLUMNS:
                                if record.get(k):
                                    row[k] = record[k]
                            existing_rows.append(row)
                            updated = True
                        else:
                            existing_rows.append(row)
            except Exception:
                pass

        if not updated:
            existing_rows.append(record)

        with open(self.cache_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            writer.writerows(existing_rows)


# ── Live Multi-Source Scraper Engine ──────────────────────────────────────────

class LiveCompanyScraper:
    """Multi-source async corporate intelligence scraper."""

    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

    async def init_browser(self, p):
        self.browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        self.context = await self.browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800}
        )

    # ── 1. Wikipedia API Infobox (Instant Enterprise Intelligence) ────────────
    async def scrape_wikipedia_infobox(
        self,
        company_name: str,
        session: aiohttp.ClientSession
    ) -> Dict[str, Any]:
        """Fetch Wikipedia corporate infobox for instant employees, key people, and website."""
        data = {"employees": "", "key_people": [], "website": "", "hq": ""}
        clean_name = normalize_company_name(company_name)

        # Query Wikipedia API with compliant User-Agent and Title-Cased query
        title_name = normalize_company_name(company_name).title()
        url = (
            f"https://en.wikipedia.org/w/api.php?action=query&prop=revisions&rvprop=content&rvslots=*"
            f"&titles={urllib.parse.quote(title_name)}&redirects=1&format=json"
        )
        headers = {"User-Agent": "CorporateIntelligenceBot/1.0 (https://aivatika.com; dev@aivatika.com)"}

        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    pages = res_json.get("query", {}).get("pages", {})
                    for pid, pdata in pages.items():
                        if pid == "-1":
                            continue
                        revs = pdata.get("revisions", [])
                        if not revs:
                            continue
                        wikitext = revs[0].get("slots", {}).get("main", {}).get("*", "")

                        fields = {}
                        for m in re.finditer(r"\|\s*([a-zA-Z_]+)\s*=\s*(.*?)(?=\n\||\n\}\})", wikitext, re.DOTALL):
                            k = m.group(1).strip()
                            v = m.group(2).strip()

                            # Extract website from wikitext directly before stripping macros
                            if k == "website" and not data["website"]:
                                w_m = re.search(r"(?:https?://[^\s\|\]\}]+|www\.[^\s\|\]\}]+)", v)
                                if w_m:
                                    raw_w = w_m.group(0).rstrip("/").rstrip("}")
                                    data["website"] = raw_w if raw_w.startswith("http") else f"https://{raw_w}"

                            # Extract key people [[Name]] directly from wikitext
                            if k == "key_people" and not data["key_people"]:
                                kp_names = re.findall(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", v)
                                for kn in kp_names:
                                    kn_clean = re.sub(r"\b(Chairman|CEO|Managing Director|MD|Executive)\b", "", kn, flags=re.I).strip()
                                    if len(kn_clean) > 3 and not re.search(r"\d", kn_clean) and kn_clean not in data["key_people"]:
                                        data["key_people"].append(kn_clean)

                            v_clean = re.sub(r"<ref.*?(?:/>|</ref>)", "", v, flags=re.DOTALL)
                            v_clean = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", v_clean)
                            v_clean = re.sub(r"\{\{.*?\}\}", "", v_clean, flags=re.DOTALL)
                            v_clean = re.sub(r"\s+", " ", v_clean).strip()
                            fields[k] = v_clean

                        if fields.get("num_employees") and not data["employees"]:
                            data["employees"] = fields["num_employees"]

                        if not data["website"] and fields.get("website"):
                            w_raw = fields["website"]
                            w_match = re.search(r"(?:https?://[^\s\|\]\}]+|www\.[^\s\|\]\}]+)", w_raw)
                            if w_match:
                                raw_w = w_match.group(0).rstrip("/").rstrip("}")
                                data["website"] = raw_w if raw_w.startswith("http") else f"https://{raw_w}"

                        hq = fields.get("hq_location_city") or fields.get("location_city") or fields.get("hq_location")
                        if hq:
                            data["hq"] = hq
        except Exception:
            pass

        return data

    # ── 2. Official Website Discovery via Search ──────────────────────────────
    async def discover_website_via_search(
        self,
        company_name: str,
        company_state: str = "",
        session: Optional[aiohttp.ClientSession] = None
    ) -> str:
        """Find official website using DDG Instant Answer API & DDGS html text search."""
        clean_name = normalize_company_name(company_name)

        # Step A: DuckDuckGo Instant Answer API (Zero block / instant corporate website)
        try:
            ddg_api_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(clean_name)}&format=json"
            async with aiohttp.ClientSession() as sess:
                async with sess.get(ddg_api_url, timeout=aiohttp.ClientTimeout(total=4)) as r:
                    if r.status == 200:
                        d = await r.json(content_type=None)
                        results = d.get("Results", [])
                        if results and results[0].get("FirstURL"):
                            u = results[0]["FirstURL"]
                            if not is_blacklisted_domain(u) and u.startswith("http"):
                                if await self.is_candidate_website_valid(u, company_name, company_state, session):
                                    return u
        except Exception:
            pass

        if DDGS is None:
            return ""

        brand_tokens = get_distinctive_brand_tokens(company_name)
        core_brand = " ".join(brand_tokens).title() if brand_tokens else clean_name

        queries = [f"{clean_name} official website"]
        if core_brand.lower() != clean_name.lower() and len(core_brand) >= 3:
            queries.append(f"{core_brand} website")

        def _run_search(q: str):
            p = PROXY_MANAGER.get_proxy()
            if p:
                try:
                    with DDGS(proxy=p, timeout=3.0) as ddgs:
                        res = list(ddgs.text(q, max_results=3, backend="lite"))
                        if res:
                            return res
                except Exception:
                    pass
            # Fallback to direct local network only if no proxy configured
            try:
                with DDGS(timeout=2.0) as ddgs:
                    return list(ddgs.text(q, max_results=3, backend="lite"))
            except Exception:
                pass
            return []

        loop = asyncio.get_running_loop()

        for q in queries:
            try:
                results = await loop.run_in_executor(None, _run_search, q)
                for item in results:
                    href = item.get("href", "")
                    if href and not is_blacklisted_domain(href) and href.startswith("http"):
                        dom = extract_registered_domain(href)
                        if not dom:
                            continue
                        if not is_domain_relevant_to_company(dom, company_name):
                            continue

                        # Check candidate URLs with original scheme first (HTTP or HTTPS)
                        orig_scheme = "http" if href.startswith("http://") else "https"
                        candidates = [
                            f"{orig_scheme}://www.{dom}",
                            f"{orig_scheme}://{dom}",
                        ]
                        # If HTTPS was attempted, also fallback to HTTP for sites with unverified SSL
                        if orig_scheme == "https":
                            candidates.append(f"http://www.{dom}")
                            candidates.append(f"http://{dom}")
                        else:
                            candidates.append(f"https://www.{dom}")

                        for cand_url in candidates:
                            if await self.is_candidate_website_valid(cand_url, company_name, company_state, session):
                                return cand_url
            except Exception:
                continue

        return ""

    async def is_candidate_website_valid(
        self,
        url: str,
        company_name: str,
        company_state: str = "",
        session: Optional[aiohttp.ClientSession] = None
    ) -> bool:
        """Verify that candidate domain has genuine corporate relevance to the Indian entity.
        Requires whole-name matching and Indian geographic/statutory verification.
        Never trusts .in domains blindly.
        """
        if not url:
            return False
        dom = extract_registered_domain(url).lower()
        if not dom:
            return False

        # ── Gate 1: Whole-Name Brand Token Matching on Domain ─────────────────
        if not is_domain_relevant_to_company(dom, company_name):
            return False

        tokens = get_distinctive_brand_tokens(company_name)
        full_brand = " ".join(tokens)

        # ── Gate 2 & 3: Fetch page and verify Whole Name + Indian Geo ─────────
        async def _check(sess):
            try:
                p = PROXY_MANAGER.get_proxy()
                get_kwargs = {
                    "headers": BROWSER_HEADERS,
                    "timeout": aiohttp.ClientTimeout(total=3.5),
                    "ssl": False,
                }
                if p:
                    get_kwargs["proxy"] = p
                async with sess.get(url, **get_kwargs) as resp:
                    if resp.status == 200:
                        raw_html = await resp.text(errors="replace")
                        # Strip script, style, svg to eliminate base64 and minified JS/CSS noise
                        clean = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", raw_html, flags=re.DOTALL | re.I)
                        clean = re.sub(r"<[^>]+>", " ", clean)
                        clean_text = " ".join(clean.split()).lower()

                        # Must match full brand phrase or all tokens in page text (with plural/singular support)
                        name_match = (full_brand in clean_text) or all(t in clean_text or t.rstrip("s") in clean_text for t in tokens)
                        if not name_match:
                            return False

                        # Must have verifiable Indian corporate presence
                        has_indian_geo = (
                            bool(re.search(r"\bindia\b", clean_text))
                            or bool(re.search(r"(?:\+91[\s\-]?[6-9]\d{4}[\s\-]?[0-9]{5}|\b\+91\s*[6-9]\d{9}\b|\(\+91\))", clean_text))
                            or bool(re.search(r"\b(?:pvt\.?\s*ltd\.?|private\s+limited|llp)\b", clean_text))
                            or bool(company_state and len(company_state) >= 3 and re.search(r"\b" + re.escape(company_state.lower()) + r"\b", clean_text))
                        )
                        if not has_indian_geo:
                            return False

                        # Reject obvious international sites that have no Indian office
                        intl_indicators = ["united states", "headquarters: usa", "virginia, usa", "london, uk", "spain", "australia"]
                        if any(ind in clean_text for ind in intl_indicators) and not bool(re.search(r"\b(?:india|\+91)\b", clean_text)):
                            return False

                        return True
            except Exception:
                pass
            return False

        if session:
            return await _check(session)
        else:
            async with aiohttp.ClientSession(headers=BROWSER_HEADERS) as s:
                return await _check(s)

    # ── 3. Official Website Crawler (Email, Contact Form, Leadership, Headcount) ──
    async def scrape_official_website(
        self,
        website_url: str,
        session: aiohttp.ClientSession
    ) -> Dict[str, Any]:
        """Crawl official website across /contact, /about, and /leadership subpages."""
        info = {
            "website": website_url,
            "email": "",
            "phone": "",
            "contact_form": "",
            "employee_strength": "",
            "key_people": [],
            "linkedin": "",
            "instagram": "",
            "address": "",
            "state": "",
        }
        if not website_url or not website_url.startswith("http"):
            return info

        registered_domain = extract_registered_domain(website_url)
        base_clean = website_url.rstrip("/")

        subpaths = [
            "",
            "/contact",
            "/contact-us",
            "/about",
            "/about-us",
        ]

        for path in subpaths:
            # If we already have email, phone, contact form, address, and key people, stop early!
            if info["email"] and info["phone"] and info["contact_form"] and info["address"] and len(info["key_people"]) >= 2:
                break

            target_url = f"{base_clean}{path}" if path else base_clean
            try:
                p = PROXY_MANAGER.get_proxy()
                s_kwargs = {
                    "headers": BROWSER_HEADERS,
                    "timeout": aiohttp.ClientTimeout(total=4),
                    "ssl": False,
                }
                if p:
                    s_kwargs["proxy"] = p
                async with session.get(target_url, **s_kwargs) as resp:
                    if resp.status != 200:
                        continue
                    html = await resp.text(errors="replace")
                    soup = BeautifulSoup(html, "html.parser")
                    text = soup.get_text(separator=" ", strip=True)

                    # 0. Structured Data (JSON-LD) extraction for official address, email, phone, social
                    for s_tag in soup.find_all("script", type="application/ld+json"):
                        try:
                            import json
                            raw_s = s_tag.string or s_tag.get_text()
                            if raw_s:
                                s_data = json.loads(raw_s.strip())
                                s_items = s_data if isinstance(s_data, list) else [s_data]
                                for item in s_items:
                                    if not isinstance(item, dict):
                                        continue
                                    # Address & State
                                    addr_obj = item.get("address")
                                    if isinstance(addr_obj, dict) and not info["address"]:
                                        loc = addr_obj.get("addressLocality", "")
                                        reg = addr_obj.get("addressRegion", "")
                                        cnt = addr_obj.get("addressCountry", "")
                                        parts = [p for p in [loc, reg, cnt] if p]
                                        if parts:
                                            info["address"] = ", ".join(parts)
                                        if reg and not info["state"]:
                                            info["state"] = reg
                                    elif isinstance(addr_obj, str) and not info["address"]:
                                        info["address"] = addr_obj

                                    # Contact email
                                    c_point = item.get("contactPoint")
                                    if isinstance(c_point, dict) and not info["email"]:
                                        em = c_point.get("email", "")
                                        if em:
                                            info["email"] = em.strip().lower()
                                    elif item.get("email") and not info["email"]:
                                        info["email"] = item["email"].strip().lower()

                                    # Contact phone from JSON-LD
                                    if not info["phone"]:
                                        tel = item.get("telephone")
                                        if tel:
                                            cp = clean_phone_number(str(tel))
                                            if cp:
                                                info["phone"] = cp
                                        elif isinstance(c_point, dict) and c_point.get("telephone"):
                                            cp = clean_phone_number(str(c_point["telephone"]))
                                            if cp:
                                                info["phone"] = cp

                                    # Social Links (sameAs)
                                    same_as = item.get("sameAs", [])
                                    if isinstance(same_as, str):
                                        same_as = [same_as]
                                    for slink in same_as:
                                        if "linkedin.com/company/" in slink and not info["linkedin"]:
                                            info["linkedin"] = slink.rstrip("/")
                                        if "instagram.com/" in slink and not info["instagram"]:
                                            info["instagram"] = slink.rstrip("/")
                        except Exception:
                            pass

                    # 0B. Text address extraction from /contact or /about
                    if not info["address"] and any(k in target_url.lower() for k in ["/contact", "/about"]):
                        m_loc = re.search(r"(?:Based in|Located in|Office:?)\s+([A-Za-z\s,]+(?:India|Bengaluru|Bangalore|Delhi|Mumbai|Hyderabad|Pune|Chennai|Kolkata))", text, re.I)
                        if m_loc:
                            info["address"] = m_loc.group(1).strip()

                    # 1. Contact Form URL
                    if not info["contact_form"]:
                        if any(k in target_url.lower() for k in ["/contact", "/reach", "/get-in-touch"]):
                            info["contact_form"] = target_url
                        else:
                            for a in soup.find_all("a", href=True):
                                h = a["href"].lower()
                                if "contact" in h:
                                    info["contact_form"] = urllib.parse.urljoin(target_url, a["href"])
                                    break

                    # 2. Domain-Matched Business Email
                    if not info["email"]:
                        # First check mailto links
                        for a in soup.find_all("a", href=True):
                            if a["href"].lower().startswith("mailto:"):
                                m_addr = a["href"][7:].split("?")[0].strip().lower()
                                m_dom = m_addr.split("@")[-1]
                                if m_dom == registered_domain and m_dom not in FREE_EMAIL_DOMAINS:
                                    info["email"] = m_addr
                                    break

                        # Regex check
                        if not info["email"]:
                            emails = EMAIL_REGEX.findall(html)
                            for em in emails:
                                em_low = em.lower().strip()
                                em_domain = em_low.split("@")[-1]
                                if em_domain == registered_domain and not any(em_low.startswith(p) for p in ["privacy@", "abuse@", "legal@"]):
                                    info["email"] = em_low
                                    break
                    # 2B. Official Contact / Phone Number
                    if not info["phone"]:
                        # Check tel: links
                        for a in soup.find_all("a", href=True):
                            h = a["href"].strip().lower()
                            if h.startswith("tel:"):
                                raw_p = a["href"].split(":", 1)[-1].split("?")[0].strip()
                                cp = clean_phone_number(raw_p)
                                if cp:
                                    info["phone"] = cp
                                    break

                        # Regex check across page text
                        if not info["phone"]:
                            phone_matches = re.findall(
                                r"(?:tel|phone|call|contact|mobile|helpline|whatsapp)?[:\s\-]*"
                                r"((?:\+91[\s\-]?)?(?:[6-9]\d{4}[\s\-]?\d{5}|[6-9]\d{9})|1800[\s\-]?[0-9]{3}[\s\-]?[0-9]{3,4}|1860[\s\-]?[0-9]{3}[\s\-]?[0-9]{3,4}|0\d{2,4}[\s\-]?[0-9]{6,8})\b",
                                text,
                                re.I
                            )
                            for pm in phone_matches:
                                cp = clean_phone_number(pm)
                                if cp:
                                    info["phone"] = cp
                                    break

                    # 3. Employee Strength / Headcount
                    if not info["employee_strength"]:
                        hc_match = HEADCOUNT_REGEX.search(text)
                        if hc_match:
                            info["employee_strength"] = hc_match.group(1)

                    # 4. Leadership & Executive Headings
                    if len(info["key_people"]) < 4:
                        for heading in soup.find_all(["h2", "h3", "h4", "strong"]):
                            htext = heading.get_text(strip=True)
                            if 4 < len(htext) < 40 and any(htext.startswith(prefix) for prefix in ["Mr.", "Ms.", "Mrs.", "Dr."]):
                                if htext not in info["key_people"]:
                                    info["key_people"].append(htext)

                        leader_patterns = [
                            r"(?:CEO|Chief Executive Officer|Managing Director|Founder|Co-Founder|Chairman)[\s:]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})",
                            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})[\s,]+(?:CEO|Managing Director|Founder|Chairman)",
                        ]
                        for pat in leader_patterns:
                            matches = re.findall(pat, text)
                            for m in matches:
                                if len(m) > 4 and m not in info["key_people"]:
                                    info["key_people"].append(m)

                    # 5. Social Links (LinkedIn & Instagram)
                    for a in soup.find_all("a", href=True):
                        h = a["href"].strip()
                        if not info["linkedin"] and "linkedin.com" in h.lower():
                            m_li = re.search(r"(?:https?:)?//(?:[a-z]{2,3}\.)?linkedin\.com/(?:company|school)/([A-Za-z0-9\-_%]+)/?", h, re.I)
                            if m_li:
                                info["linkedin"] = f"https://www.linkedin.com/company/{m_li.group(1)}"
                        if not info["instagram"] and "instagram.com" in h.lower():
                            if not any(x in h.lower() for x in ["/p/", "/reel/", "/stories/", "/explore/", "/tags/"]):
                                m_ig = re.search(r"(?:https?:)?//(?:www\.)?instagram\.com/([A-Za-z0-9_.]+)/?", h, re.I)
                                if m_ig:
                                    handle = m_ig.group(1).rstrip("/")
                                    if handle not in ["p", "reel", "stories", "explore", "about"]:
                                        info["instagram"] = f"https://www.instagram.com/{handle}"

            except Exception:
                continue

        return info

    # ── 4. Social Media Search Fallback (LinkedIn & Instagram) ────────────────
    async def search_social_profiles(
        self,
        company_name: str,
        website_url: str = ""
    ) -> Tuple[str, str]:
        """Search DDGS for official Company LinkedIn and Instagram with domain verification."""
        linkedin = ""
        instagram = ""
        if DDGS is None:
            return linkedin, instagram

        norm_tokens = get_distinctive_brand_tokens(company_name)
        core_brand = " ".join(norm_tokens).title() if norm_tokens else normalize_company_name(company_name).title()
        website_stem = ""
        if website_url:
            reg_dom = extract_registered_domain(website_url)
            if reg_dom:
                website_stem = reg_dom.split(".")[0].lower()

        def _fetch_social():
            def _query_ddgs(q: str):
                p = PROXY_MANAGER.get_proxy()
                if p:
                    try:
                        with DDGS(proxy=p, timeout=2.5) as ddgs:
                            return list(ddgs.text(q, max_results=3, backend="lite"))
                    except Exception:
                        pass
                try:
                    with DDGS(timeout=2.0) as ddgs:
                        return list(ddgs.text(q, max_results=3, backend="lite"))
                except Exception:
                    pass
                return []

            ql = f'site:linkedin.com/company "{website_stem}"' if website_stem else f'"{core_brand}" site:linkedin.com/company'
            qi = f'site:instagram.com "{website_stem}"' if website_stem else f'"{core_brand}" site:instagram.com'
            return _query_ddgs(ql), _query_ddgs(qi)

        loop = asyncio.get_running_loop()
        try:
            res_li, res_ig = await loop.run_in_executor(None, _fetch_social)
            full_brand_slug = "".join(norm_tokens)
            co_lower = company_name.lower()
            intl_words = [
                "international", "global", "worldwide", "usa", "us", "uk",
                "europe", "australia", "canada", "espana", "spain", "defense",
                "defence", "oficial", "official_es"
            ]

            for item in res_li:
                h = item.get("href", "")
                if "linkedin.com/company/" in h:
                    m_li = re.search(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/([A-Za-z0-9\-_%]+)/?", h)
                    if m_li:
                        slug = m_li.group(1).lower()
                        # Reject international buzzwords in slug if not in company name
                        if any(w in slug for w in intl_words if w not in co_lower):
                            continue
                        slug_clean = slug.replace("-", "").replace("_", "")
                        # Direct match with verified website domain stem
                        if website_stem and (website_stem == slug_clean or website_stem in slug_clean):
                            linkedin = f"https://www.linkedin.com/company/{m_li.group(1)}"
                            break
                        # Strict whole-name match
                        if len(norm_tokens) > 1:
                            if full_brand_slug in slug_clean or all(t in slug_clean for t in norm_tokens):
                                linkedin = f"https://www.linkedin.com/company/{m_li.group(1)}"
                                break
                        elif norm_tokens and norm_tokens[0] in slug_clean:
                            linkedin = f"https://www.linkedin.com/company/{m_li.group(1)}"
                            break

            for item in res_ig:
                h = item.get("href", "")
                if "instagram.com/" in h and not any(x in h.lower() for x in ["/p/", "/reel/", "/stories/", "/explore/", "/tags/"]):
                    m_ig = re.search(r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9_.]+)/?", h)
                    if m_ig:
                        handle = m_ig.group(1).lower().rstrip("/")
                        # Reject international buzzwords in handle if not in company name
                        if any(w in handle for w in intl_words if w not in co_lower):
                            continue
                        handle_clean = handle.replace("_", "").replace(".", "")
                        # Direct match with verified website domain stem
                        if website_stem and (website_stem == handle_clean or website_stem in handle_clean):
                            instagram = f"https://www.instagram.com/{m_ig.group(1)}"
                            break
                        # Strict whole-name match
                        if len(norm_tokens) > 1:
                            if full_brand_slug in handle_clean or all(t in handle_clean for t in norm_tokens):
                                instagram = f"https://www.instagram.com/{m_ig.group(1)}"
                                break
                        elif norm_tokens and norm_tokens[0] in handle_clean:
                            instagram = f"https://www.instagram.com/{m_ig.group(1)}"
                            break
        except Exception:
            pass

        return linkedin, instagram

    # ── 4. Leadership & Key Executives Live Extractor ─────────────────────────
    async def search_leadership_executives(
        self,
        company_name: str,
        session: aiohttp.ClientSession
    ) -> List[str]:
        """Search for leadership page, crawl it, and extract real director & executive names."""
        leaders: List[str] = []
        if DDGS is None:
            return leaders

        target_urls: List[str] = []

        def _run_search():
            clean = normalize_company_name(company_name)
            p = PROXY_MANAGER.get_proxy()
            try:
                with DDGS(proxy=p) as ddgs:
                    return list(ddgs.text(f"{clean} leadership team board of directors", max_results=4, backend="html"))
            except Exception:
                try:
                    with DDGS(proxy=p) as ddgs:
                        return list(ddgs.text(f"{clean} leadership team board of directors", max_results=4, backend="lite"))
                except Exception:
                    return []

        loop = asyncio.get_running_loop()
        try:
            results = await loop.run_in_executor(None, _run_search)
            for item in results:
                href = item.get("href", "")
                body = (item.get("title", "") + " " + item.get("body", "")).strip()

                # Extract executive names mentioned in snippet
                names_in_snip = re.findall(r"\b(?:Mr\.|Ms\.|Mrs\.|Dr\.)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b", body)
                for n in names_in_snip:
                    if n not in leaders:
                        leaders.append(n)

                if any(k in href.lower() for k in ["leadership", "director", "board", "management", "team", "about"]):
                    target_urls.append(href)
        except Exception:
            pass

        # Crawl top 2 leadership pages for heading names
        for u in target_urls[:2]:
            try:
                async with session.get(u, headers={"User-Agent": USER_AGENT}, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        soup = BeautifulSoup(await r.text(), "html.parser")
                        for h in soup.find_all(["h2", "h3", "h4", "strong"]):
                            t = h.get_text(strip=True)
                            if any(t.startswith(p) for p in ["Mr. ", "Ms. ", "Mrs. ", "Dr. "]) and 4 < len(t) < 40:
                                if t not in leaders:
                                    leaders.append(t)
            except Exception:
                pass

        return leaders[:5]

    # ── 5. Statutory MCA Registry Lookup (For Non-CSV Companies) ─────────────
    async def scrape_mca_registry_statutory(
        self,
        company_name: str,
        session: aiohttp.ClientSession
    ) -> Dict[str, Any]:
        """Extract CIN, Capital, Class, and Directors for non-CSV companies."""
        data = {
            "cin": "",
            "reg_date": "",
            "company_class": "",
            "industry": "",
            "state": "",
            "address": "",
            "auth_capital": "",
            "paid_capital": "",
            "directors": [],
        }

        norm_target = normalize_company_name(company_name).lower()
        target_tokens = [t for t in norm_target.split() if len(t) >= 4 and t not in GENERIC_WORDS]
        if not target_tokens:
            target_tokens = [t for t in norm_target.split() if len(t) >= 3 and t not in GENERIC_WORDS]

        # Step A: DDGS fast CIN extraction
        if DDGS:
            def _find_cin():
                p = PROXY_MANAGER.get_proxy()
                try:
                    with DDGS(proxy=p) as ddgs:
                        return list(ddgs.text(f'"{company_name}" CIN number', max_results=3))
                except Exception:
                    return []

            loop = asyncio.get_running_loop()
            try:
                items = await loop.run_in_executor(None, _find_cin)
                for item in items:
                    blob = (item.get("title", "") + " " + item.get("body", "")).lower()
                    # Company brand token MUST be present in snippet
                    if target_tokens and not any(t in blob for t in target_tokens):
                        continue
                    cin_m = CIN_REGEX.search(blob)
                    if cin_m:
                        data["cin"] = cin_m.group(1).upper()
                        break
            except Exception:
                pass

        if data["cin"]:
            return data

        # Step B: Bing HTML Fallback
        query = f'"{company_name}" CIN Zaubacorp'
        bing_url = f"https://www.bing.com/search?q={urllib.parse.quote_plus(query)}"
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            async with session.get(bing_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    if target_tokens and any(t in html.lower() for t in target_tokens):
                        cin_found = CIN_REGEX.search(html)
                        if cin_found:
                            data["cin"] = cin_found.group(1).upper()
        except Exception:
            pass

        return data

    # ── 5B. MCA Statutory Filing Enrichment via Zaubacorp (Email & Directors) ─
    async def scrape_zaubacorp_statutory(self, cin: str, company_name: str) -> Dict[str, Any]:
        """Fetch official registered MCA email, directors, and statutory website using CIN."""
        res = {"email": "", "directors": [], "website": ""}
        if not cin:
            return res

        def _fetch_sync():
            slug = re.sub(r"[^A-Za-z0-9]+", "-", company_name).strip("-")
            url = f"https://www.zaubacorp.com/company/{slug}/{cin}"
            headers = {
                "User-Agent": USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
            }
            proxy_url = PROXY_MANAGER.get_proxy()
            opener = None
            if proxy_url:
                try:
                    proxy_support = urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url})
                    opener = urllib.request.build_opener(proxy_support)
                except Exception:
                    opener = None

            # Step 1: ZaubaCorp attempt
            try:
                req = urllib.request.Request(url, headers=headers)
                r_ctx = opener.open(req, timeout=2.0) if opener else urllib.request.urlopen(req, timeout=2.0)
                with r_ctx as r:
                    html = r.read().decode("utf-8", errors="ignore")
                    soup = BeautifulSoup(html, "html.parser")

                    # Verify that this ZaubaCorp page actually belongs to the searched company!
                    h1 = soup.find("h1")
                    h1_text = h1.get_text(strip=True) if h1 else (soup.title.string if soup.title else "")
                    h1_clean = normalize_company_name(h1_text).lower()

                    norm_target = normalize_company_name(company_name).lower()
                    target_tokens = [t for t in norm_target.split() if len(t) >= 4 and t not in GENERIC_WORDS]
                    if not target_tokens:
                        target_tokens = [t for t in norm_target.split() if len(t) >= 3 and t not in GENERIC_WORDS]

                    if not target_tokens or any(t in h1_clean for t in target_tokens):
                        # 1. Registered Email
                        emails = [
                            em.lower().strip(".")
                            for em in re.findall(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}", html)
                            if not any(x in em.lower() for x in ["zaubacorp", "your@email", "sentry", "domain.com"])
                        ]
                        if emails:
                            res["email"] = emails[0]

                        # 2. Directors / DIN Table
                        for tr in soup.find_all("tr"):
                            tds = [td.get_text(strip=True) for td in tr.find_all("td")]
                            if len(tds) >= 4 and re.match(r"^\d{8}$", tds[0]):
                                d_name = tds[1].title()
                                desig = tds[2]
                                res["directors"].append(f"{d_name} ({desig})")

                        # 3. Official Website if listed in MCA table
                        for tr in soup.find_all("tr"):
                            text = tr.get_text(" ", strip=True)
                            if "website" in text.lower():
                                m = re.search(r"https?://[^\s<>]+", text)
                                if m:
                                    res["website"] = m.group(0)
            except Exception:
                pass

            # Step 2: Independent Fallback to QuickCompany if missing directors or email
            if not res["directors"] or not res["email"]:
                try:
                    qc_slug = re.sub(r"[^a-zA-Z0-9]+", "-", company_name.lower()).strip("-")
                    qc_url = f"https://www.quickcompany.in/company/{qc_slug}"
                    qc_req = urllib.request.Request(qc_url, headers=headers)
                    qc_ctx = opener.open(qc_req, timeout=2.0) if opener else urllib.request.urlopen(qc_req, timeout=2.0)
                    with qc_ctx as qc_r:
                        qc_html = qc_r.read().decode("utf-8", errors="ignore")
                        qc_soup = BeautifulSoup(qc_html, "html.parser")
                        for a in qc_soup.find_all("a", href=True):
                            h = a["href"]
                            if "/directors/" in h:
                                dname = a.get_text(strip=True).rstrip(".").strip()
                                if dname and dname not in res["directors"] and "directors" not in dname.lower() and len(dname) > 3:
                                    res["directors"].append(dname)
                            elif "/trademarks/" in h:
                                tm = a.get_text(strip=True).strip()
                                if tm and tm not in res.get("trademarks", []) and "trademarks" not in tm.lower() and len(tm) > 2:
                                    if "trademarks" not in res:
                                        res["trademarks"] = []
                                    res["trademarks"].append(tm)
                        if not res["email"]:
                            qc_emails = [
                                em.lower().strip(".")
                                for em in re.findall(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}", qc_html)
                                if not any(x in em.lower() for x in ["quickcompany", "your@email", "sentry", "domain.com"])
                            ]
                            if qc_emails:
                                res["email"] = qc_emails[0]
                except Exception:
                    pass

            return res

        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, _fetch_sync)
        except Exception:
            return res

    # ── 6. Google Maps Headless Playwright (Location & Website Fallback) ──────
    async def scrape_google_maps(self, company_name: str) -> Dict[str, str]:
        """Headless Google Maps query for address and official website."""
        data = {"address": "", "website": ""}
        if not self.context:
            return data

        page = await self.context.new_page()
        try:
            q = f"{company_name} headquarters"
            url = f"https://www.google.com/maps/search/{urllib.parse.quote_plus(q)}"
            await page.goto(url, timeout=18000)
            await page.wait_for_timeout(2500)

            website_el = page.locator("a[aria-label*='website'], a[data-item-id='authority']").first
            if await website_el.count() > 0:
                href = await website_el.get_attribute("href")
                if href and href.startswith("http") and "google.com" not in href:
                    data["website"] = href

            addr_el = page.locator("button[aria-label*='Address:'], button[data-item-id='address']").first
            if await addr_el.count() > 0:
                label = await addr_el.get_attribute("aria-label") or ""
                clean_addr = label.replace("Address:", "").strip()
                # Reject Plus-codes (e.g. 'VG94+RWC, ...') that are GPS artifacts rather than addresses
                if not re.match(r"^[A-Z0-9]{4}\+[A-Z0-9]{2,}", clean_addr):
                    data["address"] = clean_addr

        except Exception:
            pass
        finally:
            await page.close()

        return data


# ── Master Intelligence Agent (Orchestrator) ──────────────────────────────────

class MasterCompanyAgent:
    """End-to-End Company Intelligence Agent with 2-Tier Architecture."""

    def __init__(self):
        self.cache = LocalIntelligenceCache()
        self.scraper = LiveCompanyScraper()

    async def search_company(
        self,
        company_name: str,
        use_cache: bool = True,
        interactive: bool = False,
        state: Optional[str] = None,
        cin: Optional[str] = None,
        **kwargs
    ) -> Dict[str, str]:
        print(f"\n" + "=" * 70)
        print(f"  🔍 SEARCHING INTELLIGENCE FOR: '{company_name.upper()}'")
        print("=" * 70)

        # ── TIER 1: Check Local Cache & CSVs ──────────────────────────────────
        record = {col: "" for col in OUTPUT_COLUMNS}
        record["Company Name"] = company_name.upper()

        # Accept pre-populated statutory record (e.g. from batch pipeline) to avoid disk scans
        if kwargs.get("initial_record"):
            for k, v in kwargs["initial_record"].items():
                if v and not record.get(k):
                    record[k] = v

        if use_cache:
            cached_record = self.cache.lookup(company_name)
            if (
                cached_record
                and cached_record.get("CIN")
                and (
                    cached_record.get("Company Website")
                    or cached_record.get("Key People (Director / CEO / Stakeholder)")
                    or cached_record.get("Employee Strength")
                )
            ):
                print("  ⚡ [TIER 1] Instant Cache Hit! Full verified profile found (0 ms).")
                return cached_record
            elif cached_record:
                for k, v in cached_record.items():
                    if v and not record.get(k):
                        record[k] = v
                print(f"  📂 [TIER 1] Found in Cache, checking local database for missing fields...")

        # If statutory data (CIN, Address, Capital) is missing AND not already provided in initial_record, search local master CSVs
        if not kwargs.get("initial_record") and (not record.get("CIN") or not record.get("Authorized Capital") or not record.get("Company Address")):
            csv_record = self.cache.search_local_csvs(company_name)
            if csv_record:
                print(f"  📂 [TIER 1] Found in Local MCA Database! Populating statutory details...")
                for k, v in csv_record.items():
                    if v and not record.get(k):
                        record[k] = v
                if csv_record.get("Company Name"):
                    record["Company Name"] = csv_record["Company Name"]

        # Check what fields are still missing
        missing_fields = [k for k in OUTPUT_COLUMNS if not record.get(k)]
        if not missing_fields:
            if kwargs.get("save_to_cache", True):
                self.cache.save_or_update(record)
            return record

        print(f"  🌐 [TIER 2] Enriching corporate intelligence via single authoritative source...")

        # ── TIER 2: Single-Source Authoritative Live Enrichment ────────────────
        connector = aiohttp.TCPConnector(limit=0, ssl=False, ttl_dns_cache=300)
        async with aiohttp.ClientSession(connector=connector) as session:
            zauba_data: Dict[str, Any] = {}

            # Source A: Official MCA Filing Records (Email & Directors for Verified MCA Entities only)
            if record.get("CIN") and (not record.get("Company Email") or not record.get("Key People (Director / CEO / Stakeholder)")):
                print("  🏛️  [Statutory] Fetching Official MCA Filing Records (Email & Directors)...")
                zauba_data = await self.scraper.scrape_zaubacorp_statutory(record["CIN"], record.get("Company Name", company_name))
                if zauba_data.get("email") and not record.get("Company Email"):
                    record["Company Email"] = zauba_data["email"]
                if zauba_data.get("directors") and not record.get("Key People (Director / CEO / Stakeholder)"):
                    record["Key People (Director / CEO / Stakeholder)"] = ", ".join(zauba_data["directors"][:5])

            # Source B: Discover Official Corporate Website (Single Source for Web & Digital Contact Intel)
            if not record.get("Company Website"):
                print("  🔎 [Step 1/3] Discovering Official Corporate Website...")
                found_url = await self.scraper.discover_website_via_search(
                    company_name,
                    company_state=record.get("Company State", ""),
                    session=session
                )
                if found_url:
                    record["Company Website"] = found_url
                elif zauba_data.get("trademarks"):
                    for tm in zauba_data["trademarks"]:
                        tm_url = await self.scraper.discover_website_via_search(
                            tm,
                            company_state=record.get("Company State", ""),
                            session=session
                        )
                        if tm_url:
                            record["Company Website"] = tm_url
                            break
                        direct_tm = f"https://www.{re.sub(r'[^a-zA-Z0-9]+', '', tm).lower()}.com"
                        try:
                            async with session.get(direct_tm, headers=BROWSER_HEADERS, timeout=aiohttp.ClientTimeout(total=4), ssl=False) as r_tm:
                                if r_tm.status == 200:
                                    record["Company Website"] = direct_tm
                                    break
                        except Exception:
                            pass

            # Source C: Deep Crawl Official Website (Email, Contact Form, Office Location, Headcount, Social Links)
            if record.get("Company Website"):
                print(f"  🌐 [Step 2/3] Crawling Official Website ({record['Company Website']})...")
                site_data = await self.scraper.scrape_official_website(record["Company Website"], session)

                # Prioritize verified domain email directly from company website (e.g. contact@aivatika.com)
                if site_data.get("email"):
                    site_em = site_data["email"]
                    site_em_dom = site_em.split("@")[-1]
                    site_reg_dom = extract_registered_domain(record.get("Company Website", ""))
                    rec_em = record.get("Company Email", "")
                    if site_em_dom == site_reg_dom and site_em_dom not in FREE_EMAIL_DOMAINS:
                        record["Company Email"] = site_em
                    elif not rec_em:
                        record["Company Email"] = site_em

                # Official verified address from website schema / contact page
                if site_data.get("address") and not record.get("Company Address"):
                    record["Company Address"] = site_data["address"]
                if site_data.get("state") and not record.get("Company State"):
                    record["Company State"] = site_data["state"]

                if site_data.get("phone") and not record.get("Company Contact Number"):
                    record["Company Contact Number"] = site_data["phone"]
                if site_data.get("contact_form") and not record.get("Company Contact Form"):
                    record["Company Contact Form"] = site_data["contact_form"]
                if site_data.get("employee_strength") and not record.get("Employee Strength"):
                    record["Employee Strength"] = site_data["employee_strength"]
                if site_data.get("linkedin") and not record.get("Company LinkedIn"):
                    record["Company LinkedIn"] = site_data["linkedin"]
                if site_data.get("instagram") and not record.get("Company Instagram"):
                    record["Company Instagram"] = site_data["instagram"]

            # Source D: Social Media Profiles (if not already extracted directly from official website)
            if (not record.get("Company LinkedIn") or not record.get("Company Instagram")) and record.get("Company Website"):
                print("  📱 [Step 3/3] Discovering Official LinkedIn & Instagram Profiles...")
                li, ig = await self.scraper.search_social_profiles(company_name, record.get("Company Website", ""))
                if li and not record.get("Company LinkedIn"):
                    record["Company LinkedIn"] = li
                if ig and not record.get("Company Instagram"):
                    record["Company Instagram"] = ig

        # For any field not found in authoritative sources, mark as NOT_FOUND (never guess or fabricate)
        for k in OUTPUT_COLUMNS:
            if not record.get(k):
                record[k] = "NOT_FOUND"

        # Save to Cache (optional in batch runs to avoid file rewrite overhead)
        if kwargs.get("save_to_cache", True):
            self.cache.save_or_update(record)
            print("  💾 [CACHE] Profile updated & saved to 'company_master_intelligence.csv'.")
        return record


# ── Display Formatter ─────────────────────────────────────────────────────────

def display_profile(record: Dict[str, str]):
    """Print an attractive corporate profile card in the terminal."""
    print("\n" + "=" * 70)
    print(f"  🏢 COMPANY PROFILE: {record.get('Company Name', 'N/A')}")
    print("=" * 70)
    print(f"  • CIN                       : {record.get('CIN') or 'NOT_FOUND'}")
    print(f"  • Registration Date         : {record.get('Company Registration Date') or 'NOT_FOUND'}")
    print(f"  • Company Class             : {record.get('Company Class') or 'NOT_FOUND'}")
    print(f"  • Industry                  : {record.get('Company Industrial Classification') or 'NOT_FOUND'}")
    print(f"  • State                     : {record.get('Company State') or 'NOT_FOUND'}")
    print(f"  • Address                   : {record.get('Company Address') or 'NOT_FOUND'}")
    print(f"  • Authorized Capital        : {record.get('Authorized Capital') or 'NOT_FOUND'}")
    print(f"  • Paid-up Capital           : {record.get('Paidup Capital') or 'NOT_FOUND'}")
    print("-" * 70)
    print(f"  • Official Website          : {record.get('Company Website') or 'NOT_FOUND'}")
    print(f"  • Business Email            : {record.get('Company Email') or 'NOT_FOUND'}")
    print(f"  • Contact Number            : {record.get('Company Contact Number') or 'NOT_FOUND'}")
    print(f"  • Contact Form URL          : {record.get('Company Contact Form') or 'NOT_FOUND'}")
    print(f"  • Employee Strength         : {record.get('Employee Strength') or 'NOT_FOUND'}")
    print(f"  • Key People / Directors    : {record.get('Key People (Director / CEO / Stakeholder)') or 'NOT_FOUND'}")
    print("-" * 70)
    print(f"  • LinkedIn Company Page     : {record.get('Company LinkedIn') or 'NOT_FOUND'}")
    print(f"  • Instagram Official Handle : {record.get('Company Instagram') or 'NOT_FOUND'}")
    print("=" * 70 + "\n")


# ── Interactive CLI ───────────────────────────────────────────────────────────

async def async_main():
    parser = argparse.ArgumentParser(
        description="Master Company Intelligence Agent — On-Demand 16-Field Corporate Scraper."
    )
    parser.add_argument(
        "-c", "--company",
        type=str,
        default=None,
        help="Company name to search directly"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass local cache and force fresh web scrape"
    )

    args = parser.parse_args()
    agent = MasterCompanyAgent()

    # ── Mode 1: Single-Company CLI Execution ─────────────────────────────────
    # Triggered when running: python master_main.py --company "Tata Motors"
    # Searches the provided company argument once, prints results, and exits.
    if args.company:
        result = await agent.search_company(args.company, use_cache=not args.no_cache)
        display_profile(result)
        return

    # ── Mode 2: Interactive Terminal REPL Loop ────────────────────────────────
    # Triggered when running without arguments: python master_main.py
    # Prompts for company names repeatedly until the user types 'exit' or 'quit'.
    print("=" * 70)
    print("  🚀 MASTER COMPANY INTELLIGENCE AGENT (Ready)")
    print("  Type any company name (e.g. 'Tata Motors', 'Infosys', 'Decarbonic Global')")
    print("  Type 'exit' or 'quit' to stop.")
    print("=" * 70)

    while True:
        try:
            query = input("\n👉 Enter Company Name: ").strip()
            if not query:
                continue
            if query.lower() in ("exit", "quit", "q"):
                print("Goodbye!")
                break

            # Searches the user-entered prompt query in the continuous loop
            result = await agent.search_company(query, use_cache=not args.no_cache)
            display_profile(result)

        except (KeyboardInterrupt, EOFError):
            print("\nExiting. All data preserved.")
            break


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()

"""
Configuration and constants for the MCA Company Enrichment Scraper v2.
Strict validation rules per user specification.
"""

from typing import Set, List

# ── File / batch settings ─────────────────────────────────────────────────────
DEFAULT_INPUT_CSV   = "MCA_2025_Companies_Important.csv"
DEFAULT_OUTPUT_CSV  = "enriched_companies.csv"
CHECKPOINT_INTERVAL = 25
DEFAULT_CONCURRENCY = 5
REQUEST_TIMEOUT_SECONDS = 15
PLAYWRIGHT_TIMEOUT_MS   = 20_000

# ── Output columns (strict order) ─────────────────────────────────────────────
OUTPUT_COLUMNS: List[str] = [
    "Company",
    "Website",
    "Email",
    "Contact Form",
    "Instagram",
    "LinkedIn",
]

# ── Sentinel value ─────────────────────────────────────────────────────────────
NOT_FOUND = "NOT_FOUND"

# ── Browser User-Agents ────────────────────────────────────────────────────────
USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# ── Blacklisted domains: NEVER accepted as official website ────────────────────
BLACKLISTED_DOMAINS: Set[str] = {
    # Explicitly listed in user rules
    "falconebiz.com",
    "tofler.in",
    "thecompanycheck.com",
    "mca.gov.in",
    "indiafilings.com",
    "startuptalky.com",
    "crunchbase.com",
    "tracxn.com",
    "justdial.com",
    "indiamart.com",
    "tradeindia.com",
    "exportersindia.com",
    "allindiaitr.com",
    "buysellprivatelimited.com",
    "infomint.co.in",
    "alchetron.com",
    "wikipedia.org",
    "zoominfo.com",
    "rocketreach.co",
    "apollo.io",
    "carwale.com",
    "bikewale.com",
    "cardekho.com",
    "bikedekho.com",
    "zigwheels.com",
    "gaadi.com",
    "autoportal.com",
    "housing.com",
    "nobroker.in",
    "magicbricks.com",
    "99acres.com",
    "shiksha.com",
    "collegedunia.com",
    "planetexim.net",
    "bizidex.com",
    "sansadhan.com",
    "anekantprakashan.com",
    "webmd.com",
    "britannica.com",
    "dictionary.com",
    "oxfordlearnersdictionaries.com",
    "cambridge.org",
    "merriam-webster.com",
    "investopedia.com",
    # Social/directory LinkedIn pages handled separately (company pages allowed)
    "startupindia.gov.in",
    "mca21.gov.in",

    # Additional directories & registries
    "zaubacorp.com",
    "quickcompany.in",
    "vakilsearch.com",
    "connect2india.com",
    "instafinancials.com",
    "corpintel.io",
    "mastersindia.co",
    "credhive.in",
    "edgeinsights.in",
    "gowox.com",
    "qorpiq.com",
    "neusourcestartup.com",
    "fundoodata.com",
    "companydetails.in",
    "instacompany.in",
    "corporatedir.com",
    "cybex.in",
    "volza.com",
    "company360.in",
    "legalkart.com",
    "f6s.com",
    "dnb.com",
    "kompass.com",
    "opencorporates.com",
    "globalindia.org",
    "mergedbiz.com",
    "wysa.io",

    # Job portals / HR
    "glassdoor.com",
    "glassdoor.co.in",
    "ambitionbox.com",
    "indeed.com",
    "naukri.com",
    "internshala.com",
    "shine.com",

    # Financial / stock
    "moneycontrol.com",
    "bseindia.com",
    "nseindia.com",
    "screener.in",
    "groww.in",
    "zerodha.com",
    "angelone.in",
    "finology.in",

    # News / media
    "economictimes.indiatimes.com",
    "timesofindia.indiatimes.com",
    "businessstandard.com",
    "livemint.com",
    "ndtv.com",
    "thehindubusinessline.com",

    # Search engines
    "google.com", "google.co.in", "bing.com", "duckduckgo.com",
    "yahoo.com", "msn.com", "yandex.com",

    # Marketplaces
    "amazon.in", "amazon.com", "flipkart.com",
    "sulekha.com", "yellowpages.in", "quikr.com", "olx.in",
    "dial4trade.com",

    # Social platforms (official company pages handled via extractor)
    "facebook.com", "youtube.com", "twitter.com", "x.com",
    "pinterest.com", "reddit.com", "quora.com",
    "medium.com", "github.com", "gitlab.com",
    "tiktok.com", "vimeo.com", "threads.net",
}

# ── Parked / suspended page indicators ────────────────────────────────────────
PARKED_INDICATORS: List[str] = [
    "buy this domain",
    "this domain is for sale",
    "domain is parked",
    "parked free",
    "sedoparking",
    "hugedomains",
    "domain has expired",
    "renew now",
    "account suspended",
    "cgi-sys/suspendedpage",
    "website under construction",
    "this website is coming soon",
    "coming soon",
    "temporarily unavailable",
    "namecheap parking",
    "afternic.com",
    "domain name marketplace",
    "inquire about this domain",
    "apache2 default page",
    "welcome to nginx!",
    "iis windows server",
    "domain registered at",
    "godaddy.com/domainsearch",
]

# ── Free-email providers: NEVER accepted as business email ─────────────────────
FREE_EMAIL_DOMAINS: Set[str] = {
    "gmail.com", "googlemail.com",
    "yahoo.com", "yahoo.co.in", "yahoo.co.uk",
    "outlook.com", "outlook.in", "hotmail.com", "hotmail.co.in",
    "rediffmail.com", "rediff.com",
    "protonmail.com", "proton.me",
    "icloud.com", "me.com", "mac.com",
    "aol.com",
    "zohomail.com", "zoho.com",
    "yandex.com", "yandex.ru",
    "msn.com",
    "live.com", "live.in",
}

# ── Email prefixes that MUST be rejected ──────────────────────────────────────
REJECTED_EMAIL_PREFIXES: Set[str] = {
    "support", "help", "sales", "marketing", "media", "press",
    "customer", "customerservice", "care", "customercare",
    "admin", "administrator", "jobs", "career", "careers",
    "hr", "recruitment", "noreply", "no-reply", "info",
    "billing", "invoicing", "feedback", "team", "general",
    "enquiry", "enquiries", "query", "queries",
    "webmaster", "postmaster", "abuse",
    "privacy", "legal", "compliance", "dpo", "gdpr",
    "security", "it", "technical", "tech",
}

# ── Preferred business email prefixes (priority order) ────────────────────────
PREFERRED_EMAIL_PREFIXES: List[str] = [
    "founder", "director", "ceo", "cto", "coo", "cfo",
    "partner", "md", "chairman",
    "business", "hello", "contact", "connect",
    "collaborate", "partnerships", "office",
    "work", "reach", "hi",
]

# ── Sub-paths to crawl on target website ──────────────────────────────────────
CRAWL_SUBPATHS: List[str] = [
    "",           # homepage
    "about",
    "about-us",
    "aboutus",
    "company",
    "contact",
    "contact-us",
    "contactus",
    "get-in-touch",
    "team",
    "leadership",
    "management",
]

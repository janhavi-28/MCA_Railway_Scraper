"""
Contact & social extractor v2 — strict rules as per specification.

Email rules:
  - Must belong to the verified company domain.
  - Rejects all free-mail providers.
  - Rejects all "support@", "sales@", "info@" style prefixes.
  - Returns NOT_FOUND rather than any doubtful email.

Contact Form:
  - Must be the company's own /contact or /contact-us page.

LinkedIn:
  - Must be the official COMPANY page (linkedin.com/company/<slug>).
  - Rejects personal profiles, directory pages.

Instagram:
  - Must be the official company account (instagram.com/<handle>).
  - Rejects personal, fan, or directory accounts.
"""

import re
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import tldextract

from .config import (
    NOT_FOUND,
    FREE_EMAIL_DOMAINS,
    REJECTED_EMAIL_PREFIXES,
    PREFERRED_EMAIL_PREFIXES,
)

# ── Email regex ────────────────────────────────────────────────────────────────
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]{1,64}"
    r"@"
    r"[a-zA-Z0-9.\-]{2,255}"
    r"\.[a-zA-Z]{2,10}",
    re.IGNORECASE,
)

# Obfuscation patterns: "user [at] domain [dot] com", "user(at)domain.com"
_EMAIL_OBFUS_RE = re.compile(
    r"([a-zA-Z0-9._%+\-]{1,64})"
    r"\s*[\(\[]\s*(?:at|@)\s*[\)\]]\s*"
    r"([a-zA-Z0-9.\-]{2,100})"
    r"\s*[\(\[]\s*(?:dot|\.)\s*[\)\]]\s*"
    r"([a-zA-Z]{2,10})",
    re.IGNORECASE,
)


def _extract_domain(url: str) -> str:
    try:
        ext = tldextract.extract(url)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}".lower()
    except Exception:
        pass
    return ""


def _is_free_email(email: str) -> bool:
    domain = email.split("@")[-1].lower()
    return domain in FREE_EMAIL_DOMAINS


def _is_rejected_prefix(email: str) -> bool:
    prefix = email.split("@")[0].lower().strip(".")
    if prefix in REJECTED_EMAIL_PREFIXES:
        return True
    parts = re.split(r"[._\-]", prefix)
    for part in parts:
        if part in REJECTED_EMAIL_PREFIXES:
            return True
    return False


def _email_score(email: str) -> int:
    """Higher = better. Used to rank preferred emails."""
    prefix = email.split("@")[0].lower()
    for i, pref in enumerate(PREFERRED_EMAIL_PREFIXES):
        if prefix == pref or prefix.startswith(pref):
            return len(PREFERRED_EMAIL_PREFIXES) - i
    return 0


def extract_emails_from_html(html: str) -> Set[str]:
    """Extract all email-like strings from raw HTML + decoded obfuscations."""
    emails: Set[str] = set()

    # mailto: links
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().startswith("mailto:"):
            raw = href[7:].split("?")[0].strip()
            if _EMAIL_RE.match(raw):
                emails.add(raw.lower())

    # Raw regex on entire HTML text
    for m in _EMAIL_RE.finditer(html):
        emails.add(m.group().lower())

    # Obfuscated patterns
    for m in _EMAIL_OBFUS_RE.finditer(html):
        addr = f"{m.group(1)}@{m.group(2)}.{m.group(3)}"
        emails.add(addr.lower())

    return emails


def pick_best_email(
    all_emails: Set[str],
    website_domain: str,
) -> str:
    """
    From all discovered emails, return the single best business email.
    Rules (strict):
      1. Must belong to website_domain.
      2. Must NOT be a free-mail provider.
      3. Must NOT have a rejected prefix.
      4. Prefer executive / direct prefixes.
    Returns NOT_FOUND if nothing qualifies.
    """
    if not all_emails or not website_domain:
        return NOT_FOUND

    site_domain = _extract_domain(website_domain) or website_domain.lower()
    # Remove scheme / path
    site_domain = site_domain.replace("http://", "").replace("https://", "").split("/")[0]

    qualified: List[str] = []
    for email in all_emails:
        email_domain = email.split("@")[-1].lower()

        # Must match company domain
        if site_domain and email_domain != site_domain and not email_domain.endswith("." + site_domain):
            continue
        # No free mail
        if _is_free_email(email):
            continue
        # No rejected prefixes
        if _is_rejected_prefix(email):
            continue
        qualified.append(email)

    if not qualified:
        return NOT_FOUND

    # Sort by preference score (descending), then alphabetically for determinism
    qualified.sort(key=lambda e: (-_email_score(e), e))
    return qualified[0]


def extract_contact_page(
    crawled_pages: Dict[str, str],
    base_url: str,
    page_urls: Optional[Dict[str, str]] = None,
) -> str:
    """
    Return the company's official contact page.
    1. If a verified contact subpage was found and crawled, return its actual URL.
    2. If the homepage itself has a contact form or anchor (#contact), return {base_url}#contact or {base_url}.
    3. Otherwise return NOT_FOUND.
    """
    clean_base = base_url.rstrip("/")

    # Check discovered contact subpage URL that returned HTTP 200
    if page_urls and "contact" in page_urls:
        return page_urls["contact"]

    for page_key in ("contact", "contact-us", "contactus", "get-in-touch"):
        if page_urls and page_key in page_urls:
            return page_urls[page_key]
        if page_key in crawled_pages and crawled_pages[page_key]:
            return f"{clean_base}/{page_key}"

    # Check homepage for contact form or #contact anchor (single-page sites)
    home_html = crawled_pages.get("/") or ""
    if home_html:
        soup = BeautifulSoup(home_html, "html.parser")
        # Check for #contact anchor
        for a in soup.find_all("a", href=True):
            href_low = a["href"].strip().lower()
            if href_low in ("#contact", "#contact-us", "#contactus", "#get-in-touch"):
                return f"{clean_base}#contact"

        # Check for form with email / message / contact inputs on homepage
        for form in soup.find_all("form"):
            form_text = form.get_text().lower()
            inputs = [inp.get("name", "").lower() for inp in form.find_all(["input", "textarea"])]
            if any("email" in i or "message" in i for i in inputs) or "contact" in form_text or "send message" in form_text:
                return clean_base

    return NOT_FOUND


def extract_linkedin(crawled_pages: Dict[str, str], company_name: str = "") -> str:
    """
    Extract ONLY an official company LinkedIn page
    (linkedin.com/company/<slug>).
    Rejects personal profiles (linkedin.com/in/...) and third-party/agency links.
    """
    combined_html = " ".join(crawled_pages.values())
    pattern = re.compile(
        r'https?://(?:www\.)?linkedin\.com/company/([A-Za-z0-9\-_%]+)',
        re.IGNORECASE,
    )
    core_tokens = []
    if company_name:
        core = re.sub(r"\b(PRIVATE LIMITED|PVT\.?\s*LTD\.?|LIMITED|LTD\.?|LLP|OPC)\b", "", company_name, flags=re.I).strip()
        core_tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", core) if len(t) > 2]

    for m in pattern.finditer(combined_html):
        slug = m.group(1).strip("/")
        if not slug:
            continue
        # Verify slug matches company brand if tokens available
        if core_tokens:
            slug_clean = re.sub(r"[^a-z0-9]", "", slug.lower())
            if not any(t in slug_clean for t in core_tokens):
                continue
        return f"https://www.linkedin.com/company/{slug}"
    return NOT_FOUND


def extract_instagram(crawled_pages: Dict[str, str], company_name: str = "") -> str:
    """
    Extract ONLY official company Instagram account
    (instagram.com/<handle>).
    Rejects explore / tag / reel / p/ paths and web designer/agency handles.
    """
    combined_html = " ".join(crawled_pages.values())
    pattern = re.compile(
        r'https?://(?:www\.)?instagram\.com/([A-Za-z0-9_.]+)/?',
        re.IGNORECASE,
    )
    _reject_handles = {
        "explore", "p", "reel", "reels", "stories", "tags",
        "accounts", "direct", "web",
    }
    core_tokens = []
    if company_name:
        core = re.sub(r"\b(PRIVATE LIMITED|PVT\.?\s*LTD\.?|LIMITED|LTD\.?|LLP|OPC)\b", "", company_name, flags=re.I).strip()
        core_tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", core) if len(t) > 2]

    for m in pattern.finditer(combined_html):
        handle = m.group(1).strip("/")
        if not handle or handle.lower() in _reject_handles:
            continue
        if core_tokens:
            handle_clean = re.sub(r"[^a-z0-9]", "", handle.lower())
            if not any(t in handle_clean for t in core_tokens):
                continue
        return f"https://www.instagram.com/{handle}"
    return NOT_FOUND

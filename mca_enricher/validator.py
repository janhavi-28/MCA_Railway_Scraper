"""
Website validator v2 — strict official-website verification.

Rules:
- Homepage must clearly display the company name or brand.
- Logo alt/src must match brand.
- About or Contact page must belong to the same company.
- Domain branding must match company.
- Parked / expired / coming-soon / suspended pages are rejected.
"""

import re
import urllib.parse
from typing import Tuple, List
from bs4 import BeautifulSoup
from rapidfuzz import fuzz
import tldextract

from .config import PARKED_INDICATORS, NOT_FOUND
from .logger import logger

# Corporate suffixes stripped for core-brand matching
_CORP_SUFFIXES = re.compile(
    r"\b(PRIVATE\s+LIMITED|PVT\.?\s*LTD\.?|LIMITED|LTD\.?|LLP|OPC"
    r"|PRODUCER\s+COMPANY\s+LIMITED|ENTERPRISES|SOLUTIONS|SERVICES"
    r"|CORPORATION|CORP|INDIA|TECHNOLOGIES|TECH|SYSTEMS|INFOTECH)\b",
    re.IGNORECASE,
)


def _core_brand(name: str) -> str:
    """Strip legal / generic suffixes and return the brand core."""
    s = _CORP_SUFFIXES.sub(" ", name)
    s = re.sub(r"[^A-Za-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _is_parked(html: str, title: str) -> Tuple[bool, str]:
    """Detect parked, expired, suspended, or coming-soon pages."""
    if not html or len(html.strip()) < 200:
        return True, "Empty / minimal HTML"
    low_html  = html.lower()
    low_title = title.lower()
    for kw in PARKED_INDICATORS:
        if kw in low_title or kw in low_html:
            return True, f"Parked indicator: '{kw}'"
    return False, ""


def validate_website(
    html: str,
    target_url: str,
    company_name: str,
    cin: str = "",
    state: str = "",
    address: str = "",
    industry: str = "",
) -> Tuple[bool, str, str]:
    """
    Verify the website truly belongs to `company_name`.

    Returns (is_valid, confidence, notes).
    confidence: 'High' | 'Medium' | 'Low'
    """
    if not html:
        return False, NOT_FOUND, "No HTML"

    soup = BeautifulSoup(html, "html.parser")

    # ── Page metadata ────────────────────────────────────────────────────────
    title = soup.title.get_text(strip=True) if soup.title else ""

    parked, parked_reason = _is_parked(html, title)
    if parked:
        return False, NOT_FOUND, parked_reason

    # Strip scripts/styles
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    body_text  = soup.get_text(separator=" ", strip=True)
    body_lower = body_text.lower()

    if len(body_text) < 200:
        return False, NOT_FOUND, "Page body too short"

    meta_desc = ""
    desc_tag = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
    if desc_tag and desc_tag.get("content"):
        meta_desc = str(desc_tag["content"])

    # ── Core brand + domain ───────────────────────────────────────────────────
    core = _core_brand(company_name)
    ext  = tldextract.extract(target_url)
    domain_slug = ext.domain.lower() if ext.domain else ""

    # ── CIN presence ─────────────────────────────────────────────────────────
    cin_found = bool(cin and cin.strip().upper() in html.upper())

    # ── Foreign ccTLD rejection ───────────────────────────────────────────────
    FOREIGN_CCTLDS = {
        "uk", "co.uk", "ca", "au", "com.au", "de", "fr", "it", "es", "nl", "ru",
        "cn", "jp", "br", "nz", "co.nz", "za", "ch", "se", "no", "pl", "ie",
        "at", "be", "dk", "fi", "cz", "ro", "gr", "pt", "hu", "il", "sg", "my",
    }
    tld_suffix = ext.suffix.lower() if ext.suffix else ""
    is_foreign_cctld = tld_suffix in FOREIGN_CCTLDS

    # ── State / address match ─────────────────────────────────────────────────
    state_match   = bool(state and state.strip().lower() in body_lower)
    address_match = False
    if address:
        pins = re.findall(r"\b[1-9][0-9]{5}\b", address)
        address_match = any(p in body_text for p in pins)

    # Immediately reject foreign ccTLDs unless verified Indian presence
    if is_foreign_cctld and not cin_found and not state_match and "india" not in body_lower[:2000]:
        return False, NOT_FOUND, f"Foreign ccTLD (.{tld_suffix}) without Indian registration proof"

    # ── Core brand phrase matching ────────────────────────────────────────────
    core_lower = core.lower()
    full_name_lower = company_name.lower()

    headings = " ".join(h.get_text() for h in soup.find_all(["h1", "h2", "h3"])[:6])
    top_text = f"{title} {meta_desc} {headings}".lower()

    exact_in_top  = (core_lower in top_text) or (full_name_lower in top_text)
    exact_in_body = (core_lower in body_lower) or (full_name_lower in body_lower)

    # Token sort ratio on title / headings
    score_title = max(
        fuzz.token_sort_ratio(core_lower, title.lower()),
        fuzz.partial_ratio(core_lower, title.lower()),
    )
    score_headings = max(
        fuzz.token_sort_ratio(core_lower, headings.lower()),
        fuzz.partial_ratio(core_lower, headings.lower()),
    ) if headings else 0

    score_top = max(score_title, score_headings)

    if exact_in_top:
        name_score = max(score_top, 95)
    elif exact_in_body:
        name_score = max(score_top, 85)
    else:
        name_score = score_top

    # ── Domain–brand alignment ────────────────────────────────────────────────
    domain_match = False
    if domain_slug:
        slug_clean   = re.sub(r"[^a-z0-9]", "", domain_slug)
        core_tokens  = [t.lower() for t in core.split() if len(t) > 2]
        if core_tokens:
            concat = "".join(core_tokens)
            # Full match or all tokens in domain slug
            if concat in slug_clean or all(t in slug_clean for t in core_tokens):
                domain_match = True
            elif len(core_tokens) == 1 and (core_tokens[0] == slug_clean or slug_clean.startswith(core_tokens[0])):
                domain_match = True
            # Multi-word: slug must cover at least 50% of the brand length to avoid single common-word hijack (e.g. 'surya')
            elif len(slug_clean) >= 4 and slug_clean in concat and (len(slug_clean) / max(len(concat), 1)) >= 0.5:
                domain_match = True
            elif len(core_tokens) >= 2 and all(t in slug_clean for t in core_tokens[:2]):
                domain_match = True

    # ── Logo match ────────────────────────────────────────────────────────────
    logo_match = False
    for img in soup.find_all("img"):
        alt = (img.get("alt") or "").lower()
        src = (img.get("src") or "").lower()
        if "logo" in alt or "logo" in src:
            for tok in core.split():
                if len(tok) > 3 and tok.lower() in f"{alt} {src}":
                    logo_match = True
                    break
        if logo_match:
            break

    # ── Path-based aggregator / article filter ────────────────────────────────
    parsed = urllib.parse.urlparse(target_url)
    path_low = parsed.path.lower()
    reject_path_patterns = [
        r"/definition/",
        r"/article/",
        r"/heart-disease/",
        r"/science/",
        r"/news/",
        r"/wiki/",
        r"/yp/",
        r"/listing/",
        r"/directory/",
        r"/startups/",
        r"/indian-company/",
        r"/cin/",
        r"[uUlL]\d{5}[a-zA-Z]{2}\d{4}[a-zA-Z]{3}\d{6}",
    ]
    for pattern in reject_path_patterns:
        if re.search(pattern, path_low):
            return False, NOT_FOUND, f"URL path matches directory/article pattern ({pattern})"

    # ── Social platform as website rejection ──────────────────────────────────
    social_domains = {
        "instagram.com", "facebook.com", "linkedin.com", "twitter.com", "x.com",
        "youtube.com", "pinterest.com", "reddit.com", "tiktok.com"
    }
    target_netloc = parsed.netloc.lower().replace("www.", "")
    if any(target_netloc == s or target_netloc.endswith("." + s) for s in social_domains):
        return False, NOT_FOUND, "Social profile cannot be used as company official website"

    # ── Navigation: About / Contact links ─────────────────────────────────────
    hrefs = [a.get("href", "").lower() for a in soup.find_all("a", href=True)]
    has_about   = any("about"   in h for h in hrefs)
    has_contact = any("contact" in h for h in hrefs)

    # ── Confidence determination ──────────────────────────────────────────────
    notes: List[str] = []
    if cin_found:     notes.append("CIN confirmed")
    if domain_match:  notes.append("Domain matches brand")
    if name_score >= 80: notes.append(f"Name score {name_score}%")
    if logo_match:    notes.append("Logo matched")
    if state_match:   notes.append(f"State '{state}' matched")
    if address_match: notes.append("Address/PIN matched")
    if has_about:     notes.append("About page present")
    if has_contact:   notes.append("Contact page present")

    note_str = "; ".join(notes)

    # ── Official Website Confidence Decision ──────────────────────────────────
    # Strict rule: Domain branding MUST match company, or CIN confirmed with exact name in top text
    if domain_match:
        if cin_found or (name_score >= 80 and (has_about or has_contact or logo_match)):
            return True, "High", note_str
        if name_score >= 70 or logo_match:
            return True, "Medium", note_str

    if cin_found and exact_in_top and not is_foreign_cctld:
        return True, "Medium", f"CIN confirmed on branded page ({note_str})"

    return False, NOT_FOUND, f"Domain branding does not match company (domain_match={domain_match}, name_score={name_score}%)"

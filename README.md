# MCA 2025-26 Company Database Enrichment Scraper

A production-grade, asynchronous Python scraper designed to enrich Indian Ministry of Corporate Affairs (MCA) company databases (100,000+ companies) **without any paid APIs or API keys**.

---

## 🚀 Key Features

- **Zero Paid APIs / Zero API Keys**:
  - **Primary**: DuckDuckGo Search (HTML / Instant API)
  - **Fallback**: Bing Organic Search (HTML scraping with base64 redirect resolution)
  - **No Google Search**: Fully avoids Google to prevent rapid bot blocks and IP blacklisting.
- **Strict Anti-Hallucination & Validation Rules**:
  - Uses `RapidFuzz` for fuzzy brand matching against title, headings, and footer text.
  - Verifies MCA company CIN, State, Address PIN codes, and Logo presence.
  - Automatically identifies and rejects parked domains (GoDaddy, Sedo, Dan, etc.), expired domains, suspended pages, marketplace domains, and empty sites (<150 chars).
- **Targeted Page Crawling**:
  - Automatically crawls: `/`, `/about`, `/about-us`, `/company`, `/team`, `/leadership`, `/management`, `/contact`, `/contact-us`, `/privacy-policy`, `/terms`.
  - Discovers embedded contact forms and records the contact page URL.
- **Intelligent Contact Extraction**:
  - **Emails**: Extracts and de-obfuscates emails. Strictly excludes generic support/career emails (`support@`, `sales@`, `jobs@`, `hr@`, etc.) from being primary. Prioritizes executive/direct prefixes (`founder@`, `ceo@`, `director@`, `contact@`, etc.), using `info@` only as a last resort.
  - **Phones**: Extracts Indian business landlines, mobile numbers, and dedicated WhatsApp links (`wa.me` / `api.whatsapp.com`).
  - **Social Profiles**: Captures official LinkedIn Company pages (strictly filters out personal `/in/` employee profiles), Instagram, Facebook, and Twitter/X handles.
- **High Performance & Large Scale (100,000+ Companies)**:
  - Powered by `asyncio` and `aiohttp` connection pooling.
  - Selective Playwright Chromium fallback strictly when client-side JavaScript rendering (SPA) is needed.
  - Atomic checkpoints every **25 companies** to prevent data loss.
  - Seamless **Resume Support**: Automatically reads already processed CINs on restart and resumes without re-scraping.
- **Tri-Channel Audit Logging**:
  - `logs/success.log`: Successfully matched companies and contact details.
  - `logs/errors.log`: Network or parsing failures with detailed tracebacks.
  - `logs/not_found.log`: Every failed lookup with the exact disqualification reason.

---

## 📂 Project Architecture

```
d:/AIVATIKA_WORK/MCA_2025-26 Companies/
├── MCA_2025_Companies_Important.csv    # Input CSV (94,175+ rows)
├── enriched_companies.csv              # Output enriched CSV
├── main.py                             # CLI Entry Point
├── README.md                           # Documentation
├── logs/
│   ├── success.log                     # Verified match log
│   ├── errors.log                      # Error tracebacks
│   └── not_found.log                   # Rejection audit reasons
└── mca_enricher/
    ├── __init__.py                     # Package init
    ├── config.py                       # Blacklists, constants, settings
    ├── search.py                       # Free search engine orchestrator (DDG + Bing)
    ├── validator.py                    # RapidFuzz scoring, anti-hallucination, parked domain rejection
    ├── crawler.py                      # aiohttp async crawler with Playwright SPA fallback
    ├── extractor.py                    # Email priority, phones, WhatsApp, contact forms, social media
    ├── enricher.py                     # Single-company orchestrator
    └── runner.py                       # 100k+ Batch pipeline, checkpointing, resume, progress bar
```

---

## 🛠️ Installation & Setup

All required dependencies are installed in your Python environment:
- `aiohttp`
- `playwright` (Chromium binary installed)
- `duckduckgo_search` / `ddgs`
- `rapidfuzz`
- `tldextract`
- `pandas`
- `beautifulsoup4`
- `tqdm`

---

## ⚡ How to Run

### 1. Default Run (Processes all 94,175 companies with 5 concurrent workers):
```powershell
python main.py
```

### 2. Custom Worker Concurrency:
For faster processing on high-speed internet connections:
```powershell
python main.py --concurrency 8
```
*(Recommended concurrency: 4 to 8 to avoid search engine throttling while maximizing throughput).*

### 3. Test on a Small Batch:
To test and inspect the first 10 or 25 companies:
```powershell
python main.py --limit 10
```

### 4. Pausing & Resuming:
- **To pause**: Press `Ctrl+C`. All processed rows up to that moment are safely flushed and preserved in `enriched_companies.csv`.
- **To resume**: Simply re-run `python main.py`. The scraper detects previously completed CINs and immediately picks up where it left off.

---

## 📊 Output Schema (Exact 6 Columns)

The output CSV `enriched_companies.csv` and `genuine_companies.csv` contain the exact 6 verified columns:

| Column | Description |
|---|---|
| `Company` | Official corporate name |
| `Website` | Verified official website URL |
| `Email` | Filtered official domain email (no free/generic emails) |
| `Contact Form` | Discovered `/contact` URL or `#contact` form anchor |
| `Instagram` | Official verified corporate Instagram profile |
| `LinkedIn` | Official verified corporate LinkedIn company page |

---

## 🧹 Post-Processing (Filter Out NOT_FOUND)

To filter out companies with no website and extract only genuine companies into a clean CSV:

```powershell
python clean_genuine_companies.py
```
This generates `genuine_companies.csv` with empty fields cleaned to blanks, ready for CRM or presentation.


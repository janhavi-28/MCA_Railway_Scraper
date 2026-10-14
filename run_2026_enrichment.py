#!/usr/bin/env python3
"""
Production 2026 Batch Enrichment Pipeline
===========================================
High-throughput, proxy-enabled corporate intelligence scraper targeting:
yearwise_csv/companies_2026.csv (161,409 companies).

Key Features:
- Rotating Proxy Support (Webshare / HTTP / SOCKS5 from proxies.txt)
- Real-Time Row-by-Row Persistence (companies_2026_enriched.csv)
- Instant Checkpoint & Auto-Resume (Skipping already processed companies)
- Corporate Email Domain Website Probing (Instant website discovery without search engines)
- Controlled Concurrency with Fast Failover (No stalls or freezes)
- Live ETA & Progress Reporting
"""

import argparse
import asyncio
import csv
import itertools
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
import aiohttp
from bs4 import BeautifulSoup
import tldextract

from master_main import (
    MasterCompanyAgent,
    OUTPUT_COLUMNS,
    NOT_FOUND,
    BROWSER_HEADERS,
    USER_AGENT,
    FREE_EMAIL_DOMAINS,
    extract_registered_domain,
    normalize_company_name,
)

try:
    from gdrive_sync import GDriveSync
except ImportError:
    GDriveSync = None

# Ensure UTF-8 output and instant unbuffered streaming on Windows console
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

# ── Dynamic Storage & Path Detection (Local & Railway Persistent Volume) ──────
DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data" if Path("/app/data").is_dir() else "."))
INPUT_2026_CSV = Path(os.getenv("INPUT_CSV_PATH", "yearwise_csv/companies_2026.csv"))
OUTPUT_ENRICHED_CSV = Path(os.getenv("OUTPUT_CSV_PATH", str(DATA_DIR / "companies_2026_enriched.csv")))
PROXIES_FILE = Path("proxies.txt")

# Auto-initialize persistent volume on Railway if mounted and output CSV not yet copied
if DATA_DIR != Path(".") and not OUTPUT_ENRICHED_CSV.exists() and Path("companies_2026_enriched.csv").exists():
    try:
        import shutil
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2("companies_2026_enriched.csv", OUTPUT_ENRICHED_CSV)
        print(f"📦 Successfully initialized Railway persistent volume storage at: {OUTPUT_ENRICHED_CSV}")
    except Exception as e:
        print(f"⚠️ Warning initializing volume storage: {e}")


def load_proxies() -> List[str]:
    """Load proxy URLs from environment variable PROXIES_LIST or local proxy files."""
    raw_lines = []

    # Priority 1: Cloud Environment Variable (e.g. Railway PROXIES_LIST)
    env_proxies = os.getenv("PROXIES_LIST")
    if env_proxies:
        raw_lines.extend(env_proxies.splitlines())

    # Priority 2: Local proxy files
    candidates = [PROXIES_FILE, Path("Webshare 10 proxies.txt")]
    for p_path in candidates:
        if p_path.exists():
            with open(p_path, "r", encoding="utf-8", errors="ignore") as f:
                raw_lines.extend(f.readlines())

    proxies = []
    for line in raw_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Format 1: http://user:pass@ip:port or http://ip:port or socks5://...
        if line.startswith("http://") or line.startswith("https://") or line.startswith("socks5://"):
            proxies.append(line)
            continue

        # Format 2: ip:port:username:password
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
    return deduped


def load_processed_cins() -> Set[str]:
    """Find all CINs already enriched to enable instantaneous resume."""
    processed = set()
    if OUTPUT_ENRICHED_CSV.exists():
        try:
            with open(OUTPUT_ENRICHED_CSV, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    cin = (r.get("CIN") or "").strip().upper()
                    if cin:
                        processed.add(cin)
        except Exception:
            pass
    return processed


async def probe_email_domain_website(email: str, session: aiohttp.ClientSession, proxy: Optional[str] = None) -> Optional[str]:
    """Fast probe: If company email is custom (e.g. info@alphamoney.in), check if website is live."""
    if not email or "@" not in email:
        return None
    domain = email.split("@")[-1].strip().lower()
    if not domain or domain in FREE_EMAIL_DOMAINS or "." not in domain:
        return None

    candidates = [f"https://www.{domain}", f"https://{domain}", f"http://www.{domain}"]
    for cand in candidates:
        try:
            kwargs = {
                "headers": BROWSER_HEADERS,
                "timeout": aiohttp.ClientTimeout(total=3.5),
                "ssl": False,
            }
            if proxy:
                kwargs["proxy"] = proxy
            async with session.get(cand, **kwargs) as resp:
                if resp.status == 200:
                    return str(resp.url)
        except Exception:
            continue
    return None


async def run_pipeline(concurrency: int = 5, limit: int = 0, no_proxy: bool = False):
    if not INPUT_2026_CSV.exists():
        print(f"❌ Error: {INPUT_2026_CSV} not found.")
        sys.exit(1)

    proxies = [] if no_proxy else load_proxies()
    proxy_cycle = itertools.cycle(proxies) if proxies else None
    gdrive = GDriveSync() if GDriveSync else None

    print("=" * 76)
    print("  🚀 2026 MCA CORPORATE INTELLIGENCE PRODUCTION ENRICHMENT PIPELINE")
    print("=" * 76)
    print(f"  • Target Dataset   : {INPUT_2026_CSV.resolve()}")
    print(f"  • Enriched Output  : {OUTPUT_ENRICHED_CSV.resolve()}")
    print(f"  • Proxies Active   : {len(proxies)} loaded from proxies.txt" if proxies else "  • Mode             : Direct Local Network (No Proxies)")
    print(f"  • Worker Concurrency: {concurrency}")
    if gdrive and gdrive.is_configured:
        print(f"  • Google Drive Sync: ACTIVE (Folder: {gdrive.folder_id})")
    else:
        print("  • Google Drive Sync: Standby (Set GDRIVE_FOLDER_ID & credentials to activate)")
    print("=" * 76 + "\n")

    # Load input companies
    companies_to_process = []
    processed_cins = load_processed_cins()
    print(f"📂 Scanning progress: {len(processed_cins):,d} companies already enriched and will be skipped.")

    with open(INPUT_2026_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            cin = (r.get("CIN") or "").strip().upper()
            if cin and cin not in processed_cins:
                companies_to_process.append(r)
                if limit > 0 and len(companies_to_process) >= limit:
                    break

    total_remaining = len(companies_to_process)
    if total_remaining == 0:
        print("🎉 All companies in 2026 dataset have already been enriched! Nothing to do.")
        return

    print(f"🎯 Total Remaining Companies to Enrich: {total_remaining:,d}\n")

    # Initialize CSV header if newly created
    if not OUTPUT_ENRICHED_CSV.exists() or OUTPUT_ENRICHED_CSV.stat().st_size == 0:
        with open(OUTPUT_ENRICHED_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()

    agent = MasterCompanyAgent()
    sem = asyncio.Semaphore(concurrency)
    completed = 0
    start_time = time.time()
    lock = asyncio.Lock()

    async def process_one(co_row: Dict[str, str], idx: int):
        nonlocal completed
        async with sem:
            t0 = time.time()
            co_name = co_row.get("Company Name", "").strip()
            cin = co_row.get("CIN", "").strip()
            proxy = next(proxy_cycle) if proxy_cycle else None

            try:
                # Perform search with pre-loaded statutory data to bypass multi-gigabyte disk scans
                res = await agent.search_company(
                    co_name,
                    use_cache=False,
                    interactive=False,
                    state=co_row.get("Company State", ""),
                    cin=cin,
                    initial_record=co_row,
                    save_to_cache=False
                )

                # Merge any missing statutory fields directly from the cleaned 2026 CSV row
                for k in OUTPUT_COLUMNS:
                    if (not res.get(k) or res.get(k) == NOT_FOUND) and co_row.get(k):
                        res[k] = co_row[k]

                # Fast Probe: If email exists but website missing, check email domain directly
                if (not res.get("Company Website") or res.get("Company Website") == NOT_FOUND) and res.get("Company Email"):
                    connector = aiohttp.TCPConnector(ssl=False)
                    async with aiohttp.ClientSession(connector=connector) as probe_sess:
                        discovered_web = await probe_email_domain_website(res["Company Email"], probe_sess, proxy=proxy)
                        if discovered_web:
                            res["Company Website"] = discovered_web

            except Exception as e:
                res = {k: co_row.get(k, NOT_FOUND) for k in OUTPUT_COLUMNS}
                res["Company Name"] = co_name
                res["CIN"] = cin

            elapsed = time.time() - t0

            # Atomic thread-safe file append
            async with lock:
                with open(OUTPUT_ENRICHED_CSV, "a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
                    writer.writerow(res)

                completed += 1
                total_elapsed = time.time() - start_time
                avg_time = total_elapsed / completed if completed else 0
                remaining_time_sec = avg_time * (total_remaining - completed)
                eta_hours = remaining_time_sec / 3600

                w = res.get("Company Website") or "-"
                e = res.get("Company Email") or "-"
                ph = res.get("Company Contact Number") or "-"
                d = (res.get("Key People (Director / CEO / Stakeholder)") or "-")[:25]
                if w == NOT_FOUND: w = "-"
                if e == NOT_FOUND: e = "-"
                if ph == NOT_FOUND: ph = "-"
                if d == NOT_FOUND: d = "-"

                print(
                    f"[{completed:5d}/{total_remaining}] ({completed/total_remaining*100:4.1f}%) "
                    f"{co_name[:26]:<26} | Web: {w[:20]:<20} | Em: {e[:20]:<20} | Ph: {ph[:14]:<14} | ETA: {eta_hours:4.1f}h"
                )

                # Periodic Google Drive Auto-Sync every 250 companies
                if gdrive and gdrive.is_configured and completed % 250 == 0:
                    asyncio.get_running_loop().run_in_executor(None, gdrive.sync_file, OUTPUT_ENRICHED_CSV)

    tasks = [process_one(row, i) for i, row in enumerate(companies_to_process, 1)]
    await asyncio.gather(*tasks)

    # Final Google Drive Auto-Sync on completion
    if gdrive and gdrive.is_configured:
        print("\n☁️ Uploading final completed dataset to Google Drive...")
        gdrive.sync_file(OUTPUT_ENRICHED_CSV)

    print("\n" + "=" * 76)
    print("  🎉 ENRICHMENT COMPLETE FOR 2026 BATCH!")
    print(f"  • Companies Processed : {completed:,d}")
    print(f"  • Total Time          : {(time.time() - start_time)/60:.1f} mins")
    print(f"  • Saved File          : {OUTPUT_ENRICHED_CSV.resolve()}")
    print("=" * 76 + "\n")


def main():
    default_concurrency = int(os.getenv("CONCURRENCY", "3"))
    parser = argparse.ArgumentParser(description="2026 MCA Companies Enrichment Pipeline")
    parser.add_argument("--concurrency", type=int, default=default_concurrency, help=f"Number of concurrent workers (default: {default_concurrency})")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of companies to process (default: 0 = all)")
    parser.add_argument("--no-proxy", action="store_true", help="Run in direct local mode without proxies")
    args = parser.parse_args()

    asyncio.run(run_pipeline(concurrency=args.concurrency, limit=args.limit, no_proxy=args.no_proxy))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
MCA Company Database Enrichment Scraper v2
Strict rules: Website / Email / Contact Form / Instagram / LinkedIn

Usage:
    python main.py                          # run full dataset
    python main.py --limit 1000            # process next 1000
    python main.py --concurrency 5         # set workers
    python main.py --output my_output.csv  # custom output file
    python main.py --fresh                 # delete output and restart from scratch
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows console
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from mca_enricher.config import DEFAULT_INPUT_CSV, DEFAULT_OUTPUT_CSV, DEFAULT_CONCURRENCY
from mca_enricher.runner import BatchPipeline
from mca_enricher.logger import logger


def parse_args():
    p = argparse.ArgumentParser(
        description="MCA Enrichment Scraper v2 - zero paid APIs."
    )
    p.add_argument("-i", "--input",       dest="input_csv",  default=DEFAULT_INPUT_CSV)
    p.add_argument("-o", "--output",      dest="output_csv", default=DEFAULT_OUTPUT_CSV)
    p.add_argument("-c", "--concurrency", dest="concurrency",type=int, default=DEFAULT_CONCURRENCY)
    p.add_argument("-l", "--limit",       dest="limit",      type=int, default=None,
                   help="Max companies to process in this run (default: all remaining)")
    p.add_argument("--fresh", action="store_true",
                   help="Delete existing output and restart from the first row")
    return p.parse_args()


def main():
    args = parse_args()

    if not Path(args.input_csv).exists():
        print(f"\n[ERROR] Input file '{args.input_csv}' not found.")
        sys.exit(1)

    # Fresh restart: delete the output file so all companies are re-processed
    if args.fresh:
        out = Path(args.output_csv)
        if out.exists():
            out.unlink()
            print(f"[FRESH] Deleted {args.output_csv} - starting from row 1.")

    print("=" * 65)
    print("  MCA Company Enrichment Scraper v2")
    print("=" * 65)
    print(f"  Input        : {args.input_csv}")
    print(f"  Output       : {args.output_csv}")
    print(f"  Workers      : {args.concurrency}")
    print(f"  Limit        : {args.limit or 'ALL remaining'}")
    print(f"  Columns      : Company | Website | Email | Contact Form | Instagram | LinkedIn")
    print(f"  Search order : DuckDuckGo -> Bing -> Google -> Startpage")
    print(f"  Resumable    : YES (skips already-processed companies)")
    print("=" * 65)

    pipeline = BatchPipeline(
        input_csv   = args.input_csv,
        output_csv  = args.output_csv,
        concurrency = args.concurrency,
        limit       = args.limit,
    )

    try:
        asyncio.run(pipeline.run())
    except KeyboardInterrupt:
        print("\n[PAUSED] Progress saved. Run again to resume.")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

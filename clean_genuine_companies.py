#!/usr/bin/env python3
"""
Clean Enriched MCA Companies
============================
Filters enriched_companies.csv to remove all 'NOT_FOUND' companies,
keeping ONLY genuine, verified companies with official websites and contacts.

Usage:
    python clean_genuine_companies.py
    python clean_genuine_companies.py --output genuine_companies.csv
    python clean_genuine_companies.py --blanks              # (default) replace 'NOT_FOUND' in empty fields with clean blanks
    python clean_genuine_companies.py --keep-not-found      # keep 'NOT_FOUND' text in empty fields
    python clean_genuine_companies.py --in-place            # overwrite enriched_companies.csv (creates backup)
"""

import argparse
import csv
import shutil
import sys
from pathlib import Path
from typing import List, Dict

# Ensure UTF-8 output on Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def clean_row(row: Dict[str, str], replace_not_found_with_blank: bool = True) -> Dict[str, str]:
    cleaned = {}
    for k, v in row.items():
        val = (v or "").strip()
        if replace_not_found_with_blank and val.upper() == "NOT_FOUND":
            cleaned[k] = ""
        else:
            cleaned[k] = val
    return cleaned


def main():
    parser = argparse.ArgumentParser(
        description="Filter enriched_companies.csv to keep only genuine companies."
    )
    parser.add_argument(
        "-i", "--input",
        default="enriched_companies.csv",
        help="Input CSV file path (default: enriched_companies.csv)"
    )
    parser.add_argument(
        "-o", "--output",
        default="genuine_companies.csv",
        help="Output CSV file path (default: genuine_companies.csv)"
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the input file directly (creates an .old backup first)"
    )
    parser.add_argument(
        "--keep-not-found",
        action="store_true",
        help="Retain 'NOT_FOUND' string in fields where data wasn't found (default: replace with clean blanks)"
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] Input file '{input_path}' not found.")
        sys.exit(1)

    # Read input CSV
    with open(input_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if not fieldnames or "Company" not in fieldnames or "Website" not in fieldnames:
            print("[ERROR] CSV does not have expected columns (Company, Website, ...).")
            sys.exit(1)
        raw_rows = list(reader)

    total_rows = len(raw_rows)

    # Filter: Keep only rows with genuine verified website
    genuine_rows: List[Dict[str, str]] = []
    replace_blanks = not args.keep_not_found

    for row in raw_rows:
        web = (row.get("Website") or "").strip().upper()
        if web and web != "NOT_FOUND":
            genuine_rows.append(clean_row(row, replace_not_found_with_blank=replace_blanks))

    total_genuine = len(genuine_rows)
    total_removed = total_rows - total_genuine

    # Metrics
    has_email = sum(1 for r in genuine_rows if r.get("Email") and r.get("Email") != "NOT_FOUND")
    has_form = sum(1 for r in genuine_rows if r.get("Contact Form") and r.get("Contact Form") != "NOT_FOUND")
    has_ig = sum(1 for r in genuine_rows if r.get("Instagram") and r.get("Instagram") != "NOT_FOUND")
    has_li = sum(1 for r in genuine_rows if r.get("LinkedIn") and r.get("LinkedIn") != "NOT_FOUND")

    # Determine destination
    if args.in_place:
        backup_path = input_path.with_suffix(".csv.backup")
        shutil.copy2(input_path, backup_path)
        print(f"[BACKUP] Saved copy of raw file to '{backup_path.name}'")
        target_output = input_path
    else:
        target_output = Path(args.output)

    # Write cleaned CSV
    with open(target_output, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(genuine_rows)

    # Summary Report
    print("=" * 65)
    print("  MCA Enrichment Cleaner - Summary")
    print("=" * 65)
    print(f"  Input File         : {input_path}")
    print(f"  Total Processed    : {total_rows}")
    print(f"  NOT_FOUND (Removed): {total_removed} ({total_removed/max(total_rows, 1)*100:.1f}%)")
    print(f"  Genuine Companies  : {total_genuine} ({total_genuine/max(total_rows, 1)*100:.1f}%)")
    print("-" * 65)
    print(f"  Verified Websites  : {total_genuine} (100.0%)")
    print(f"  Emails Discovered  : {has_email}")
    print(f"  Contact Forms      : {has_form}")
    print(f"  Instagram Profiles : {has_ig}")
    print(f"  LinkedIn Profiles  : {has_li}")
    print(f"  Output Saved To    : {target_output.resolve()}")
    print("=" * 65)

    # Show first 5 samples
    print("\nPreview of cleaned dataset (first 5 companies):")
    for i, r in enumerate(genuine_rows[:5], 1):
        print(f"  {i}. {r.get('Company')}")
        print(f"     Website : {r.get('Website')}")
        if r.get('Email'):
            print(f"     Email   : {r.get('Email')}")
        if r.get('Contact Form'):
            print(f"     Form    : {r.get('Contact Form')}")
        if r.get('Instagram'):
            print(f"     IG      : {r.get('Instagram')}")
        if r.get('LinkedIn'):
            print(f"     LinkedIn: {r.get('LinkedIn')}")
        print()


if __name__ == "__main__":
    main()

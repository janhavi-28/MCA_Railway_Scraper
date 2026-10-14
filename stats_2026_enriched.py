#!/usr/bin/env python3
"""
Statistics & Quality Audit Tool for companies_2026_enriched.csv
================================================================
Generates comprehensive yield, fill-rate, contactability, and demographic analytics
for enriched 2026 MCA company intelligence data.
"""

import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Any

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ENRICHED_CSV = Path("companies_2026_enriched.csv")
MASTER_2026_CSV = Path("yearwise_csv/companies_2026.csv")
STATS_SUMMARY_TXT = Path("companies_2026_stats_summary.txt")

FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "rediffmail.com",
    "icloud.com", "protonmail.com", "zoho.com", "yandex.com", "aol.com"
}


def is_valid_field(val: Any) -> bool:
    """Check if value is present and not a placeholder."""
    if not val:
        return False
    v = str(val).strip()
    return bool(v) and v.upper() not in {"NOT_FOUND", "NONE", "NULL", "NAN", "-"}


def generate_statistics():
    if not ENRICHED_CSV.exists():
        print(f"❌ Error: {ENRICHED_CSV} not found.")
        return

    # Total master count
    master_total = 161409
    if MASTER_2026_CSV.exists():
        try:
            with open(MASTER_2026_CSV, "r", encoding="utf-8", errors="ignore") as f:
                master_total = max(0, sum(1 for _ in f) - 1)
        except Exception:
            pass

    # Read enriched data
    rows: List[Dict[str, str]] = []
    with open(ENRICHED_CSV, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("CIN") or r.get("Company Name"):
                rows.append(r)

    total_enriched = len(rows)
    if total_enriched == 0:
        print("⚠️ No data found in companies_2026_enriched.csv yet.")
        return

    # Metrics counters
    field_counts = Counter()
    custom_domain_emails = 0
    free_domain_emails = 0
    states_counter = Counter()
    industries_counter = Counter()

    contactable_count = 0
    high_value_leads = 0  # Website + Email + Director

    for r in rows:
        has_web = is_valid_field(r.get("Company Website"))
        has_email = is_valid_field(r.get("Company Email"))
        has_phone = is_valid_field(r.get("Company Contact Number"))
        has_form = is_valid_field(r.get("Company Contact Form"))
        has_people = is_valid_field(r.get("Key People (Director / CEO / Stakeholder)"))
        has_li = is_valid_field(r.get("Company LinkedIn"))
        has_ig = is_valid_field(r.get("Company Instagram"))

        for col, val in r.items():
            if is_valid_field(val):
                field_counts[col] += 1

        # Email categorization
        if has_email:
            em = str(r.get("Company Email", "")).lower().strip()
            dom = em.split("@")[-1] if "@" in em else ""
            if dom in FREE_EMAIL_DOMAINS:
                free_domain_emails += 1
            else:
                custom_domain_emails += 1

        # Contactability
        if has_web or has_email or has_phone or has_form or has_li or has_ig:
            contactable_count += 1

        if has_web and has_email and has_people:
            high_value_leads += 1

        # Demographics
        st = r.get("Company State", "").strip()
        if st and st != "NOT_FOUND":
            states_counter[st] += 1

        ind = r.get("Company Industrial Classification", "").strip()
        if ind and ind != "NOT_FOUND":
            industries_counter[ind] += 1

    # Formatting output text
    lines = []
    def p(text: str = ""):
        print(text)
        lines.append(text)

    p("=" * 78)
    p("  📊 2026 MCA ENRICHMENT DATASET STATISTICS & QUALITY AUDIT REPORT")
    p("=" * 78)
    p(f"  • Source File              : {ENRICHED_CSV.resolve()}")
    p(f"  • Total Companies Enriched : {total_enriched:,d}")
    p(f"  • Master 2026 Pool Size    : {master_total:,d}")
    p(f"  • Progress Completed       : {(total_enriched / master_total * 100):.2f}%")
    p(f"  • Remaining to Enrich      : {max(0, master_total - total_enriched):,d}")
    p("=" * 78)

    p("\n🎯 1. DIGITAL INTELLIGENCE & CONTACT REACH (Lead Generation Yield)")
    p("-" * 78)
    p(f"  {'Field Name':<38} | {'Found':<10} | {'Fill Rate':<10}")
    p("-" * 78)
    
    digital_fields = [
        ("Company Website", "🌐 Corporate Websites"),
        ("Company Email", "📧 Verified Emails"),
        ("Company Contact Number", "📞 Contact Numbers (Tel/Mob)"),
        ("Company Contact Form", "📝 Web Contact Forms"),
        ("Key People (Director / CEO / Stakeholder)", "👥 Directors / Key People"),
        ("Employee Strength", "💼 Headcount / Strength"),
        ("Company LinkedIn", "🔗 Official LinkedIn"),
        ("Company Instagram", "📸 Official Instagram"),
    ]

    for raw_col, label in digital_fields:
        cnt = field_counts[raw_col]
        pct = (cnt / total_enriched) * 100
        p(f"  {label:<38} | {cnt:<10,d} | {pct:>6.2f}%")

    p("-" * 78)
    p(f"  • Corporate Domain Emails (@company.com) : {custom_domain_emails:,d} ({custom_domain_emails/total_enriched*100:.2f}%)")
    p(f"  • Free Webmail (@gmail/@yahoo/etc)       : {free_domain_emails:,d} ({free_domain_emails/total_enriched*100:.2f}%)")
    p(f"  • Any Contact Reach (Web/Email/Social)   : {contactable_count:,d} ({contactable_count/total_enriched*100:.2f}%)")
    p(f"  • High-Value Triple Match (Web+Email+Dir): {high_value_leads:,d} ({high_value_leads/total_enriched*100:.2f}%)")

    p("\n🏛️  2. STATUTORY & CORPORATE BASELINE")
    p("-" * 78)
    p(f"  {'Field Name':<38} | {'Found':<10} | {'Fill Rate':<10}")
    p("-" * 78)
    
    statutory_fields = [
        ("CIN", "🆔 Corporate Identity No (CIN)"),
        ("Company Name", "🏢 Legal Company Name"),
        ("Company Registration Date", "📅 Incorporation Date"),
        ("Company Class", "🏛️  Company Class"),
        ("Company Industrial Classification", "🏭 Industrial Classification"),
        ("Company State", "📍 Registered State"),
        ("Company Address", "📮 Registered Office Address"),
        ("Authorized Capital", "💰 Authorized Capital (INR)"),
        ("Paidup Capital", "💵 Paid-up Capital (INR)"),
    ]

    for raw_col, label in statutory_fields:
        cnt = field_counts[raw_col]
        pct = (cnt / total_enriched) * 100
        p(f"  {label:<38} | {cnt:<10,d} | {pct:>6.2f}%")

    p("-" * 78)

    p("\n📍 3. TOP 5 STATES IN CURRENT ENRICHED BATCH")
    p("-" * 78)
    for st, c in states_counter.most_common(5):
        p(f"  • {st:<30} : {c:,d} companies ({(c/total_enriched*100):.1f}%)")

    p("\n🏭 4. TOP 5 INDUSTRIES IN CURRENT ENRICHED BATCH")
    p("-" * 78)
    for ind, c in industries_counter.most_common(5):
        p(f"  • {ind:<30} : {c:,d} companies ({(c/total_enriched*100):.1f}%)")

    # Sample Recent Leads
    p("\n⭐ 5. RECENT HIGH-INTEL SAMPLES (Latest Enriched Leads)")
    p("-" * 78)
    sample_leads = [
        r for r in rows
        if is_valid_field(r.get("Company Website")) and is_valid_field(r.get("Company Email"))
    ][-3:]

    if not sample_leads:
        sample_leads = [r for r in rows if is_valid_field(r.get("Company Website"))][-3:]

    for i, s in enumerate(sample_leads, 1):
        p(f"  [{i}] {s.get('Company Name')}")
        p(f"      • CIN       : {s.get('CIN')}")
        p(f"      • Website   : {s.get('Company Website')}")
        p(f"      • Email     : {s.get('Company Email')}")
        p(f"      • Phone     : {s.get('Company Contact Number', 'NOT_FOUND')}")
        p(f"      • Directors : {s.get('Key People (Director / CEO / Stakeholder)')}")
        p(f"      • Socials   : LI: {s.get('Company LinkedIn')} | IG: {s.get('Company Instagram')}")
        p()

    p("=" * 78)
    p(f"  ✅ Report saved to: {STATS_SUMMARY_TXT.resolve()}")
    p("=" * 78 + "\n")

    # Save to text summary file
    try:
        with open(STATS_SUMMARY_TXT, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        print(f"Warning: Could not save summary file: {e}")


if __name__ == "__main__":
    generate_statistics()

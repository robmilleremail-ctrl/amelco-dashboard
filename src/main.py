#!/usr/bin/env python3
"""
Amelco US Gaming Market Dashboard
Weekly pre-call briefing generator.

Usage:
    python src/main.py [--date YYYY-MM-DD] [--output-dir PATH] [--no-cache]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, date, timezone
from pathlib import Path

# Ensure src/ is on the path when run from project root
sys.path.insert(0, str(Path(__file__).parent))

from utils import log_info, log_error, log_warning, today_str, find_project_root
from news_fetcher import fetch_headlines, generate_news_summary
from revenue_fetcher import fetch_revenue_data
from legislation_fetcher import fetch_legislation_updates
from state_matrix import build_state_matrix, get_status_summary
from recommender import generate_recommendations
from report_builder import build_report, write_report
from html_builder import build_html_report, write_html_report, add_password_gate


def load_config(project_root: Path) -> dict:
    config_path = project_root / "config.json"
    if not config_path.exists():
        log_error(f"config.json not found at {config_path}")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


def resolve_output_dir(config: dict, project_root: Path, override: str | None = None) -> Path:
    raw = override or config.get("output_dir", "output")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = project_root / p
    return p


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Amelco US Gaming Market Dashboard")
    parser.add_argument("--date", default=today_str(), help="Report date (YYYY-MM-DD)")
    parser.add_argument("--output-dir", default=None, help="Override output directory")
    parser.add_argument("--no-cache", action="store_true", help="Bypass page cache")
    args = parser.parse_args()

    start_time = time.time()
    run_date = args.date

    print(f"\n{'='*60}")
    print(f"  Amelco US Gaming Dashboard — {run_date}")
    print(f"{'='*60}\n")

    project_root = find_project_root()
    config = load_config(project_root)
    data_dir = project_root / "data"
    data_dir.mkdir(exist_ok=True)
    output_dir = resolve_output_dir(config, project_root, args.output_dir)

    # Verify Anthropic SDK can find a key (env var or Claude Code config)
    try:
        import anthropic as _anth
        _anth.Anthropic()
    except _anth.AuthenticationError:
        log_error("No Anthropic API key found.")
        log_error("Set it with: export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    # ── Step 1: News ──────────────────────────────────────────────────────────
    log_info("Step 1/5: Fetching news headlines...")
    headlines, failed_news = fetch_headlines(config)
    sources_checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    log_info("Step 1/5: Generating news summary via Claude...")
    news_summary = generate_news_summary(headlines, config)

    # ── Step 2: Revenue ───────────────────────────────────────────────────────
    log_info("Step 2/5: Fetching state revenue data...")
    revenue_map, failed_revenue = fetch_revenue_data(config, data_dir)
    log_info(f"  Revenue data available for {len(revenue_map)} states")

    # ── Step 3: Legislation ───────────────────────────────────────────────────
    log_info("Step 3/5: Fetching legislation updates...")
    active_bills, changed_bill_ids, failed_legislation = fetch_legislation_updates(config, data_dir)
    log_info(f"  {len(active_bills)} active bills tracked, {len(changed_bill_ids)} changed this run")

    # ── Step 4: State Matrix ──────────────────────────────────────────────────
    log_info("Step 4/5: Building state matrix...")
    status_summary = get_status_summary(config, data_dir)
    state_matrix_md = build_state_matrix(config, data_dir, revenue_map)

    # ── Step 5: Recommendations ───────────────────────────────────────────────
    log_info("Step 5/5: Generating strategic recommendations via Claude...")
    recommendations = generate_recommendations(
        config, news_summary, revenue_map, active_bills, data_dir
    )

    # ── Assemble Report ───────────────────────────────────────────────────────
    log_info("Assembling final report...")
    report_content = build_report(
        run_date=run_date,
        news_summary=news_summary,
        state_matrix_md=state_matrix_md,
        active_bills=active_bills,
        changed_bill_ids=changed_bill_ids,
        recommendations=recommendations,
        failed_news_sources=failed_news,
        failed_revenue_sources=failed_revenue,
        failed_legislation_sources=failed_legislation,
        sources_checked_at=sources_checked_at,
        status_summary=status_summary,
    )

    output_path = write_report(report_content, output_dir, run_date)

    # HTML report
    html_content = build_html_report(
        run_date=run_date,
        news_summary=news_summary,
        headlines=headlines,
        revenue_map=revenue_map,
        active_bills=active_bills,
        changed_bill_ids=changed_bill_ids,
        recommendations=recommendations,
        failed_news_sources=failed_news,
        failed_revenue_sources=failed_revenue,
        failed_legislation_sources=failed_legislation,
        sources_checked_at=sources_checked_at,
        status_summary=status_summary,
        config=config,
        data_dir=data_dir,
    )
    # Save ungated version for local server use
    ungated_path = write_html_report(html_content, output_dir, run_date)

    # Apply password gate for the public/shared version
    pw_hash = config.get("dashboard_password_hash") or os.environ.get("DASHBOARD_PASSWORD_HASH")
    if pw_hash:
        gated_content = add_password_gate(html_content, pw_hash, run_date)
        gated_path = output_dir / f"amelco-dashboard-{run_date}-protected.html"
        gated_path.write_text(gated_content, encoding="utf-8")

    html_path = ungated_path

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"  ✅ Report complete in {elapsed:.0f}s")
    print(f"  📄 Markdown: {output_path}")
    print(f"  🌐 HTML:     {html_path}")
    print(f"  📰 Headlines fetched: {len(headlines)}")
    print(f"  🗺️  States with revenue data: {len(revenue_map)}")
    print(f"  📋 Active bills tracked: {len(active_bills)}")
    print(f"  🔔 Bills changed this run: {len(changed_bill_ids)}")
    if failed_news or failed_revenue or failed_legislation:
        print(f"\n  ⚠️  Some sources unavailable:")
        if failed_news:
            print(f"     News: {', '.join(failed_news)}")
        if failed_revenue:
            print(f"     Revenue: {', '.join(failed_revenue)}")
        if failed_legislation:
            print(f"     Legislation: {', '.join(failed_legislation)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

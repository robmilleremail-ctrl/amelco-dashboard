"""Assembles all sections into the final markdown report."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from utils import today_str


def build_report(
    run_date: str,
    news_summary: str,
    state_matrix_md: str,
    active_bills: list[dict],
    changed_bill_ids: list[str],
    recommendations: str,
    failed_news_sources: list[str],
    failed_revenue_sources: list[str],
    failed_legislation_sources: list[str],
    sources_checked_at: str,
    status_summary: dict,
) -> str:
    sections = [
        _build_header(run_date, status_summary),
        _build_news_section(news_summary, failed_news_sources, sources_checked_at),
        _build_state_matrix_section(state_matrix_md),
        _build_legislation_section(active_bills, changed_bill_ids),
        _build_recommendations_section(recommendations),
        _build_footer(failed_news_sources, failed_revenue_sources, failed_legislation_sources, run_date),
    ]
    return "\n\n---\n\n".join(sections)


def write_report(content: str, output_dir: Path, run_date: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"amelco-dashboard-{run_date}.md"
    filename.write_text(content, encoding="utf-8")
    return filename


def _build_header(run_date: str, status_summary: dict) -> str:
    osb_live = status_summary.get("osb_live", 0)
    ig_live = status_summary.get("igaming_live", 0)
    osb_legal = status_summary.get("osb_legal_not_launched", 0)

    return f"""# Amelco US Gaming Market Dashboard
## Weekly Briefing — {run_date}

> **Prepared for:** Rob Miller, US Strategic Partner, Amelco
> **Purpose:** Pre-call briefing for weekly Amelco strategy call
> **Generated:** {run_date}

### Market Snapshot
| Metric | Count |
|--------|-------|
| States with Live OSB | {osb_live} |
| States with Live iGaming | {ig_live} |
| States: OSB Legal, Not Launched | {osb_legal} |"""


def _build_news_section(summary: str, failed_sources: list[str], checked_at: str) -> str:
    failure_note = ""
    if failed_sources:
        failure_note = f"\n\n> ⚠️ **Sources unavailable this run:** {', '.join(failed_sources)}"

    return f"""## Section 1: Weekly News Summary

{summary}{failure_note}

*Sources checked: {checked_at}*"""


def _build_state_matrix_section(matrix_md: str) -> str:
    return f"""## Section 2: State-by-State Regulatory & Revenue Matrix

{matrix_md}"""


def _build_legislation_section(active_bills: list[dict], changed_ids: list[str]) -> str:
    changed_set = set(changed_ids)

    if not active_bills:
        return """## Section 3: Legislative Tracker

*No active legislation tracked this week. Sources may have been unavailable or no bills found.*"""

    # Separate by relevance
    high = [b for b in active_bills if b.get("amelco_relevance") == "High"]
    medium = [b for b in active_bills if b.get("amelco_relevance") == "Medium"]
    low = [b for b in active_bills if b.get("amelco_relevance") == "Low"]

    lines = ["## Section 3: Legislative Tracker\n"]

    if changed_ids:
        lines.append(f"> 🔔 **{len(changed_ids)} bill(s) updated this week.**\n")

    def fmt_table(bills: list[dict]) -> str:
        rows = [
            "| State | Bill | Category | Summary | Status | Last Action | Relevance |",
            "|-------|------|----------|---------|--------|-------------|-----------|",
        ]
        for b in bills:
            bill_id = b.get("id", "")
            changed_marker = "🆕 " if bill_id in changed_set else ""
            state = b.get("state", "")
            bill_num = b.get("bill_numbers", "")
            cat = b.get("category", "")
            summary = b.get("summary", "")[:80] + ("..." if len(b.get("summary", "")) > 80 else "")
            status = b.get("status", "")
            last_action = b.get("last_action_date", "")
            relevance = b.get("amelco_relevance", "")
            rows.append(
                f"| {changed_marker}{state} | {bill_num} | {cat} | {summary} | {status} | {last_action} | {relevance} |"
            )
        return "\n".join(rows)

    if high:
        lines.append("### 🔴 High Relevance")
        lines.append(fmt_table(high))
        lines.append("")

    if medium:
        lines.append("### 🟡 Medium Relevance")
        lines.append(fmt_table(medium))
        lines.append("")

    if low:
        lines.append("### ⚪ Low Relevance")
        lines.append(fmt_table(low))
        lines.append("")

    return "\n".join(lines)


def _build_recommendations_section(recommendations: str) -> str:
    return f"""## Section 4: Strategic Recommendations

*AI-generated based on this week's news, legislation, and revenue data.*

{recommendations}"""


def _build_footer(
    failed_news: list[str],
    failed_revenue: list[str],
    failed_legislation: list[str],
    run_date: str,
) -> str:
    lines = ["## Report Notes\n"]

    all_failures = []
    if failed_news:
        all_failures.append(f"**News:** {', '.join(failed_news)}")
    if failed_revenue:
        all_failures.append(f"**Revenue:** {', '.join(failed_revenue)}")
    if failed_legislation:
        all_failures.append(f"**Legislation:** {', '.join(failed_legislation)}")

    if all_failures:
        lines.append("**Unavailable sources this run:**")
        for f in all_failures:
            lines.append(f"- {f}")
        lines.append("")

    lines.append(f"*Report generated: {run_date}*")
    lines.append("*Data is sourced from public information. Verify before use in presentations.*")

    return "\n".join(lines)

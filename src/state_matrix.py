"""Builds the state-by-state regulatory and revenue matrix."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from utils import (
    load_json, log_warning, today_str,
    fmt_millions, fmt_pct, fmt_tax, pct_change
)

STATE_ORDER = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DC", "DE", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WV", "WI", "WY",
]


def build_state_matrix(
    config: dict,
    data_dir: Path,
    revenue_map: dict[str, dict],
    recent_changes: Optional[set[str]] = None,
) -> str:
    """Build the markdown state matrix table. Returns the table as a string."""
    state_status = load_json(data_dir / "state_status.json")
    states = state_status.get("states", {})
    amelco_states = set(config.get("amelco_states", []))
    recent_changes = recent_changes or set()

    # Determine most recent data month
    months_available = [
        r["current"].get("month", "") for r in revenue_map.values() if "current" in r
    ]
    latest_data_month = max(months_available) if months_available else "N/A"
    status_last_updated = state_status.get("_meta", {}).get("last_updated", "unknown")

    lines = [
        "| State | OSB | iGaming | Pred. Markets | Horse Racing | OSB GGR | OSB YoY | iGaming GGR | iGaming YoY | Tax (OSB) | Tax (iG) | Data Month | Amelco |",
        "|-------|-----|---------|---------------|--------------|---------|---------|-------------|-------------|-----------|----------|------------|--------|",
    ]

    for code in STATE_ORDER:
        if code not in states:
            continue

        info = states[code]
        rev = revenue_map.get(code, {})
        current_rev = rev.get("current", {})
        prior_rev = rev.get("prior_year", {})
        is_stale = rev.get("is_stale", False)

        name = info.get("name", code)
        osb_status = _fmt_status(info.get("osb", "Not legal"))
        ig_status = _fmt_status(info.get("igaming", "Not legal"))
        pred_status = _fmt_pred(info.get("prediction_markets", "No state action"))
        hr_status = _fmt_hr(info.get("horse_racing_online", "Not legal"))

        osb_ggr_raw = current_rev.get("osb_ggr")
        ig_ggr_raw = current_rev.get("igaming_ggr")
        prior_osb_ggr = prior_rev.get("osb_ggr") if prior_rev else None
        prior_ig_ggr = prior_rev.get("igaming_ggr") if prior_rev else None

        osb_ggr_str = fmt_millions(osb_ggr_raw) if not is_stale else "N/A (stale)"
        ig_ggr_str = fmt_millions(ig_ggr_raw) if not is_stale else "N/A (stale)"
        osb_yoy_str = fmt_pct(pct_change(osb_ggr_raw, prior_osb_ggr), highlight=True)
        ig_yoy_str = fmt_pct(pct_change(ig_ggr_raw, prior_ig_ggr), highlight=True)

        data_month = current_rev.get("month", "—") if current_rev else "—"
        tax_osb = fmt_tax(info.get("tax_rate_osb"))
        tax_ig = fmt_tax(info.get("tax_rate_igaming"))

        # Amelco marker
        amelco_marker = "★" if code in amelco_states else ""

        # Bold entire row if recent status change
        state_label = f"**{code} {name}**" if code in recent_changes else f"{code} {name}"

        lines.append(
            f"| {state_label} | {osb_status} | {ig_status} | {pred_status} | {hr_status} "
            f"| {osb_ggr_str} | {osb_yoy_str} | {ig_ggr_str} | {ig_yoy_str} "
            f"| {tax_osb} | {tax_ig} | {data_month} | {amelco_marker} |"
        )

    footer = (
        f"\n> Revenue data as of **{latest_data_month}**. "
        f"Status data last updated **{status_last_updated}**. "
        f"★ = Amelco currently operates. "
        f"**Bold state** = status changed in last 30 days. "
        f"**▲/▼** = YoY growth >25% or decline >10%."
    )

    return "\n".join(lines) + "\n" + footer


def _fmt_status(status: str) -> str:
    icons = {
        "Live": "🟢 Live",
        "Legal (not launched)": "🟡 Legal",
        "Legislation pending": "🔵 Pending",
        "Not legal": "⚫ No",
    }
    return icons.get(status, status)


def _fmt_pred(status: str) -> str:
    icons = {
        "Permitted": "✅",
        "Restricted": "⚠️",
        "Banned": "🚫",
        "No state action": "—",
    }
    return icons.get(status, status)


def _fmt_hr(status: str) -> str:
    icons = {
        "Live": "🟢",
        "Legal (not launched)": "🟡",
        "Not legal": "—",
    }
    return icons.get(status, status)


def get_status_summary(config: dict, data_dir: Path) -> dict:
    """Return counts of states by legal category for report header."""
    state_status = load_json(data_dir / "state_status.json")
    states = state_status.get("states", {})

    summary = {
        "osb_live": 0, "osb_legal_not_launched": 0, "osb_pending": 0, "osb_not_legal": 0,
        "igaming_live": 0, "igaming_legal_not_launched": 0, "igaming_pending": 0, "igaming_not_legal": 0,
    }
    for info in states.values():
        osb = info.get("osb", "Not legal")
        ig = info.get("igaming", "Not legal")
        if osb == "Live":
            summary["osb_live"] += 1
        elif osb == "Legal (not launched)":
            summary["osb_legal_not_launched"] += 1
        elif osb == "Legislation pending":
            summary["osb_pending"] += 1
        else:
            summary["osb_not_legal"] += 1
        if ig == "Live":
            summary["igaming_live"] += 1
        elif ig == "Legal (not launched)":
            summary["igaming_legal_not_launched"] += 1
        elif ig == "Legislation pending":
            summary["igaming_pending"] += 1
        else:
            summary["igaming_not_legal"] += 1

    return summary

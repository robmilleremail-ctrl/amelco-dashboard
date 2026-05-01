"""Fetches state revenue data, stores history, calculates YoY comparisons."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from utils import (
    fetch_page, parse_html, log_error, log_info, log_warning,
    load_json, save_json, today_str, pct_change, find_project_root
)


def load_revenue_history(data_dir: Path) -> list[dict]:
    path = data_dir / "revenue_history.json"
    data = load_json(path)
    return data.get("records", [])


def save_revenue_history(records: list[dict], data_dir: Path) -> None:
    path = data_dir / "revenue_history.json"
    save_json({"records": records}, path)


def fetch_revenue_data(config: dict, data_dir: Path) -> tuple[dict[str, dict], list[str]]:
    """
    Fetch latest revenue data from configured sources.
    Returns (state_revenue_map, failed_sources).
    state_revenue_map: {state_code: {month, osb_ggr, osb_handle, igaming_ggr, ...}}
    """
    existing = load_revenue_history(data_dir)
    new_records: list[dict] = []
    failed_sources: list[str] = []
    delay = config.get("request_delay_seconds", 2)

    for source in config.get("revenue_sources", []):
        name = source["name"]
        url = source["url"]
        log_info(f"Fetching revenue data from {name}...")
        try:
            records = _fetch_revenue_source(name, url, delay)
            if records:
                new_records.extend(records)
                log_info(f"  Got {len(records)} state-month records from {name}")
            else:
                log_warning(f"  No revenue data extracted from {name}")
                failed_sources.append(name)
        except Exception as e:
            log_error(f"  Revenue fetch failed for {name}: {e}")
            failed_sources.append(name)

    # Merge new records into history (no duplicates by state+month)
    merged = _merge_records(existing, new_records)
    save_revenue_history(merged, data_dir)

    # Build current state map: most recent record per state
    state_map = _build_state_map(merged, config)
    return state_map, failed_sources


def _fetch_revenue_source(name: str, url: str, delay: float) -> list[dict]:
    parsers = {
        "RG.org": _parse_rg_org,
        "Legal Sports Report": _parse_lsr_revenue,
        "SportsHandle": _parse_sportshandle,
    }
    parser = parsers.get(name, _parse_generic_revenue)
    html = fetch_page(url, delay=delay)
    if not html:
        return []
    return parser(html, name)


def _parse_rg_org(html: str, source: str) -> list[dict]:
    """Parse RG.org statistics page for state revenue data."""
    soup = parse_html(html)
    records = []
    today = today_str()

    # Look for tables with state revenue data
    tables = soup.find_all("table")
    for table in tables:
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not any(h in headers for h in ["state", "ggr", "revenue", "handle"]):
            continue

        rows = table.find_all("tr")[1:]  # skip header
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 2:
                continue
            record = _parse_revenue_row(cells, headers, source, today)
            if record:
                records.append(record)

    # Also try JSON-LD or embedded data
    if not records:
        records = _extract_embedded_data(html, source, today)

    return records


def _parse_lsr_revenue(html: str, source: str) -> list[dict]:
    """Parse Legal Sports Report revenue tracker."""
    soup = parse_html(html)
    records = []
    today = today_str()

    tables = soup.find_all("table")
    for table in tables:
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not headers:
            continue
        rows = table.find_all("tr")[1:]
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 2:
                continue
            record = _parse_revenue_row(cells, headers, source, today)
            if record:
                records.append(record)

    return records


def _parse_sportshandle(html: str, source: str) -> list[dict]:
    """Parse SportsHandle revenue tracker."""
    soup = parse_html(html)
    records = []
    today = today_str()

    tables = soup.find_all("table")
    for table in tables:
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        rows = table.find_all("tr")[1:]
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 2:
                continue
            record = _parse_revenue_row(cells, headers, source, today)
            if record:
                records.append(record)

    return records


def _parse_generic_revenue(html: str, source: str) -> list[dict]:
    soup = parse_html(html)
    records = []
    today = today_str()
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        for row in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            record = _parse_revenue_row(cells, headers, source, today)
            if record:
                records.append(record)
    return records


# State name to code mapping
STATE_CODES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "washington d.c.": "DC", "district of columbia": "DC",
    "d.c.": "DC", "dc": "DC",
}


def _normalize_state(raw: str) -> Optional[str]:
    """Convert state name or abbreviation to 2-letter code."""
    raw = raw.strip()
    if len(raw) == 2 and raw.upper() in STATE_CODES.values():
        return raw.upper()
    return STATE_CODES.get(raw.lower())


def _parse_money(val: str) -> Optional[float]:
    """Parse a money string like '$123.4M' or '123,456,789' into float dollars."""
    if not val:
        return None
    val = val.replace(",", "").strip()
    multiplier = 1
    if val.upper().endswith("M"):
        multiplier = 1_000_000
        val = val[:-1]
    elif val.upper().endswith("B"):
        multiplier = 1_000_000_000
        val = val[:-1]
    val = re.sub(r"[^0-9.\-]", "", val)
    try:
        return float(val) * multiplier
    except (ValueError, TypeError):
        return None


def _parse_revenue_row(cells: list[str], headers: list[str], source: str, today: str) -> Optional[dict]:
    """Try to extract a revenue record from a table row."""
    if not cells or not cells[0]:
        return None

    state_code = _normalize_state(cells[0])
    if not state_code:
        return None

    record: dict = {
        "state": state_code,
        "month": _infer_month(today),
        "osb_handle": None,
        "osb_ggr": None,
        "osb_hold_rate": None,
        "osb_tax_paid": None,
        "igaming_ggr": None,
        "source": source,
        "fetched_date": today,
    }

    for i, header in enumerate(headers):
        if i >= len(cells):
            break
        val = cells[i]
        if "handle" in header:
            record["osb_handle"] = _parse_money(val)
        elif "ggr" in header or "revenue" in header or "gross" in header:
            money = _parse_money(val)
            if "igaming" in header or "casino" in header or "icasino" in header:
                record["igaming_ggr"] = money
            else:
                record["osb_ggr"] = money
        elif "hold" in header:
            record["osb_hold_rate"] = _parse_pct(val)
        elif "tax" in header:
            record["osb_tax_paid"] = _parse_money(val)
        elif "month" in header or "period" in header or "date" in header:
            record["month"] = _parse_month_str(val) or record["month"]

    # Require at least some revenue data
    if record["osb_ggr"] is None and record["osb_handle"] is None and record["igaming_ggr"] is None:
        return None

    return record


def _parse_pct(val: str) -> Optional[float]:
    val = re.sub(r"[^0-9.\-]", "", val)
    try:
        return float(val) / 100
    except (ValueError, TypeError):
        return None


def _parse_month_str(val: str) -> Optional[str]:
    """Try to parse month strings like 'February 2026', 'Feb 2026', '2026-02'."""
    val = val.strip()
    for fmt in ("%B %Y", "%b %Y", "%Y-%m", "%m/%Y"):
        try:
            d = datetime.strptime(val, fmt)
            return d.strftime("%Y-%m")
        except ValueError:
            continue
    return None


def _infer_month(today_str: str) -> str:
    """Default to last month since current month data usually isn't available."""
    d = date.fromisoformat(today_str)
    if d.month == 1:
        return f"{d.year - 1}-12"
    return f"{d.year}-{d.month - 1:02d}"


def _extract_embedded_data(html: str, source: str, today: str) -> list[dict]:
    """Try to extract data from JSON-LD or script tags."""
    records = []
    # Look for state revenue patterns in script blocks
    matches = re.findall(
        r'"state"\s*:\s*"([A-Z]{2})"\s*,.*?"ggr"\s*:\s*([\d.]+)',
        html, re.IGNORECASE | re.DOTALL
    )
    for state_code, ggr_str in matches[:30]:
        try:
            records.append({
                "state": state_code.upper(),
                "month": _infer_month(today),
                "osb_handle": None,
                "osb_ggr": float(ggr_str),
                "osb_hold_rate": None,
                "osb_tax_paid": None,
                "igaming_ggr": None,
                "source": source,
                "fetched_date": today,
            })
        except ValueError:
            continue
    return records


def _merge_records(existing: list[dict], new_records: list[dict]) -> list[dict]:
    """Merge new records into existing, deduplicating by state+month (new wins)."""
    existing_map: dict[tuple, dict] = {}
    for r in existing:
        key = (r.get("state", ""), r.get("month", ""))
        existing_map[key] = r

    for r in new_records:
        key = (r.get("state", ""), r.get("month", ""))
        if key[0] and key[1]:
            existing_map[key] = r  # new data overwrites

    return sorted(existing_map.values(), key=lambda r: (r.get("state", ""), r.get("month", "")))


def _build_state_map(records: list[dict], config: dict) -> dict[str, dict]:
    """
    For each state, find the most recent record.
    Also attach the same-month-prior-year record for YoY.
    Returns {state_code: {current: record, prior_year: record or None}}.
    """
    staleness_days = config.get("revenue_staleness_days", 90)
    today = date.today()

    by_state: dict[str, list[dict]] = {}
    for r in records:
        state = r.get("state", "")
        if state:
            by_state.setdefault(state, []).append(r)

    result: dict[str, dict] = {}
    for state, state_records in by_state.items():
        sorted_records = sorted(state_records, key=lambda r: r.get("month", ""), reverse=True)
        current = sorted_records[0]

        # Check staleness
        fetched = date.fromisoformat(current.get("fetched_date", today.isoformat()))
        days_old = (today - fetched).days
        is_stale = days_old > staleness_days

        # Find prior year record
        current_month = current.get("month", "")
        prior_year_month = _prior_year_month(current_month)
        prior = next(
            (r for r in sorted_records if r.get("month") == prior_year_month),
            None
        )

        result[state] = {
            "current": current,
            "prior_year": prior,
            "is_stale": is_stale,
            "days_old": days_old,
        }

    return result


def _prior_year_month(month_str: str) -> str:
    """Return the same month one year prior: '2026-02' -> '2025-02'."""
    try:
        year, month = month_str.split("-")
        return f"{int(year) - 1}-{month}"
    except (ValueError, AttributeError):
        return ""

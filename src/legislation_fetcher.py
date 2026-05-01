"""Fetches and tracks active gaming legislation across US states."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import anthropic

from utils import (
    fetch_page, parse_html, log_error, log_info, log_warning,
    load_json, save_json, today_str, find_project_root
)

CATEGORIES = [
    "Sports Betting", "iGaming", "Prediction Markets", "Sweepstakes Ban",
    "Tax Change", "Horse Racing", "Tribal Compact", "Other"
]

STATUSES = [
    "Introduced", "In Committee", "Passed Committee", "Passed One Chamber",
    "Passed Both Chambers", "Sent to Governor", "Signed", "Vetoed",
    "Veto Overridden", "Dead/Tabled"
]

TERMINAL_STATUSES = {"Signed", "Vetoed", "Dead/Tabled"}


def load_tracker(data_dir: Path) -> dict:
    path = data_dir / "legislation_tracker.json"
    data = load_json(path)
    if not data:
        data = {"_meta": {"last_updated": today_str()}, "active": [], "archived": []}
    return data


def save_tracker(tracker: dict, data_dir: Path) -> None:
    tracker["_meta"]["last_updated"] = today_str()
    save_json(tracker, data_dir / "legislation_tracker.json")


def fetch_legislation_updates(config: dict, data_dir: Path) -> tuple[list[dict], list[str], list[str]]:
    """
    Fetch legislation updates from sources.
    Returns (active_bills, changed_bill_ids, failed_sources).
    """
    tracker = load_tracker(data_dir)
    existing_active = {b["id"]: b for b in tracker.get("active", [])}
    delay = config.get("request_delay_seconds", 2)

    fetched_bills: list[dict] = []
    failed_sources: list[str] = []

    for source in config.get("legislation_sources", []):
        name = source["name"]
        url = source["url"]
        log_info(f"Fetching legislation from {name}...")
        try:
            bills = _fetch_legislation_source(name, url, delay, config)
            if bills:
                fetched_bills.extend(bills)
                log_info(f"  Got {len(bills)} bills from {name}")
            else:
                log_warning(f"  No bills extracted from {name}")
                failed_sources.append(name)
        except Exception as e:
            log_error(f"  Legislation fetch failed for {name}: {e}")
            failed_sources.append(name)

    # Merge fetched bills with existing tracker
    changed_ids = _merge_bills(tracker, existing_active, fetched_bills)

    # Archive terminal bills older than 30 days
    _archive_old_bills(tracker)

    save_tracker(tracker, data_dir)
    return tracker.get("active", []), changed_ids, failed_sources


def _fetch_legislation_source(name: str, url: str, delay: float, config: dict) -> list[dict]:
    parsers = {
        "Gambling Insider": _parse_gambling_insider_bills,
        "Legal Sports Report": _parse_lsr_legislation,
        "Bookies.com": _parse_bookies_legislation,
    }
    parser = parsers.get(name)
    html = fetch_page(url, delay=delay)
    if not html:
        # Try Claude web search as fallback
        return _claude_legislation_search(name, url, config)

    if parser:
        bills = parser(html, name)
        if bills:
            return bills

    # Generic table parser fallback
    bills = _parse_generic_legislation_table(html, name)
    if not bills:
        bills = _claude_legislation_search(name, url, config)
    return bills


def _parse_gambling_insider_bills(html: str, source: str) -> list[dict]:
    soup = parse_html(html)
    bills = []

    # Gambling Insider bill tracker page has a structured table/list
    tables = soup.find_all("table")
    for table in tables:
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        for row in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 3:
                continue
            bill = _parse_bill_row(cells, headers, source)
            if bill:
                bills.append(bill)

    # Also check article content for bill mentions
    if not bills:
        bills = _extract_bills_from_text(soup.get_text(), source)

    return bills


def _parse_lsr_legislation(html: str, source: str) -> list[dict]:
    soup = parse_html(html)
    bills = []

    tables = soup.find_all("table")
    for table in tables:
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        for row in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 3:
                continue
            bill = _parse_bill_row(cells, headers, source)
            if bill:
                bills.append(bill)

    if not bills:
        bills = _extract_bills_from_text(soup.get_text(), source)

    return bills


def _parse_bookies_legislation(html: str, source: str) -> list[dict]:
    soup = parse_html(html)
    bills = _extract_bills_from_text(soup.get_text(), source)
    return bills


def _parse_generic_legislation_table(html: str, source: str) -> list[dict]:
    soup = parse_html(html)
    bills = []
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        for row in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 2:
                continue
            bill = _parse_bill_row(cells, headers, source)
            if bill:
                bills.append(bill)
    return bills


BILL_PATTERN = re.compile(r"\b(HB|SB|AB|HR|SR|SCR|HCR|HJR|SJR)\s*(\d+)\b", re.IGNORECASE)
STATE_NAMES = {
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming",
}

STATE_NAME_TO_CODE = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}


def _extract_bills_from_text(text: str, source: str) -> list[dict]:
    """Heuristic: find bill number mentions in plain text and create records."""
    bills = []
    matches = BILL_PATTERN.finditer(text)
    seen_bills = set()

    for m in matches:
        bill_type = m.group(1).upper()
        bill_num = m.group(2)
        bill_id_raw = f"{bill_type} {bill_num}"

        if bill_id_raw in seen_bills:
            continue
        seen_bills.add(bill_id_raw)

        # Try to find state context around this match
        start = max(0, m.start() - 200)
        end = min(len(text), m.end() + 300)
        context = text[start:end]

        state = None
        for state_name in STATE_NAMES:
            if state_name.lower() in context.lower():
                state = state_name
                break

        if not state:
            continue

        state_code = STATE_NAME_TO_CODE.get(state, "??")
        bill_id = f"{state_code}-{bill_id_raw}"

        # Infer category from context keywords
        category = _infer_category(context)
        status = _infer_status(context)

        bill = {
            "id": bill_id,
            "state": state,
            "state_code": state_code,
            "bill_numbers": bill_id_raw,
            "category": category,
            "summary": f"Gaming legislation in {state} ({bill_id_raw})",
            "status": status,
            "last_action_date": today_str(),
            "amelco_relevance": "Medium",
            "source": source,
            "last_updated": today_str(),
        }
        bill["amelco_relevance"] = _score_relevance(bill)
        bills.append(bill)

    return bills[:20]  # Cap to avoid noise


def _infer_category(context: str) -> str:
    ctx = context.lower()
    if any(w in ctx for w in ["sports bet", "sportsbook", "wagering"]):
        return "Sports Betting"
    if any(w in ctx for w in ["igaming", "online casino", "online gambling", "icasino"]):
        return "iGaming"
    if any(w in ctx for w in ["prediction market", "kalshi", "polymarket", "event contract"]):
        return "Prediction Markets"
    if any(w in ctx for w in ["sweepstakes", "gray market", "grey market"]):
        return "Sweepstakes Ban"
    if any(w in ctx for w in ["tax rate", "tax increase", "tax change"]):
        return "Tax Change"
    if any(w in ctx for w in ["horse racing", "horseracing", "adw", "pari-mutuel"]):
        return "Horse Racing"
    if any(w in ctx for w in ["tribal", "compact", "tribe", "indian gaming"]):
        return "Tribal Compact"
    return "Other"


def _infer_status(context: str) -> str:
    ctx = context.lower()
    if any(w in ctx for w in ["signed into law", "signed by governor", "governor signed"]):
        return "Signed"
    if any(w in ctx for w in ["vetoed", "veto"]):
        return "Vetoed"
    if any(w in ctx for w in ["sent to governor", "awaiting governor"]):
        return "Sent to Governor"
    if any(w in ctx for w in ["passed both", "full passage", "bicameral"]):
        return "Passed Both Chambers"
    if any(w in ctx for w in ["passed senate", "passed house", "passed one"]):
        return "Passed One Chamber"
    if any(w in ctx for w in ["passed committee", "out of committee", "committee approved"]):
        return "Passed Committee"
    if any(w in ctx for w in ["in committee", "referred to committee"]):
        return "In Committee"
    if any(w in ctx for w in ["dead", "tabled", "failed", "died"]):
        return "Dead/Tabled"
    return "Introduced"


def _parse_bill_row(cells: list[str], headers: list[str], source: str) -> Optional[dict]:
    """Parse a table row into a bill record."""
    if not cells or len(cells) < 2:
        return None

    bill = {
        "id": "",
        "state": "",
        "state_code": "",
        "bill_numbers": "",
        "category": "Other",
        "summary": "",
        "status": "Introduced",
        "last_action_date": today_str(),
        "amelco_relevance": "Low",
        "source": source,
        "last_updated": today_str(),
    }

    for i, header in enumerate(headers):
        if i >= len(cells):
            break
        val = cells[i].strip()
        h = header.lower()
        if "state" in h:
            bill["state"] = val
            code = STATE_NAME_TO_CODE.get(val, val[:2].upper() if len(val) >= 2 else "??")
            bill["state_code"] = code
        elif "bill" in h or "number" in h:
            bill["bill_numbers"] = val
        elif "category" in h or "type" in h:
            bill["category"] = _normalize_category(val)
        elif "summary" in h or "description" in h or "title" in h:
            bill["summary"] = val[:300]
        elif "status" in h:
            bill["status"] = _normalize_status(val)
        elif "date" in h or "action" in h:
            bill["last_action_date"] = val

    if not bill["state"] or not bill["bill_numbers"]:
        return None

    bill["id"] = f"{bill['state_code']}-{bill['bill_numbers']}"
    bill["amelco_relevance"] = _score_relevance(bill)
    return bill


def _normalize_category(val: str) -> str:
    for cat in CATEGORIES:
        if cat.lower() in val.lower():
            return cat
    return "Other"


def _normalize_status(val: str) -> str:
    for status in STATUSES:
        if status.lower() in val.lower():
            return status
    return "Introduced"


def _score_relevance(bill: dict) -> str:
    """Score Amelco relevance per the requirements."""
    state_code = bill.get("state_code", "")
    category = bill.get("category", "")
    status = bill.get("status", "")
    summary = bill.get("summary", "").lower()

    if status in ("Dead/Tabled", "Vetoed"):
        return "Low"

    high_triggers = [
        category in ("Sports Betting", "iGaming") and status not in TERMINAL_STATUSES,
        category == "Tribal Compact",
        "hub-and-spoke" in summary or "server" in summary,
        "horse racing" in summary and "fixed-odds" in summary,
        "fixed odds" in summary,
    ]
    if any(high_triggers):
        return "High"

    medium_triggers = [
        category == "Tax Change",
        category == "Prediction Markets",
        category == "Sweepstakes Ban",
        "license" in summary,
    ]
    if any(medium_triggers):
        return "Medium"

    return "Low"


def _merge_bills(tracker: dict, existing_map: dict, fetched_bills: list[dict]) -> list[str]:
    """Merge fetched bills into tracker. Returns list of bill IDs that changed."""
    changed = []
    merged_active = dict(existing_map)  # start from existing

    for bill in fetched_bills:
        bill_id = bill.get("id", "")
        if not bill_id:
            continue

        existing = merged_active.get(bill_id)
        if existing:
            if existing.get("status") != bill.get("status"):
                changed.append(bill_id)
            # Update with new info but preserve manual edits to relevance if set
            bill["amelco_relevance"] = existing.get("amelco_relevance", bill["amelco_relevance"])
            merged_active[bill_id] = bill
        else:
            merged_active[bill_id] = bill
            changed.append(bill_id)

    tracker["active"] = sorted(merged_active.values(), key=lambda b: b.get("state", ""))
    return changed


def _archive_old_bills(tracker: dict) -> None:
    """Move terminal bills older than 30 days to archive."""
    today = date.today()
    still_active = []
    archived = tracker.get("archived", [])

    for bill in tracker.get("active", []):
        if bill.get("status") in TERMINAL_STATUSES:
            try:
                last_action = date.fromisoformat(bill.get("last_action_date", today.isoformat()))
                if (today - last_action).days >= 30:
                    archived.append(bill)
                    continue
            except ValueError:
                pass
        still_active.append(bill)

    tracker["active"] = still_active
    tracker["archived"] = archived


def _claude_legislation_search(source_name: str, source_url: str, config: dict) -> list[dict]:
    """Use Claude with web search to find current legislation when direct scraping fails."""
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=config.get("anthropic_model", "claude-sonnet-4-6"),
            max_tokens=2000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{
                "role": "user",
                "content": (
                    f"Search {source_name} ({source_url}) and other sources for currently active "
                    f"US state gaming legislation in 2026. Find bills related to: online sports "
                    f"betting legalization, iGaming legalization, prediction markets, tribal gaming "
                    f"compacts, sweepstakes casino bans, and gaming tax changes. "
                    f"For each bill found, provide: state name, bill number(s), category, "
                    f"one-sentence summary, and current status. Format as a list."
                )
            }]
        )

        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        if not text:
            return []

        return _extract_bills_from_text(text, f"{source_name} (search)")

    except Exception as e:
        log_error(f"Claude legislation search failed for {source_name}: {e}")
        return []

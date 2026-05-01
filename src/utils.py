"""Shared utilities: HTTP, caching, date helpers, logging."""

from __future__ import annotations

import sys
import time
import hashlib
import json
import os
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup

# Module-level page cache for current run
_page_cache: dict[str, str] = {}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_last_request_times: dict[str, float] = {}


def fetch_page(url: str, delay: float = 2.0, timeout: int = 20) -> Optional[str]:
    """Fetch a URL with caching, rate limiting, and error handling. Returns HTML or None."""
    cache_key = hashlib.md5(url.encode()).hexdigest()
    if cache_key in _page_cache:
        return _page_cache[cache_key]

    domain = _extract_domain(url)
    last = _last_request_times.get(domain, 0)
    wait = delay - (time.time() - last)
    if wait > 0:
        time.sleep(wait)

    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=timeout) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text
            _page_cache[cache_key] = html
            _last_request_times[domain] = time.time()
            return html
    except httpx.HTTPStatusError as e:
        log_error(f"HTTP {e.response.status_code} fetching {url}")
        _last_request_times[domain] = time.time()
        return None
    except Exception as e:
        log_error(f"Error fetching {url}: {e}")
        _last_request_times[domain] = time.time()
        return None


def parse_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _extract_domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc
    except Exception:
        return url


def log_error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


def log_info(msg: str) -> None:
    print(f"[INFO] {msg}")


def log_warning(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


def today_str() -> str:
    return date.today().isoformat()


def month_str(d: Optional[date] = None) -> str:
    if d is None:
        d = date.today()
    return d.strftime("%Y-%m")


def load_json(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p) as f:
        return json.load(f)


def save_json(data: dict, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(data, f, indent=2)


def find_project_root() -> Path:
    """Return the project root (parent of src/)."""
    return Path(__file__).parent.parent


def pct_change(new_val: Optional[float], old_val: Optional[float]) -> Optional[float]:
    """Return percent change from old to new, or None if either is missing/zero."""
    if new_val is None or old_val is None or old_val == 0:
        return None
    return (new_val - old_val) / abs(old_val)


def fmt_millions(val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    return f"${val/1_000_000:.1f}M"


def fmt_pct(val: Optional[float], highlight: bool = False) -> str:
    if val is None:
        return "N/A"
    s = f"{val*100:+.1f}%"
    if highlight:
        if val >= 0.25:
            s = f"**{s} ▲**"
        elif val <= -0.10:
            s = f"**{s} ▼**"
    return s


def fmt_tax(val: Optional[float]) -> str:
    if val is None:
        return "—"
    return f"{val*100:.0f}%"

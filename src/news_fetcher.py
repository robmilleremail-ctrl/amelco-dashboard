"""Fetches news headlines from configured sources and generates an AI summary.

Strategy (in order):
1. RSS feed — fast, never blocked, well-structured
2. HTML scrape — fallback if no RSS
3. Claude web_search — last resort if HTML scraping also fails
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Optional
from email.utils import parsedate_to_datetime

import anthropic

from utils import fetch_page, parse_html, log_error, log_info, log_warning, today_str

# RSS feed URLs for each source (tried before HTML scraping)
RSS_FEEDS = {
    "Pechanga.net":          "https://pechanga.net/feed/",
    "Legal Sports Report":   "https://www.legalsportsreport.com/feed/",
    "SBC Americas":          "https://sbcamericas.com/feed/",
    "Casino.org":            "https://www.casino.org/news/feed/",
    "Gambling Insider":      "https://www.gamblinginsider.com/feed/rss",
    "Yogonet":               "https://www.yogonet.com/international/rss.xml",
    "iGaming Business":      "https://igamingbusiness.com/feed/",
    "GGB Magazine":          "https://ggbmagazine.com/feed/",
    "CDC Gaming":            "https://cdcgaming.com/feed/",
    "American Gaming Assoc": "https://www.americangaming.org/feed/",
    "Gaming Regulation":     "https://www.gamingregulation.com/news/feed/",
}

# Minimum headline length to be considered valid (filters out nav/footer noise)
MIN_TITLE_LEN = 20

# ── Amelco relevance scoring ──────────────────────────────────────────────────
# Based on Amelco's business: B2B sportsbook/iGaming technology, US expansion,
# clients include Flutter/FanDuel, Hard Rock Bet, Fanatics, tribal operators.

_AMELCO_HIGH = [
    # B2B technology topics — direct relevance
    "b2b", "platform", "technology provider", "software provider", "supplier",
    "white label", "integration", "trading service", "risk management",
    "player account", "pam ", "omni-channel", "retail betting",
    # Named clients / known operators Amelco works with
    "hard rock", "fanatics", "flutter", "fanduel", "entain", "bet365",
    # Market-entry events — potential new states for Amelco clients
    "legali", "new state", "market launch", "go live", "launch",
    "compact", "tribal", "igra",
    # Regulatory / licensing — affects operator clients
    "license", "permit", "regulat", "compliance",
    # Partnership / deal signals
    "partner", "partnership", "deal", "contract", "award", "select",
    "procure", "vendor", "supplier",
]

_AMELCO_MEDIUM = [
    # Broader market context
    "revenue", "ggr", "handle", "market share", "growth", "expansion",
    "sports betting", "online casino", "igaming", "online gaming",
    "prediction market", "kalshi", "polymarket",
    "draftkings", "betmgm", "penn ", "espnbet", "barstool",
    "merger", "acquisition", "m&a", "investment",
    "mobile app", "mobile betting", "app launch",
    "state", "bill", "legislation", "legalize",
]


def score_amelco_relevance(h: dict) -> int:
    """Score a headline dict for relevance to Amelco's business (higher = more relevant)."""
    combined = (h.get("title", "") + " " + h.get("snippet", "")).lower()
    score = sum(10 for term in _AMELCO_HIGH if term in combined)
    score += sum(3 for term in _AMELCO_MEDIUM if term in combined)
    return score


def get_display_headlines(headlines: list[dict], top_n: int = 5) -> list[dict]:
    """Return up to top_n most Amelco-relevant headlines per source, sorted by relevance."""
    from collections import defaultdict
    by_source: dict[str, list[dict]] = defaultdict(list)
    for h in headlines:
        by_source[h["source"]].append(h)

    result = []
    for items in by_source.values():
        ranked = sorted(items, key=score_amelco_relevance, reverse=True)
        result.extend(ranked[:top_n])
    return result

# Gaming keywords — at least one must appear in title+snippet for a headline to count
GAMING_KEYWORDS = [
    "bet", "wager", "gambling", "gaming", "casino", "sportsbook", "lottery",
    "igaming", "tribal", "compact", "prediction market", "kalshi", "polymarket",
    "sports betting", "legali", "regulat", "license", "revenue", "ggr", "handle",
    "fanatics", "draftkings", "fanduel", "betmgm", "espnbet", "flutter",
    "hard rock", "penn", "mgm", "barstool",
]


def fetch_headlines(config: dict) -> tuple[list[dict], list[str]]:
    sources = sorted(config.get("news_sources", []), key=lambda s: s.get("priority", 99))
    delay = config.get("request_delay_seconds", 2)
    all_headlines: list[dict] = []
    failed_sources: list[str] = []

    for source in sources:
        name = source["name"]
        url = source["url"]
        log_info(f"Fetching news from {name}...")

        headlines = (
            _try_rss(name, delay)
            or _try_html(name, url, delay)
            or _web_search_fallback(name, url, config)
        )

        if headlines:
            all_headlines.extend(headlines)
            log_info(f"  Got {len(headlines)} headlines from {name}")
        else:
            log_warning(f"  No usable headlines from {name}")
            failed_sources.append(name)

    return all_headlines, failed_sources


# ── RSS ───────────────────────────────────────────────────────────────────────

def _try_rss(name: str, delay: float) -> list[dict]:
    rss_url = RSS_FEEDS.get(name)
    if not rss_url:
        return []
    xml_text = fetch_page(rss_url, delay=delay)
    if not xml_text:
        return []
    return _parse_rss(xml_text, name, rss_url)


def _parse_rss(xml_text: str, source: str, base_url: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    # Handle both RSS 2.0 and Atom
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = root.findall(".//item") or root.findall(".//atom:entry", ns)

    headlines = []
    cutoff = date.today() - timedelta(days=14)  # only last 2 weeks

    for item in items[:30]:
        title = _rss_text(item, "title")
        link  = _rss_text(item, "link") or base_url
        desc  = _rss_text(item, "description") or _rss_text(item, "summary") or ""
        pub   = _rss_text(item, "pubDate") or _rss_text(item, "published") or ""

        # Strip HTML from description
        desc = re.sub(r"<[^>]+>", " ", desc).strip()
        desc = re.sub(r"\s+", " ", desc)[:300]

        if not title or len(title) < MIN_TITLE_LEN:
            continue

        # Date filter
        try:
            pub_date = parsedate_to_datetime(pub).date() if pub else date.today()
            if pub_date < cutoff:
                continue
        except Exception:
            pass

        # Relevance filter
        combined = (title + " " + desc).lower()
        if not any(kw in combined for kw in GAMING_KEYWORDS):
            continue

        headlines.append({
            "source": source,
            "title": title.strip(),
            "snippet": desc,
            "url": link.strip(),
        })

        if len(headlines) >= 15:
            break

    return headlines


def _rss_text(el: ET.Element, tag: str) -> str:
    child = el.find(tag)
    if child is None:
        return ""
    return (child.text or "").strip()


# ── HTML scrape ───────────────────────────────────────────────────────────────

def _try_html(name: str, url: str, delay: float) -> list[dict]:
    html = fetch_page(url, delay=delay)
    if not html:
        return []
    headlines = _parse_html_generic(html, url, name)
    return [h for h in headlines if _is_valid_headline(h)]


def _parse_html_generic(html: str, base_url: str, source: str) -> list[dict]:
    soup = parse_html(html)
    headlines = []

    # Remove nav, footer, header, sidebar noise
    for tag in soup.select("nav, footer, header, aside, .sidebar, .menu, .nav, .footer, .header"):
        tag.decompose()

    # Try article elements first, then heading links
    for article in soup.select("article, .post, .entry, .news-item, .article-card, .story")[:20]:
        title_el = article.select_one("h1, h2, h3, h4, .entry-title, .post-title")
        link_el  = article.select_one("a[href]")
        snip_el  = article.select_one("p, .excerpt, .summary")

        title = title_el.get_text(strip=True) if title_el else ""
        if not title or len(title) < MIN_TITLE_LEN:
            continue

        href = link_el.get("href", base_url) if link_el else base_url
        if href.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            href = f"{parsed.scheme}://{parsed.netloc}{href}"

        headlines.append({
            "source": source,
            "title": title,
            "snippet": snip_el.get_text(strip=True)[:300] if snip_el else "",
            "url": href,
        })

    # Fallback: h2/h3 links anywhere
    if not headlines:
        for h in soup.select("h2 a, h3 a")[:20]:
            text = h.get_text(strip=True)
            if len(text) >= MIN_TITLE_LEN:
                headlines.append({
                    "source": source,
                    "title": text,
                    "snippet": "",
                    "url": h.get("href", base_url),
                })

    return headlines


def _is_valid_headline(h: dict) -> bool:
    combined = (h["title"] + " " + h["snippet"]).lower()
    if not any(kw in combined for kw in GAMING_KEYWORDS):
        return False
    if len(h["title"]) < MIN_TITLE_LEN:
        return False
    return True


# ── Claude web_search fallback ────────────────────────────────────────────────

def _web_search_fallback(source_name: str, source_url: str, config: dict) -> list[dict]:
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=config.get("anthropic_model", "claude-sonnet-4-6"),
            max_tokens=1200,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{
                "role": "user",
                "content": (
                    f"Search for the most recent US sports betting, iGaming, tribal gaming, and "
                    f"prediction market news from {source_name} ({source_url}) — last 7 days only. "
                    f"Return up to 8 headlines with a one-sentence description each. "
                    f"Format each as: HEADLINE: <title> | SUMMARY: <one sentence>"
                )
            }]
        )
        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        if not text:
            return []

        headlines = []
        for line in text.split("\n"):
            m = re.search(r"HEADLINE:\s*(.+?)\s*\|\s*SUMMARY:\s*(.+)", line)
            if m:
                title = m.group(1).strip()
                snippet = m.group(2).strip()
                if len(title) >= MIN_TITLE_LEN:
                    headlines.append({
                        "source": f"{source_name}",
                        "title": title[:200],
                        "snippet": snippet[:300],
                        "url": source_url,
                    })
            elif line.strip() and not line.startswith("[") and len(line.strip()) >= MIN_TITLE_LEN:
                clean = re.sub(r"^[\d\.\-\*•]+\s*", "", line.strip())
                if any(kw in clean.lower() for kw in GAMING_KEYWORDS):
                    headlines.append({
                        "source": f"{source_name}",
                        "title": clean[:200],
                        "snippet": "",
                        "url": source_url,
                    })
        return headlines[:10]
    except Exception as e:
        log_error(f"Web search fallback failed for {source_name}: {e}")
        return []


# ── AI summary ────────────────────────────────────────────────────────────────

def generate_news_summary(headlines: list[dict], config: dict) -> str:
    if not headlines:
        return "[No headlines fetched — all news sources unavailable this run.]"

    client = anthropic.Anthropic()
    today = today_str()

    headlines_text = "\n".join(
        f"- [{h['source']}] {h['title']}" + (f": {h['snippet']}" if h['snippet'] else "")
        for h in headlines[:40]
    )

    prompt = f"""You are preparing a weekly briefing for the US Strategic Partner of Amelco, a UK-based B2B betting technology provider.

Today is {today}. Below are the latest headlines from US gaming industry news sources.

Write a single paragraph (150-250 words) summarizing the most important developments. Direct, executive-briefing tone — no fluff. Prioritize:
1. New state legalizations, launches, or governor actions
2. Major legislation advancing or failing
3. Prediction market developments (Kalshi, Polymarket, CFTC, state actions)
4. Tribal gaming news (compacts, new partnerships)
5. Major operator moves (M&A, market entries/exits)
6. Regulatory enforcement actions

Skip categories with no significant news. Do not invent anything not in the headlines.

HEADLINES:
{headlines_text}

Write only the summary paragraph."""

    try:
        response = client.messages.create(
            model=config.get("anthropic_model", "claude-sonnet-4-6"),
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        log_error(f"Claude API error generating news summary: {e}")
        raw = "\n".join(f"- [{h['source']}] {h['title']}" for h in headlines[:20])
        return f"[AI summary unavailable — API error.]\n\n**Raw headlines:**\n{raw}"

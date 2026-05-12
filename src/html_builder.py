"""Generates a clean, modern HTML version of the dashboard report."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional


def build_html_report(
    run_date: str,
    news_summary: str,
    headlines: list[dict],
    revenue_map: dict,
    active_bills: list[dict],
    changed_bill_ids: list[str],
    recommendations: str,
    failed_news_sources: list[str],
    failed_revenue_sources: list[str],
    failed_legislation_sources: list[str],
    sources_checked_at: str,
    status_summary: dict,
    config: dict,
    data_dir: Path,
) -> str:
    from utils import load_json, fmt_millions, fmt_pct, fmt_tax, pct_change
    from state_matrix import STATE_ORDER

    state_status = load_json(data_dir / "state_status.json")
    states = state_status.get("states", {})
    amelco_states = set(config.get("amelco_states", []))
    changed_set = set(changed_bill_ids)

    months_available = [
        r["current"].get("month", "") for r in revenue_map.values() if "current" in r
    ]
    latest_data_month = max(months_available) if months_available else "N/A"
    status_last_updated = state_status.get("_meta", {}).get("last_updated", "unknown")

    # ── State matrix rows ────────────────────────────────────────────────────
    state_rows_html = ""
    for code in STATE_ORDER:
        if code not in states:
            continue
        info = states[code]
        rev = revenue_map.get(code, {})
        current_rev = rev.get("current", {})
        prior_rev = rev.get("prior_year", {})
        is_stale = rev.get("is_stale", False)

        osb_ggr_raw = current_rev.get("osb_ggr") if not is_stale else None
        ig_ggr_raw = current_rev.get("igaming_ggr") if not is_stale else None
        prior_osb = prior_rev.get("osb_ggr") if prior_rev else None
        prior_ig = prior_rev.get("igaming_ggr") if prior_rev else None

        yoy_osb = pct_change(osb_ggr_raw, prior_osb)
        yoy_ig = pct_change(ig_ggr_raw, prior_ig)

        in_amelco = code in amelco_states
        row_class = "amelco-row" if in_amelco else ""

        state_rows_html += f"""
        <tr class="{row_class}">
          <td class="state-cell">
            <span class="state-code">{code}</span>
            <span class="state-name">{info.get('name','')}</span>
            {"<span class='amelco-badge'>★ Amelco</span>" if in_amelco else ""}
          </td>
          <td>{_status_badge(info.get('osb','Not legal'), 'osb')}</td>
          <td>{_status_badge(info.get('igaming','Not legal'), 'ig')}</td>
          <td>{_pred_badge(info.get('prediction_markets','No state action'))}</td>
          <td class="num">{fmt_millions(osb_ggr_raw) if osb_ggr_raw else '<span class="na">—</span>'}</td>
          <td class="num">{_yoy_html(yoy_osb)}</td>
          <td class="num">{fmt_millions(ig_ggr_raw) if ig_ggr_raw else '<span class="na">—</span>'}</td>
          <td class="num">{_yoy_html(yoy_ig)}</td>
          <td class="num">{fmt_tax(info.get('tax_rate_osb'))}</td>
          <td class="num">{fmt_tax(info.get('tax_rate_igaming'))}</td>
          <td class="num muted">{current_rev.get('month','—') if current_rev else '—'}</td>
        </tr>"""

    # ── Legislation tables ────────────────────────────────────────────────────
    high_bills = [b for b in active_bills if b.get("amelco_relevance") == "High"]
    med_bills  = [b for b in active_bills if b.get("amelco_relevance") == "Medium"]
    low_bills  = [b for b in active_bills if b.get("amelco_relevance") == "Low"]

    def bill_table(bills: list[dict], tier: str) -> str:
        if not bills:
            return ""
        tier_colors = {"High": "tag-high", "Medium": "tag-med", "Low": "tag-low"}
        rows = ""
        for b in bills:
            changed = b.get("id","") in changed_set
            rows += f"""
            <tr{"  class='changed-row'" if changed else ""}>
              <td><span class="state-code">{b.get('state_code','')}</span> {b.get('state','')}</td>
              <td><code>{b.get('bill_numbers','')}</code></td>
              <td><span class="cat-tag">{b.get('category','')}</span></td>
              <td class="summary-cell">{b.get('summary','')}</td>
              <td>{_status_pill(b.get('status',''))}</td>
              <td class="muted">{b.get('last_action_date','')}</td>
            </tr>"""
        label = {"High": "🔴 High Relevance", "Medium": "🟡 Medium Relevance", "Low": "⚪ Low Relevance"}[tier]
        return f"""
        <div class="bill-group">
          <h4 class="bill-tier-label {tier_colors[tier]}">{label}</h4>
          <div class="table-wrap">
            <table class="data-table leg-table">
              <thead><tr>
                <th>State</th><th>Bill</th><th>Category</th>
                <th>Summary</th><th>Status</th><th>Last Action</th>
              </tr></thead>
              <tbody>{rows}</tbody>
            </table>
          </div>
        </div>"""

    leg_html = bill_table(high_bills, "High") + bill_table(med_bills, "Medium") + bill_table(low_bills, "Low")
    if not leg_html:
        leg_html = '<p class="muted">No active legislation tracked this week.</p>'

    # ── Failure notices ───────────────────────────────────────────────────────
    failure_html = ""
    all_failures = []
    if failed_news_sources:
        all_failures.append(f"<strong>News:</strong> {', '.join(failed_news_sources)}")
    if failed_revenue_sources:
        all_failures.append(f"<strong>Revenue:</strong> {', '.join(failed_revenue_sources)}")
    if failed_legislation_sources:
        all_failures.append(f"<strong>Legislation:</strong> {', '.join(failed_legislation_sources)}")
    if all_failures:
        items = "".join(f"<li>{f}</li>" for f in all_failures)
        failure_html = f'<div class="alert"><strong>⚠ Sources unavailable this run:</strong><ul>{items}</ul></div>'

    # ── Recommendations ───────────────────────────────────────────────────────
    rec_html = _format_recommendations(recommendations)

    # ── Filter headlines to top 5 per source by Amelco relevance ─────────────
    from news_fetcher import get_display_headlines
    display_headlines = get_display_headlines(headlines, top_n=5)

    # ── News summary ──────────────────────────────────────────────────────────
    if not news_summary.startswith("["):
        # AI summary succeeded — show paragraph then top-5 cards below
        news_html = (
            f'<p class="news-body">{news_summary}</p>'
            f'<div class="headlines-divider"></div>'
            f'{_headlines_cards_html(display_headlines)}'
        )
    else:
        # No AI summary — show just the cards with unavailable notice
        news_html = _headlines_fallback_html(display_headlines)

    # ── Articles table (Section 5) — same filtered set ────────────────────────
    articles_html = _articles_table_html(display_headlines)

    # ── Stat cards ────────────────────────────────────────────────────────────
    osb_live = status_summary.get("osb_live", 0)
    ig_live  = status_summary.get("igaming_live", 0)
    osb_pending = status_summary.get("osb_legal_not_launched", 0)
    states_with_rev = len([r for r in revenue_map.values() if r.get("current")])

    return _html_shell(
        run_date=run_date,
        osb_live=osb_live,
        ig_live=ig_live,
        osb_pending=osb_pending,
        states_with_rev=states_with_rev,
        active_bills_count=len(active_bills),
        news_html=news_html,
        sources_checked_at=sources_checked_at,
        failure_html=failure_html,
        state_rows_html=state_rows_html,
        latest_data_month=latest_data_month,
        status_last_updated=status_last_updated,
        leg_html=leg_html,
        changed_count=len(changed_bill_ids),
        rec_html=rec_html,
        articles_html=articles_html,
        articles_count=len(display_headlines),
        total_headlines=len(headlines),
    )


def write_html_report(html: str, output_dir: Path, run_date: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"amelco-dashboard-{run_date}.html"
    path.write_text(html, encoding="utf-8")
    return path


# ── Helpers ──────────────────────────────────────────────────────────────────

def _status_badge(status: str, kind: str) -> str:
    classes = {
        "Live": "badge-live",
        "Legal (not launched)": "badge-pending",
        "Legislation pending": "badge-bill",
        "Not legal": "badge-no",
    }
    labels = {
        "Live": "Live",
        "Legal (not launched)": "Legal",
        "Legislation pending": "Pending",
        "Not legal": "—",
    }
    cls = classes.get(status, "badge-no")
    label = labels.get(status, status)
    return f'<span class="badge {cls}">{label}</span>'


def _pred_badge(status: str) -> str:
    m = {
        "Permitted": '<span class="badge badge-live">✓</span>',
        "Restricted": '<span class="badge badge-pending">~</span>',
        "Banned": '<span class="badge badge-no">✗</span>',
        "No state action": '<span class="na">—</span>',
    }
    return m.get(status, status)


def _status_pill(status: str) -> str:
    colors = {
        "Signed": "pill-signed",
        "Vetoed": "pill-vetoed",
        "Dead/Tabled": "pill-dead",
        "Sent to Governor": "pill-gov",
        "Passed Both Chambers": "pill-passed",
        "Passed One Chamber": "pill-passed1",
        "Passed Committee": "pill-committee",
        "In Committee": "pill-incommittee",
        "Introduced": "pill-intro",
        "Veto Overridden": "pill-signed",
    }
    cls = colors.get(status, "pill-intro")
    return f'<span class="pill {cls}">{status}</span>'


def _yoy_html(val: Optional[float]) -> str:
    if val is None:
        return '<span class="na">—</span>'
    pct = val * 100
    if pct >= 25:
        return f'<span class="yoy-up">▲ {pct:+.1f}%</span>'
    elif pct <= -10:
        return f'<span class="yoy-down">▼ {pct:+.1f}%</span>'
    elif pct >= 0:
        return f'<span class="yoy-pos">{pct:+.1f}%</span>'
    else:
        return f'<span class="yoy-neg">{pct:+.1f}%</span>'


def _format_recommendations(text: str) -> str:
    """Convert the AI recommendation text to styled HTML cards."""
    if text.startswith("["):
        return f'<p class="muted">{text}</p>'

    import re
    # Split on bold headers: **Name** - action
    parts = re.split(r'\n(?=\*\*)', text.strip())
    cards = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Extract header and body
        m = re.match(r'\*\*(.+?)\*\*\s*[-–]\s*(.+?)(?:\n|$)(.*)', part, re.DOTALL)
        if m:
            title = m.group(1).strip()
            action = m.group(2).strip()
            body = m.group(3).strip()
            cards += f"""
            <div class="rec-card">
              <div class="rec-header">
                <span class="rec-title">{title}</span>
                <span class="rec-action">{action}</span>
              </div>
              {f'<p class="rec-body">{body}</p>' if body else ""}
            </div>"""
        else:
            # Fallback: just wrap in a card
            cards += f'<div class="rec-card"><p>{part}</p></div>'
    return cards if cards else f'<p class="muted">{text}</p>'


def _headlines_cards_html(headlines: list[dict]) -> str:
    """Render headlines as styled source cards (no unavailable notice)."""
    if not headlines:
        return '<p class="muted">No headlines fetched this run. Check source availability.</p>'

    from collections import defaultdict
    by_source: dict[str, list[dict]] = defaultdict(list)
    for h in headlines:
        by_source[h["source"]].append(h)

    source_colors = [
        "#58a6ff", "#3fb950", "#d29922", "#a371f7",
        "#e63946", "#79c0ff", "#56d364", "#f78166",
        "#ffa657", "#39d353", "#ff7b72", "#d2a8ff",
    ]

    html = '<div class="headlines-grid">'
    for i, (source, items) in enumerate(by_source.items()):
        color = source_colors[i % len(source_colors)]
        items_html = ""
        for h in items:
            url = h.get("url", "#")
            snippet = h.get("snippet", "")
            items_html += f"""
            <div class="headline-item">
              <div class="headline-title">
                <a href="{url}" target="_blank" rel="noopener">{h['title']}</a>
              </div>
              {f'<div class="headline-snippet">{snippet[:180]}{"…" if len(snippet)>180 else ""}</div>' if snippet else ""}
            </div>"""
        html += f"""
        <div class="source-block">
          <div class="source-label" style="border-left-color:{color}; color:{color}">{source}</div>
          {items_html}
        </div>"""
    html += "</div>"
    return html


def _headlines_fallback_html(headlines: list[dict]) -> str:
    """Render headlines with an AI-unavailable notice (used when summary fails)."""
    notice = '<div class="ai-notice">AI summary unavailable — showing raw headlines. Check your Anthropic API key.</div>'
    return notice + _headlines_cards_html(headlines)


def _articles_table_html(headlines: list[dict]) -> str:
    """Render all fetched headlines as a searchable table grouped by source."""
    if not headlines:
        return '<p class="muted">No articles fetched this run.</p>'

    # Sort by source then title
    sorted_headlines = sorted(headlines, key=lambda h: (h.get("source", ""), h.get("title", "")))

    # Source color palette (cycles)
    source_colors = [
        "#58a6ff", "#3fb950", "#d29922", "#a371f7",
        "#e63946", "#79c0ff", "#56d364", "#f78166",
        "#ffa657", "#39d353", "#ff7b72", "#d2a8ff",
        "#7ee787",
    ]
    # Build source → color map
    sources_seen: list[str] = []
    for h in sorted_headlines:
        s = h.get("source", "")
        if s not in sources_seen:
            sources_seen.append(s)
    source_color_map = {s: source_colors[i % len(source_colors)] for i, s in enumerate(sources_seen)}

    rows = ""
    for h in sorted_headlines:
        source = h.get("source", "")
        title  = h.get("title", "")
        url    = h.get("url", "#")
        snippet = h.get("snippet", "")
        color  = source_color_map.get(source, "#7d8590")
        snippet_html = f'<div class="art-snippet">{snippet[:160]}{"…" if len(snippet) > 160 else ""}</div>' if snippet else ""
        rows += f"""
        <tr>
          <td class="art-source-cell">
            <span class="art-source-dot" style="background:{color}"></span>
            <span class="art-source-name">{source}</span>
          </td>
          <td class="art-title-cell">
            <a href="{url}" target="_blank" rel="noopener" class="art-link">{title}</a>
            {snippet_html}
          </td>
        </tr>"""

    return f"""
    <div class="table-wrap">
      <table class="data-table art-table">
        <thead>
          <tr>
            <th style="width:180px">Source</th>
            <th>Story</th>
          </tr>
        </thead>
        <tbody id="articlesBody">
          {rows}
        </tbody>
      </table>
    </div>
    <div class="table-note">
      {len(headlines)} articles from {len(sources_seen)} sources · Past 14 days ·
      Click any headline to open the full story
    </div>"""


def add_password_gate(html: str, password_hash: str, run_date: str) -> str:
    """Wrap the dashboard in a password gate. Correct password replaces the page via document.write."""
    import base64
    encoded = base64.b64encode(html.encode("utf-8")).decode("ascii")
    session_key = f"amelco_auth_{run_date.replace('-', '')}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Amelco Dashboard — {run_date}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{
    background:#0d1117;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
    min-height:100vh;display:flex;align-items:center;justify-content:center;
  }}
  .card{{
    background:#161b22;border:1px solid #30363d;border-radius:12px;
    padding:40px 48px;width:100%;max-width:380px;text-align:center;
  }}
  .logo{{
    width:48px;height:48px;border-radius:10px;background:#e63946;color:#fff;
    font-size:24px;font-weight:800;display:flex;align-items:center;
    justify-content:center;margin:0 auto 20px;
  }}
  h1{{color:#e6edf3;font-size:18px;font-weight:600;margin-bottom:4px}}
  p{{color:#7d8590;font-size:13px;margin-bottom:28px}}
  input{{
    width:100%;padding:10px 14px;background:#0d1117;border:1px solid #30363d;
    border-radius:6px;color:#e6edf3;font-size:15px;outline:none;
    margin-bottom:12px;font-family:inherit;letter-spacing:0.08em;
    transition:border-color 0.15s;
  }}
  input:focus{{border-color:#58a6ff}}
  input.err{{border-color:#e63946;animation:shake 0.3s ease}}
  button{{
    width:100%;padding:10px;background:#e63946;color:#fff;border:none;
    border-radius:6px;font-size:14px;font-weight:600;cursor:pointer;
    transition:opacity 0.15s;
  }}
  button:hover{{opacity:0.85}}
  .msg{{color:#e63946;font-size:12px;margin-top:10px;min-height:18px}}
  @keyframes shake{{
    0%,100%{{transform:translateX(0)}}
    25%{{transform:translateX(-6px)}}
    75%{{transform:translateX(6px)}}
  }}
</style>
</head>
<body>
<div class="card">
  <div class="logo">A</div>
  <h1>Amelco US Dashboard</h1>
  <p>Weekly briefing &mdash; {run_date}</p>
  <form id="form">
    <input type="password" id="pw" placeholder="Password"
           autocomplete="current-password" autofocus>
    <button type="submit">Enter</button>
    <div class="msg" id="msg"></div>
  </form>
</div>
<script>
const HASH="{password_hash}",KEY="{session_key}";
const B64="{encoded}";

async function sha256(s){{
  const b=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(s));
  return Array.from(new Uint8Array(b)).map(x=>x.toString(16).padStart(2,"0")).join("");
}}
function unlock(){{
  const html=new TextDecoder().decode(Uint8Array.from(atob(B64),c=>c.charCodeAt(0)));
  document.open();document.write(html);document.close();
}}
document.getElementById("form").addEventListener("submit",async e=>{{
  e.preventDefault();
  const pw=document.getElementById("pw").value;
  if(await sha256(pw)===HASH){{
    sessionStorage.setItem(KEY,"1");unlock();
  }}else{{
    const inp=document.getElementById("pw");
    inp.classList.add("err");
    document.getElementById("msg").textContent="Incorrect password.";
    setTimeout(()=>inp.classList.remove("err"),400);
    inp.value="";inp.focus();
  }}
}});
if(sessionStorage.getItem(KEY)==="1")unlock();
</script>
</body>
</html>"""


# ── HTML Shell ────────────────────────────────────────────────────────────────

def _html_shell(**ctx) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Amelco US Gaming Dashboard — {ctx['run_date']}</title>
<style>
  :root {{
    --bg:        #0d1117;
    --surface:   #161b22;
    --surface2:  #1c2128;
    --border:    #30363d;
    --text:      #e6edf3;
    --muted:     #7d8590;
    --red:       #e63946;
    --red-dim:   #7d1c22;
    --green:     #3fb950;
    --green-dim: #1a4227;
    --yellow:    #d29922;
    --yellow-dim:#3d2f0a;
    --blue:      #58a6ff;
    --blue-dim:  #0d2044;
    --purple:    #a371f7;
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    --mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html {{ font-size: 14px; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    line-height: 1.6;
    min-height: 100vh;
  }}

  /* ── Layout ── */
  .page-wrap {{ max-width: 1400px; margin: 0 auto; padding: 0 24px 60px; }}

  /* ── Header ── */
  .site-header {{
    border-bottom: 1px solid var(--border);
    padding: 20px 0 16px;
    margin-bottom: 32px;
    display: flex;
    align-items: center;
    gap: 20px;
  }}
  .logo-bar {{ display: flex; align-items: center; gap: 12px; flex: 1; }}
  .logo-mark {{
    width: 36px; height: 36px; border-radius: 6px;
    background: var(--red); display: flex; align-items: center;
    justify-content: center; font-weight: 800; font-size: 18px; color: #fff;
    flex-shrink: 0;
  }}
  .logo-text {{ font-size: 18px; font-weight: 600; }}
  .logo-sub {{ font-size: 12px; color: var(--muted); margin-top: 1px; }}
  .header-date {{ font-size: 13px; color: var(--muted); text-align: right; line-height: 1.7; }}
  .header-date strong {{ color: var(--text); }}
  .refresh-btn {{
    display: inline-flex; align-items: center; gap: 6px;
    padding: 7px 14px; border-radius: 6px;
    background: var(--surface2); border: 1px solid var(--border);
    color: var(--text); font-size: 13px; font-weight: 500;
    cursor: pointer; transition: border-color 0.15s, background 0.15s;
    white-space: nowrap; margin-top: 8px;
  }}
  .refresh-btn:hover {{ border-color: var(--blue); background: var(--blue-dim); }}
  .refresh-btn.loading {{ opacity: 0.6; cursor: not-allowed; }}
  .refresh-btn .spin {{ display: none; }}
  .refresh-btn.loading .spin {{ display: inline; animation: spin 0.8s linear infinite; }}
  .refresh-btn.loading .icon {{ display: none; }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  .refresh-toast {{
    position: fixed; bottom: 24px; right: 24px; z-index: 999;
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 8px; padding: 12px 18px;
    font-size: 13px; color: var(--text);
    box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    transition: opacity 0.3s; opacity: 0; pointer-events: none;
  }}
  .refresh-toast.show {{ opacity: 1; }}
  .refresh-toast.ok {{ border-color: var(--green); }}
  .refresh-toast.err {{ border-color: var(--red); }}

  /* ── Stat cards ── */
  .stats-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px;
    margin-bottom: 32px;
  }}
  .stat-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 18px;
  }}
  .stat-card .stat-num {{
    font-size: 28px; font-weight: 700; line-height: 1;
    color: var(--text); margin-bottom: 4px;
  }}
  .stat-card .stat-label {{
    font-size: 12px; color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.04em;
  }}
  .stat-card.accent {{ border-color: var(--red-dim); }}
  .stat-card.accent .stat-num {{ color: var(--red); }}

  /* ── Sections ── */
  .section {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    margin-bottom: 24px;
    overflow: hidden;
  }}
  .section-header {{
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 10px;
  }}
  .section-num {{
    background: var(--red); color: #fff;
    font-size: 11px; font-weight: 700;
    width: 22px; height: 22px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
  }}
  .section-title {{ font-size: 15px; font-weight: 600; flex: 1; }}
  .section-meta {{ font-size: 12px; color: var(--muted); }}
  .section-body {{ padding: 20px; }}

  /* ── News ── */
  .news-body {{
    font-size: 14px; line-height: 1.75;
    color: var(--text); max-width: 900px;
    margin-bottom: 4px;
  }}
  .sources-note {{ margin-top: 12px; font-size: 12px; color: var(--muted); }}
  .headlines-divider {{
    border-top: 1px solid var(--border);
    margin: 20px 0 16px;
  }}

  /* ── Alert ── */
  .alert {{
    background: #271a0a; border: 1px solid #5a3a10;
    border-radius: 6px; padding: 12px 16px;
    font-size: 13px; margin-bottom: 16px; color: #e8c472;
  }}
  .alert ul {{ margin: 6px 0 0 16px; }}
  .alert li {{ margin: 2px 0; }}

  /* ── Tables ── */
  .table-wrap {{
    overflow-x: auto;
    border-radius: 6px;
    border: 1px solid var(--border);
  }}
  .data-table {{
    width: 100%; border-collapse: collapse;
    font-size: 13px;
  }}
  .data-table thead tr {{
    background: var(--surface2);
  }}
  .data-table th {{
    padding: 10px 12px;
    text-align: left;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
    position: sticky; top: 0;
    background: var(--surface2);
  }}
  .data-table td {{
    padding: 9px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: middle;
  }}
  .data-table tbody tr:last-child td {{ border-bottom: none; }}
  .data-table tbody tr:hover {{ background: var(--surface2); }}
  .amelco-row {{ background: rgba(230,57,70,0.04); }}
  .amelco-row:hover {{ background: rgba(230,57,70,0.08) !important; }}
  .changed-row {{ background: rgba(88,166,255,0.04); }}

  /* Table cells */
  .state-cell {{ white-space: nowrap; }}
  .state-code {{
    font-family: var(--mono); font-size: 12px; font-weight: 700;
    color: var(--blue); margin-right: 6px;
  }}
  .state-name {{ color: var(--text); }}
  .amelco-badge {{
    font-size: 10px; font-weight: 600;
    background: var(--red-dim); color: var(--red);
    border-radius: 4px; padding: 1px 5px; margin-left: 6px;
  }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; font-family: var(--mono); font-size: 12px; }}
  .muted {{ color: var(--muted); }}
  .na {{ color: var(--border); }}

  /* ── Badges ── */
  .badge {{
    display: inline-block; padding: 2px 8px;
    border-radius: 20px; font-size: 11px; font-weight: 600;
    white-space: nowrap;
  }}
  .badge-live    {{ background: var(--green-dim); color: var(--green); }}
  .badge-pending {{ background: var(--yellow-dim); color: var(--yellow); }}
  .badge-bill    {{ background: var(--blue-dim); color: var(--blue); }}
  .badge-no      {{ color: var(--border); font-size: 13px; }}

  /* ── Status pills ── */
  .pill {{
    display: inline-block; padding: 2px 8px;
    border-radius: 4px; font-size: 11px; font-weight: 500;
    white-space: nowrap;
  }}
  .pill-signed     {{ background: var(--green-dim); color: var(--green); }}
  .pill-passed     {{ background: #0d2a1a; color: #56d364; }}
  .pill-passed1    {{ background: #0d2a1a; color: #56d364; opacity: 0.7; }}
  .pill-committee  {{ background: var(--blue-dim); color: var(--blue); }}
  .pill-incommittee{{ background: #0d1a2e; color: #79c0ff; }}
  .pill-gov        {{ background: #2d1f6e; color: #a371f7; }}
  .pill-vetoed     {{ background: var(--red-dim); color: var(--red); }}
  .pill-dead       {{ background: #1c1c1c; color: #6e7681; }}
  .pill-intro      {{ background: var(--surface2); color: var(--muted); border: 1px solid var(--border); }}

  /* ── Category tags ── */
  .cat-tag {{
    display: inline-block; padding: 2px 7px;
    border-radius: 4px; font-size: 11px;
    background: var(--surface2); color: var(--muted);
    border: 1px solid var(--border);
    white-space: nowrap;
  }}

  /* ── YoY ── */
  .yoy-up   {{ color: var(--green); font-weight: 700; }}
  .yoy-down {{ color: var(--red); font-weight: 700; }}
  .yoy-pos  {{ color: #56d364; }}
  .yoy-neg  {{ color: #f47067; }}

  /* ── Legislation ── */
  .bill-group {{ margin-bottom: 24px; }}
  .bill-group:last-child {{ margin-bottom: 0; }}
  .bill-tier-label {{
    font-size: 13px; font-weight: 600;
    margin-bottom: 10px; padding-left: 2px;
  }}
  .tag-high  {{ color: var(--red); }}
  .tag-med   {{ color: var(--yellow); }}
  .tag-low   {{ color: var(--muted); }}
  .leg-table .summary-cell {{ max-width: 320px; color: var(--muted); font-size: 12px; }}
  code {{
    font-family: var(--mono); font-size: 12px;
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 4px; padding: 1px 6px;
    color: var(--purple);
  }}

  /* ── Recommendations ── */
  .rec-card {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-left: 3px solid var(--red);
    border-radius: 6px;
    padding: 16px 18px;
    margin-bottom: 12px;
  }}
  .rec-card:last-child {{ margin-bottom: 0; }}
  .rec-header {{ margin-bottom: 6px; }}
  .rec-title {{
    font-weight: 700; font-size: 14px; color: var(--text);
    margin-right: 8px;
  }}
  .rec-action {{ color: var(--muted); font-size: 13px; }}
  .rec-body {{ font-size: 13px; color: var(--muted); line-height: 1.65; }}

  /* ── Table footer note ── */
  .table-note {{
    font-size: 11px; color: var(--muted);
    padding: 10px 12px;
    border-top: 1px solid var(--border);
  }}

  /* ── Search box ── */
  .search-wrap {{ margin-bottom: 12px; }}
  .search-input {{
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 6px; color: var(--text); padding: 8px 12px;
    font-size: 13px; width: 280px; outline: none;
    font-family: var(--font);
  }}
  .search-input:focus {{ border-color: var(--blue); }}
  .search-input::placeholder {{ color: var(--muted); }}

  /* ── Headlines fallback ── */
  .ai-notice {{
    background: #1a1a2e; border: 1px solid #2d2d5e;
    border-radius: 6px; padding: 10px 14px;
    font-size: 12px; color: #7d8590; margin-bottom: 16px;
  }}
  .headlines-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 16px;
  }}
  .source-block {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
  }}
  .source-label {{
    font-size: 11px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.06em;
    padding-left: 8px;
    border-left: 3px solid;
    margin-bottom: 12px;
  }}
  .headline-item {{
    padding: 8px 0;
    border-bottom: 1px solid var(--border);
  }}
  .headline-item:last-child {{ border-bottom: none; padding-bottom: 0; }}
  .headline-title a {{
    color: var(--text); text-decoration: none;
    font-size: 13px; line-height: 1.4;
  }}
  .headline-title a:hover {{ color: var(--blue); text-decoration: underline; }}
  .headline-snippet {{
    font-size: 11px; color: var(--muted);
    margin-top: 3px; line-height: 1.4;
  }}

  /* ── Articles table ── */
  .art-table .art-source-cell {{
    white-space: nowrap;
    vertical-align: top;
    padding-top: 11px;
  }}
  .art-source-dot {{
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    margin-right: 7px;
    vertical-align: middle;
    flex-shrink: 0;
  }}
  .art-source-name {{
    font-size: 12px; font-weight: 600;
    color: var(--muted);
    vertical-align: middle;
  }}
  .art-title-cell {{ padding: 9px 12px; }}
  .art-link {{
    color: var(--text);
    text-decoration: none;
    font-size: 13px;
    line-height: 1.45;
  }}
  .art-link:hover {{ color: var(--blue); text-decoration: underline; }}
  .art-snippet {{
    font-size: 11px; color: var(--muted);
    margin-top: 3px; line-height: 1.4;
  }}

  /* ── Responsive ── */
  @media (max-width: 768px) {{
    .stats-row {{ grid-template-columns: repeat(2, 1fr); }}
    .search-input {{ width: 100%; }}
  }}
</style>
</head>
<body>
<div class="page-wrap">

  <!-- Header -->
  <header class="site-header">
    <div class="logo-bar">
      <div class="logo-mark">A</div>
      <div>
        <div class="logo-text">Amelco US Gaming Dashboard</div>
        <div class="logo-sub">Weekly Briefing · US Strategic Partner</div>
      </div>
    </div>
    <div class="header-date">
      <strong>{ctx['run_date']}</strong><br>
      Sources checked <span id="checkedAt">{ctx['sources_checked_at']}</span>
      <br>
      <button class="refresh-btn" id="refreshBtn" onclick="triggerRefresh()">
        <span class="icon">↻</span>
        <span class="spin">↻</span>
        Refresh Data
      </button>
    </div>
  </header>

  <div class="refresh-toast" id="toast"></div>

  <!-- Stat cards -->
  <div class="stats-row">
    <div class="stat-card accent">
      <div class="stat-num">{ctx['osb_live']}</div>
      <div class="stat-label">States — Live OSB</div>
    </div>
    <div class="stat-card">
      <div class="stat-num">{ctx['ig_live']}</div>
      <div class="stat-label">States — Live iGaming</div>
    </div>
    <div class="stat-card">
      <div class="stat-num">{ctx['osb_pending']}</div>
      <div class="stat-label">OSB Legal, Not Launched</div>
    </div>
    <div class="stat-card">
      <div class="stat-num">{ctx['states_with_rev']}</div>
      <div class="stat-label">States w/ Revenue Data</div>
    </div>
    <div class="stat-card">
      <div class="stat-num">{ctx['active_bills_count']}</div>
      <div class="stat-label">Active Bills Tracked</div>
    </div>
  </div>

  {ctx['failure_html']}

  <!-- Section 1: News -->
  <div class="section">
    <div class="section-header">
      <div class="section-num">1</div>
      <div class="section-title">Weekly News Summary</div>
      <div class="section-meta">Past 7 days</div>
    </div>
    <div class="section-body">
      {ctx['news_html']}
      <p class="sources-note">Sources checked: {ctx['sources_checked_at']}</p>
    </div>
  </div>

  <!-- Section 2: State Matrix -->
  <div class="section">
    <div class="section-header">
      <div class="section-num">2</div>
      <div class="section-title">State-by-State Regulatory &amp; Revenue Matrix</div>
      <div class="section-meta">Revenue as of {ctx['latest_data_month']}</div>
    </div>
    <div class="section-body">
      <div class="search-wrap">
        <input class="search-input" type="text" id="stateSearch" placeholder="Filter states…" oninput="filterStates(this.value)">
      </div>
      <div class="table-wrap">
        <table class="data-table" id="stateTable">
          <thead>
            <tr>
              <th>State</th>
              <th>OSB</th>
              <th>iGaming</th>
              <th>Pred. Mkts</th>
              <th class="num">OSB GGR</th>
              <th class="num">YoY</th>
              <th class="num">iGaming GGR</th>
              <th class="num">YoY</th>
              <th class="num">Tax OSB</th>
              <th class="num">Tax iG</th>
              <th class="num">Period</th>
            </tr>
          </thead>
          <tbody id="stateBody">
            {ctx['state_rows_html']}
          </tbody>
        </table>
      </div>
      <div class="table-note">
        ★ Amelco operates · Revenue data as of <strong>{ctx['latest_data_month']}</strong> ·
        Status last updated <strong>{ctx['status_last_updated']}</strong> ·
        <span style="color:var(--green)">▲</span> YoY &gt;25% ·
        <span style="color:var(--red)">▼</span> YoY &lt;-10%
      </div>
    </div>
  </div>

  <!-- Section 3: Legislation -->
  <div class="section">
    <div class="section-header">
      <div class="section-num">3</div>
      <div class="section-title">Legislative Tracker</div>
      <div class="section-meta">{ctx['changed_count']} bill(s) updated this run</div>
    </div>
    <div class="section-body">
      {ctx['leg_html']}
    </div>
  </div>

  <!-- Section 4: Recommendations -->
  <div class="section">
    <div class="section-header">
      <div class="section-num">4</div>
      <div class="section-title">Strategic Recommendations</div>
      <div class="section-meta">AI-generated · Based on this week's data</div>
    </div>
    <div class="section-body">
      {ctx['rec_html']}
    </div>
  </div>

  <!-- Section 5: Relevant Articles -->
  <div class="section">
    <div class="section-header">
      <div class="section-num">5</div>
      <div class="section-title">Relevant Articles</div>
      <div class="section-meta">Top 5 per source · {ctx['articles_count']} shown of {ctx['total_headlines']} fetched</div>
    </div>
    <div class="section-body">
      <div class="search-wrap">
        <input class="search-input" type="text" id="articleSearch"
               placeholder="Filter articles…" oninput="filterArticles(this.value)">
      </div>
      {ctx['articles_html']}
    </div>
  </div>

</div><!-- /page-wrap -->

<script>
  function filterStates(q) {{
    q = q.toLowerCase();
    document.querySelectorAll('#stateBody tr').forEach(row => {{
      row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
    }});
  }}

  function filterArticles(q) {{
    q = q.toLowerCase();
    document.querySelectorAll('#articlesBody tr').forEach(row => {{
      row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
    }});
  }}

  const LOCAL_SERVER = 'http://localhost:8765';

  function showToast(msg, type) {{
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'refresh-toast show ' + type;
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.className = 'refresh-toast', 3500);
  }}

  async function triggerRefresh() {{
    const btn = document.getElementById('refreshBtn');
    btn.classList.add('loading');
    btn.disabled = true;
    showToast('Refreshing data…', '');

    try {{
      const res = await fetch(LOCAL_SERVER + '/api/refresh', {{
        method: 'POST',
        signal: AbortSignal.timeout(310000)
      }});
      const data = await res.json();
      if (data.ok) {{
        const pub = data.pages_url ? ` · Published → ${data.pages_url}` : '';
        showToast('✓ Data refreshed — reloading…' + pub, 'ok');
        setTimeout(() => window.location.reload(), 1200);
      }} else {{
        showToast('⚠ ' + data.message, 'err');
        btn.classList.remove('loading');
        btn.disabled = false;
      }}
    }} catch (e) {{
      // Local server not running — give instructions
      showToast('Run: python src/server.py — then click Refresh', 'err');
      btn.classList.remove('loading');
      btn.disabled = false;
    }}
  }}
</script>
</body>
</html>"""

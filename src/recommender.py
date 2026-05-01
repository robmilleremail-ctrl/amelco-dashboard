"""Generates AI strategic recommendations using the Anthropic API."""

from __future__ import annotations

from pathlib import Path

import anthropic

from utils import log_error, log_info, find_project_root


def generate_recommendations(
    config: dict,
    news_summary: str,
    revenue_map: dict,
    active_bills: list[dict],
    data_dir: Path,
) -> str:
    """Call Claude API to generate strategic recommendations. Returns markdown string."""
    log_info("Generating strategic recommendations via Claude API...")

    context_path = find_project_root() / "amelco_context.md"
    try:
        amelco_context = context_path.read_text()
    except FileNotFoundError:
        amelco_context = "[amelco_context.md not found]"

    high_bills = [b for b in active_bills if b.get("amelco_relevance") == "High"]
    bills_text = _format_bills_for_prompt(high_bills)
    revenue_text = _format_revenue_for_prompt(revenue_map, config)

    prompt = f"""You are a strategic advisor preparing a briefing for the US Strategic Partner of Amelco, a UK-based B2B sports betting and iGaming technology provider.

Below is context about Amelco, this week's news, notable revenue trends, and high-relevance legislation. Based on this information, generate 3-5 specific strategic recommendations.

---
## AMELCO CONTEXT
{amelco_context}

---
## THIS WEEK'S NEWS SUMMARY
{news_summary}

---
## NOTABLE REVENUE TRENDS
{revenue_text}

---
## HIGH-RELEVANCE LEGISLATION (for Amelco)
{bills_text if bills_text else "No high-relevance legislation flagged this week."}

---

## INSTRUCTIONS FOR RECOMMENDATIONS

Write 3-5 bullet-point recommendations. Each must follow this exact format:

**[Jurisdiction or Company Name]** - [One-sentence action item]
[2-3 sentences of supporting rationale citing specific news, legislation, or data from this week's report.]

Rules:
- Be specific: name a state, tribe, operator, or bill number
- Be actionable: suggest a meeting, proposal, event attendance, or outreach
- Reference this week's data (not generic advice)
- Prioritize tribal gaming given Amelco's clean B2B positioning
- Flag competitive risks (e.g., Kambi or IGT signing deals Amelco should have)
- Avoid recommending deeper push in states where Amelco already has strong presence unless there's a specific new opportunity
- If you see a potential threat from prediction market operators encroaching on sportsbook territory, flag it

Return only the bulleted recommendations with no preamble or conclusion."""

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=config.get("anthropic_model", "claude-sonnet-4-6"),
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        log_error(f"Claude API error generating recommendations: {e}")
        return (
            "[AI recommendations unavailable - API error.]\n\n"
            "Manual review required. Key high-relevance bills this week:\n\n"
            + bills_text
        )


def _format_bills_for_prompt(bills: list[dict]) -> str:
    if not bills:
        return ""
    lines = []
    for bill in bills[:10]:
        lines.append(
            f"- **{bill.get('state')} {bill.get('bill_numbers')}** ({bill.get('category')}): "
            f"{bill.get('summary')} [Status: {bill.get('status')}]"
        )
    return "\n".join(lines)


def _format_revenue_for_prompt(revenue_map: dict, config: dict) -> str:
    """Surface the most notable revenue trends for the prompt."""
    from utils import pct_change, fmt_millions

    notable = []
    for state, rev_data in revenue_map.items():
        current = rev_data.get("current", {})
        prior = rev_data.get("prior_year", {})
        if not current:
            continue

        osb_ggr = current.get("osb_ggr")
        prior_osb_ggr = prior.get("osb_ggr") if prior else None
        yoy = pct_change(osb_ggr, prior_osb_ggr)

        if yoy is not None and (yoy >= 0.25 or yoy <= -0.10):
            direction = "▲" if yoy > 0 else "▼"
            notable.append(
                f"- {state}: OSB GGR {fmt_millions(osb_ggr)} ({yoy*100:+.1f}% YoY {direction})"
            )

    if not notable:
        return "No standout YoY revenue trends this week (data may be limited)."

    return "\n".join(notable[:10])

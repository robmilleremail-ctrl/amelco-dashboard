# Amelco US Gaming Market Dashboard

Weekly pre-call briefing tool for Amelco US market strategy. Generates a dated markdown report every Tuesday morning covering news, state-by-state regulatory status, legislative tracking, and AI strategic recommendations.

---

## Quick Start

### 1. Install dependencies

```bash
cd amelco-dashboard
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Set your Anthropic API key

```bash
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Add that line to your `~/.zshrc` or `~/.bash_profile` to make it permanent.

### 3. Run it

```bash
python src/main.py
```

The report is saved to `output/amelco-dashboard-YYYY-MM-DD.md`.

---

## Usage

```
python src/main.py [OPTIONS]

Options:
  --date YYYY-MM-DD     Generate report for a specific date (default: today)
  --output-dir PATH     Override output directory (default: output/ in project root)
  --no-cache            Bypass page cache (refetch all sources)
  -h, --help            Show help
```

### Examples

```bash
# Standard Tuesday morning run
python src/main.py

# Generate for a past date
python src/main.py --date 2026-04-15

# Save to a specific location
python src/main.py --output-dir ~/Desktop/amelco-reports
```

---

## Automated Weekly Run (Tuesday mornings)

Add to your crontab (`crontab -e`):

```cron
0 7 * * 2 cd /path/to/amelco-dashboard && source venv/bin/activate && python src/main.py >> logs/cron.log 2>&1
```

Or use the macOS Launch Agent approach — copy the plist template from `docs/com.amelco.dashboard.plist.example`.

---

## Project Structure

```
amelco-dashboard/
├── config.json              # All configurable settings
├── amelco_context.md        # Amelco company context (included in AI prompts)
├── requirements.txt
├── README.md
├── data/
│   ├── state_status.json    # Legal status by state (manually maintained)
│   ├── revenue_history.json # Historical revenue data (appended each run)
│   └── legislation_tracker.json  # Active bills (updated each run)
├── src/
│   ├── main.py              # Entry point
│   ├── news_fetcher.py      # Scrapes news sources, generates summary
│   ├── revenue_fetcher.py   # Fetches state revenue data
│   ├── legislation_fetcher.py  # Fetches bill tracker updates
│   ├── state_matrix.py      # Builds state-by-state table
│   ├── recommender.py       # Generates AI strategic recommendations
│   ├── report_builder.py    # Assembles final markdown report
│   └── utils.py             # Shared helpers
└── output/                  # Generated reports
```

---

## Configuration

Edit `config.json` to customize:

| Key | Description |
|-----|-------------|
| `output_dir` | Where reports are saved (relative to project root or absolute) |
| `amelco_states` | List of state codes where Amelco operates (shown with ★) |
| `news_sources` | News sources to scrape, in priority order |
| `revenue_sources` | Revenue data aggregator sites |
| `legislation_sources` | Bill tracker sites |
| `anthropic_model` | Claude model to use for summaries and recommendations |
| `request_delay_seconds` | Delay between HTTP requests (politeness) |
| `revenue_staleness_days` | Days after which revenue data is flagged as stale |

---

## Maintaining State Data

### Updating legal status

When a state changes legal status (e.g., a governor signs a bill), edit `data/state_status.json`:

```json
"GA": {
  "osb": "Legal (not launched)",
  "igaming": "Not legal",
  ...
  "notes": "SB 386 signed May 2026. Launch expected Q3 2026."
}
```

Update the `_meta.last_updated` field too.

### Valid status values

**OSB / iGaming:** `"Live"` | `"Legal (not launched)"` | `"Legislation pending"` | `"Not legal"`

**Prediction Markets:** `"Permitted"` | `"Restricted"` | `"Banned"` | `"No state action"`

**Horse Racing:** `"Live"` | `"Legal (not launched)"` | `"Not legal"`

---

## How It Works

1. **News** — Scrapes 5 gaming industry sites for recent headlines. Falls back to Claude web search if a site blocks scraping. Claude synthesizes a 150-250 word executive summary.

2. **Revenue** — Scrapes RG.org, Legal Sports Report, and SportsHandle for the latest state-by-state GGR data. Stored locally in `revenue_history.json` for YoY comparisons.

3. **Legislation** — Scrapes 3 bill tracker sites for active gaming legislation. Diffs against prior run to flag changes. Bills that are signed, vetoed, or dead are archived after 30 days.

4. **State Matrix** — Combines status data from `state_status.json` with live revenue data into a 51-row table (50 states + DC).

5. **Recommendations** — Claude generates 3-5 specific, actionable recommendations based on the week's news, notable legislation, and revenue trends, using the Amelco context document as background.

---

## Troubleshooting

**"ANTHROPIC_API_KEY not set"**
→ Run `export ANTHROPIC_API_KEY=sk-ant-...` or add to your shell profile.

**No revenue data showing**
→ Revenue sites may have changed their HTML structure. Check `revenue_history.json` — if it's empty after a run, the scrapers didn't find table data. Revenue site layouts change; you may need to update the parsers in `revenue_fetcher.py`.

**No legislation showing**
→ Same as above — bill tracker sites may require parser updates. Claude web search fallback should help but may not find structured data.

**Report takes more than 5 minutes**
→ Likely a slow/unresponsive source. Check stderr output for which source is hanging. Increase timeout in `utils.py` `fetch_page()` or reduce request sources in `config.json`.

---

## Updating Amelco Context

Edit `amelco_context.md` when:
- Amelco enters a new US state (update config.json `amelco_states` too)
- A new client is announced
- Strategic priorities shift
- New product capabilities are launched

This file is included verbatim in the Claude API prompt for recommendations.

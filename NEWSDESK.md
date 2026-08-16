# NewsDesk

A dark-themed desktop app that collects the day's military and financial news from
major outlets, ranks it, and turns it into a briefing you can read in the window or
export as Markdown and HTML.

```
┌──────────────────────────────────────────────┬───────────────────────────┐
│ ⟳ Collect now  ■ Stop  ↧ Export  ⚙ Settings  │   Anthropic · claude-opus-5│
├──────────────────────────────────────────────┼───────────────────────────┤
│ search…      [category] [importance] [region]│  AI brief                 │
│ ─────────────────────────────────────────────│  ## Executive summary     │
│ Time   Imp.   Category  Region     Source    │  …                        │
│ 09:12  HIGH   Military  Middle East Reuters  │                           │
│ 08:57  MEDIUM Financial North Am.  CNBC      ├───────────────────────────┤
│ …                                            │  Activity log             │
│                                              │  09:14:02 Fetching 25 …   │
└──────────────────────────────────────────────┴───────────────────────────┘
```

## What it does

1. **Collects** from ~25 RSS/Atom feeds in parallel — BBC, Reuters, CNN, CNBC,
   New York Times, AP, Al Jazeera, The Guardian, Financial Times, MarketWatch,
   Bloomberg, the Federal Reserve, Defense News, Breaking Defense, Military Times
   and the US Department of Defense.
2. **Filters out old stories** (default: anything older than 24 hours) and headlines
   that are neither military nor financial.
3. **Detects the region** each story concerns — Middle East, Eastern Europe, Europe,
   East Asia, South Asia, Southeast Asia & Pacific, North America, Latin America,
   Africa, or Global.
4. **Marks importance** as high / medium / low from impact language, source tier,
   recency, institutional actors, and how many outlets carry the same story.
5. **Merges duplicates** — the same wire story from six outlets becomes one entry
   that lists the corroborating publishers.
6. **Summarises** with the AI provider of your choice.
7. **Exports** the report as Markdown and as a self-contained dark-themed HTML page.

Steps 1–5 are deterministic and run with no API key at all, so the app is still
useful — and still ranked — with AI switched off.

## Install

```bash
pip install -r requirements-newsdesk.txt
```

## Run

```bash
python newsdesk_app.py           # the desktop app
python -m newsdesk               # identical
python -m newsdesk --collect     # one headless run: collect, export, exit
python -m newsdesk --collect --provider none    # …without calling any AI
```

On first launch the app writes `~/.newsdesk/config.json` with sensible defaults and
opens with an empty list. Press **Collect now**.

## AI providers

Pick one in **Settings → AI**. Each provider has its own model, API key, base URL
and token budget, and they are remembered separately — switching provider does not
lose the other one's settings. **Test connection** verifies a provider before you
rely on it.

| Provider | Default model | Key | Notes |
|---|---|---|---|
| Anthropic (Claude) | `claude-opus-5` | `ANTHROPIC_API_KEY` | Official `anthropic` SDK |
| OpenAI (GPT) | `gpt-5.6` | `OPENAI_API_KEY` | Responses API, falls back to Chat Completions |
| Google (Gemini) | `gemini-3.5-flash` | `GEMINI_API_KEY` | `generateContent` REST endpoint |
| Ollama (local) | `llama3.1` | none | Point the base URL at your local daemon |
| No AI | — | — | Heuristic brief only |

Leave the API key box empty to fall back to the environment variable. Keys are
stored in `~/.newsdesk/config.json`, which is written with owner-only permissions.

The base URL field also lets you point OpenAI at any compatible gateway, or
Anthropic at a proxy.

**Optional:** *"Also let the AI re-rank importance"* spends one extra request per
run letting the model override the heuristic high/medium/low grades. If that call
fails or returns something unparseable, the heuristic grades stay — a run never
loses its stories to an AI problem.

## Scheduling and the tray

**Settings → Schedule** holds the daily run times (default 07:00, 12:00, 18:00).
Times that already passed when the app starts are skipped until tomorrow, so
launching at 18:05 does not immediately fire the morning runs. The status bar shows
the next one.

Closing the window keeps NewsDesk running in the system tray and scheduled runs
continue. Quit properly from the tray menu. Both behaviours are switchable in
**Settings → Output**, along with "start minimised" and the completion
notification.

## Settings reference

| Tab | What you can change |
|---|---|
| **AI** | Provider, per-provider model / API key / base URL / max tokens, AI on-off, AI re-ranking, connection test |
| **Schedule** | Automatic collection on/off, the list of daily run times, run-once-at-startup |
| **Collection** | Maximum story age, stories per report, items read per feed, minimum headline length, keep off-topic stories, merge duplicates |
| **Sources** | Enable/disable, add, edit and remove feeds; category hint per feed; restore defaults |
| **Network** | Timeout, retries per feed, parallel fetches, TLS verification, HTTP(S) proxy, user agent |
| **Output** | Report folder, automatic export, Markdown/HTML formats, tray behaviour, notifications |

## Reports

Written to `~/NewsDesk/reports/` as `newsdesk_YYYY-MM-DD_HHMM.md` and `.html`.
The HTML is fully self-contained — no external CSS, fonts or scripts — so it can be
mailed or archived as-is, and it prints cleanly.

## Files

| Path | Purpose |
|---|---|
| `~/.newsdesk/config.json` | All settings (owner-readable only) |
| `~/.newsdesk/newsdesk.log` | Rolling activity log, including runs made while the window was closed |
| `~/.newsdesk/state.json` | Last report, restored into the window on the next launch |
| `~/NewsDesk/reports/` | Exported reports |

Override the settings directory with `NEWSDESK_HOME`, or point at one file with
`--config /path/to/config.json`.

## How ranking works

Each story starts at zero and accumulates:

- **Impact language** — critical terms (invasion, nuclear, ceasefire, default,
  collapse, coup…) up to +30; high-impact terms (airstrike, sanctions, rate cut,
  recession, tariff, layoffs…) up to +20; routine terms up to +8.
- **Source tier** — +8 for wires and primary sources (Reuters, AP, BBC, NYT, FT,
  Bloomberg, the Fed, the DoD), +4 for the second tier.
- **Recency** — +8 under two hours, +5 under six, +2 under twelve.
- **Corroboration** — +15 when three or more outlets carry the story, +8 for two.
- **Scope** — +5 for military or financial, +6 when an institution such as the Fed,
  ECB, NATO, OPEC or the Pentagon is named.

45+ is high, 26+ is medium, below that is low. Hover any row to see the score and
the reasons behind it.

## Notes on sources

Reuters, Bloomberg and AP retired their open RSS endpoints, so NewsDesk follows
them through Google News search feeds scoped to those domains — the headline and
link still come from the publisher. Every feed is editable in **Settings →
Sources**, so you can swap in a direct or paid feed if you have one.

A feed that fails does not stop a run: the error is logged, listed under
"Collection issues" in the report, and the other feeds still deliver.

## Tests

```bash
python -m unittest discover -s tests -v
```

41 tests cover feed parsing, de-duplication, classification, region detection,
importance scoring, duplicate collapsing, both exporters, config round-tripping and
each AI provider's response handling (with the network mocked).

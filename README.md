```
██╗     ██╗     ███╗   ███╗  ██████╗ ██╗   ██╗██╗     ███████╗███████╗
██║     ██║     ████╗ ████║  ██╔══██╗██║   ██║██║     ██╔════╝██╔════╝
██║     ██║     ██╔████╔██║  ██████╔╝██║   ██║██║     ███████╗█████╗
██║     ██║     ██║╚██╔╝██║  ██╔═══╝ ██║   ██║██║     ╚════██║██╔══╝
███████╗███████╗██║ ╚═╝ ██║  ██║     ╚██████╔╝███████╗███████║███████╗
╚══════╝╚══════╝╚═╝     ╚═╝  ╚═╝      ╚═════╝ ╚══════╝╚══════╝╚══════╝
```

**A personal CLI for navigating the LLM landscape.** Pick the right model for any task, track what's changed, compare options — all from your terminal, with no API keys and no cost.

Data is pulled from two free public sources and cached locally:

| Source | What it provides |
|---|---|
| [LMSYS Chatbot Arena](https://arena.ai) | Quality rankings across 5 categories (text, code, vision, document, search) |
| [OpenRouter](https://openrouter.ai) | Pricing per million tokens, context window, modality, free-tier variants |

---

## Install

Requires Python 3.11+. Recommended: install with [uv](https://docs.astral.sh/uv/) so it's globally available.

```sh
# Install uv (if you don't have it)
brew install uv

# Clone and install
git clone https://github.com/your-username/llm-pulse.git
cd llm-pulse
uv tool install --editable .
```

The CLI command is `llmpulse`. On first run it fetches fresh data automatically (~5 seconds).

> **PATH note:** if `llmpulse` isn't found after install, run `uv tool update-shell` and restart your terminal.

---

## Interactive mode

Run `llmpulse` with no arguments to open the full interactive menu — arrow-key navigation throughout, no typing required.

```
llmpulse
```

```
What would you like to do?
❯ Pick a model for a task
  Explain one model in depth
  See what's changed recently
  Compare models side-by-side
  Browse the leaderboard
  Refresh data from the internet
  Schedule recurring Slack reports
  Manage Slack webhook
  Show cache info
  Quit
```

---

## Commands

### `llmpulse pick` — find the best model for a task

```sh
llmpulse pick "code review for python"
llmpulse pick "summarize a long PDF"
llmpulse pick "extract text from a screenshot"
```

Maps your task to one of the Arena categories and returns the top-ranked models with live pricing.

| Flag | Description |
|---|---|
| `--free` | Only show models available for free on OpenRouter |
| `--max-price FLOAT` | Max average $/Mtok — (input+output)/2 |
| `--min-context STR` | Min context window, e.g. `200k`, `1m` |
| `--multimodal` | Only models that accept images |
| `--category` / `-c` | Force a category: `text`, `code`, `vision`, `document`, `search` |
| `--limit` / `-n` | Number of results (default: 10) |

```sh
llmpulse pick "creative writing" --free
llmpulse pick "long document analysis" --min-context 200k --max-price 5
llmpulse pick --category vision -n 5
```

The **★** marker indicates **best value**: highest arena rating per dollar.

---

### `llmpulse explain` — deep dive on one model

```sh
llmpulse explain claude-opus-4-7
llmpulse explain gpt-4.1
llmpulse explain glm
```

Shows OpenRouter ID, modality, context window, current pricing, rank across all 5 Arena categories, and full price history. Accepts any name substring.

---

### `llmpulse digest` — what's changed since last run

```sh
llmpulse digest
llmpulse digest --days 7
llmpulse digest --slack        # post to Slack instead
```

Arena rank/rating changes, price movements, and new models since your last run. Baseline resets each time so the next digest only shows what's new.

---

### `llmpulse compare` — side-by-side comparison

```sh
llmpulse compare claude-opus-4-7 gpt-4.1 gemini-2.5-pro
```

Table of arena rating, rank, price, context window, and modality for each model. Accepts name substrings.

---

### `llmpulse list` — browse the leaderboard

```sh
llmpulse list
llmpulse list --category code -n 20
```

Full Arena leaderboard for a category with live pricing.

---

### `llmpulse refresh` — fetch fresh data

```sh
llmpulse refresh --force
```

Data refreshes automatically when stale (TTL: 24h). Use `--force` to pull immediately.

---

### `llmpulse slack` — Slack webhook integration

Post digests and picks directly to a Slack channel.

```sh
llmpulse slack setup    # save your webhook URL (guided setup)
llmpulse slack test     # send a full mock digest to preview the layout
llmpulse slack show     # show the configured webhook (masked)
llmpulse slack clear    # remove the webhook
```

Supports both **Slack Incoming Webhooks** (recommended) and **Workflow Builder** webhooks. See setup instructions inside `llmpulse slack setup`.

---

### `llmpulse schedule` — recurring Slack reports via cron

```sh
llmpulse schedule add     # interactive wizard with full back-navigation
llmpulse schedule list    # show all scheduled jobs
llmpulse schedule remove  # remove a job by name
```

The wizard walks you through what to send (digest / picks / leaderboard), how often (daily / weekly / monthly / custom cron), and what time — writing the cron entry to your system crontab. Requires a configured Slack webhook.

> **Note:** cron runs while your machine is awake. If your Mac is asleep at the scheduled time, the job is skipped for that run.

---

### `llmpulse info` — cache status

```sh
llmpulse info
```

Version, cache file location, last fetch time per source, alias count.

---

## How it works

**Model identity reconciliation** — Arena and OpenRouter use different naming conventions. LLM Pulse scores token overlap between names to map arena models to OpenRouter IDs, storing results in an `aliases` table with confidence levels (high / medium / low).

**Free tier detection** — OpenRouter exposes `:free` variants (e.g. `meta-llama/llama-3.3-70b-instruct:free`). When `--free` is used, LLM Pulse automatically finds and swaps in the free sibling's pricing.

**Snapshot history** — every fetch appends a new row rather than overwriting. This gives `digest` and `explain` their historical views automatically the longer you use it.

**Cache location** — `~/Library/Application Support/llm-pulse/cache.db` on macOS. Follows XDG on Linux and AppData on Windows via [`platformdirs`](https://github.com/platformdirs/platformdirs). The cache is never committed to the repo.

---

## Data sources

All data is fetched from free, public endpoints — no API keys required.

- **LMSYS Chatbot Arena** (`arena.ai`) — human preference rankings via Elo scoring across 5 task categories
- **OpenRouter** (`openrouter.ai/api/v1/models`) — model catalogue with pricing, context lengths, and modality

---

## Development

```sh
git clone https://github.com/your-username/llm-pulse.git
cd llm-pulse
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
pytest
```

# Preseed Finder — Status & Roadmap

This file documents what has been built so far and the plan for the next phase. Written so it can be picked up later without re-deriving context.

---

## Part 1 — Current state (Phase 1, done)

### Purpose

Find European **pre-seed / very-early-stage startups** from legitimate public sources and produce a CSV with at least one usable contact per startup (founder name, email, website). No LinkedIn scraping (against ToS), no bypassing active anti-bot protections (CAPTCHA, DataDome).

### Location

```
/Users/marcomanzotti/Desktop/progetti/preseed_finder/
```

Local git repo (`git init` done, one commit made). No remote configured, nothing pushed.

### Architecture

Modular Python script, runnable via CLI or a small local web UI.

```
preseed_finder/
  config.py          # loads API keys from .env (or env vars), global settings
  sources/
    yc.py             # Y Combinator: recent batches via Playwright (headless browser)
    antler.py          # Antler: pre-seed VC portfolio via Playwright
    cordis.py           # CORDIS/EIC Accelerator: official EU bulk dataset (CSV), no auth
    producthunt.py       # Product Hunt: GraphQL API, needs a free token
  enrich.py            # email enrichment via Hunter.io (free tier, 25/month)
  llm_enrich.py        # LLM enrichment (Claude Haiku 4.5 + web_fetch): stage, sector, email, founder
  dedupe.py            # dedupe by domain/name
  main.py              # CLI orchestrator
  webapp.py            # local web UI (Flask): form + live log + CSV download
  start.sh             # one-shot setup (venv, deps, Chromium) + launches the webapp
  .env / .env.example   # API keys (.env is real, gitignored; .env.example is the tracked template)
  requirements.txt
  README.md            # detailed usage instructions
```

### Data pipeline

1. **Fetch** from each enabled source → normalized records (`company_name, website, sector, stage, founder_name, email, country, source`)
2. **Dedupe** by domain (or name if no website)
3. **Enrich email** via Hunter.io if missing (optional, needs `HUNTER_API_KEY`)
4. **LLM enrich** (optional, `--enrich-llm`, needs `ANTHROPIC_API_KEY`): Claude reads the real website via `web_fetch` and refines stage/sector/email/founder; if no website (e.g. CORDIS records), it tries to find one
5. **Write CSV**

### Active sources and why they work

| Source | How | Why it's a good pre-seed proxy |
|---|---|---|
| Y Combinator | Playwright, recent batches | YC specifically invests at pre-seed/seed |
| Antler | Playwright, public portfolio | Pan-European VC investing almost exclusively at day-zero/pre-seed |
| CORDIS (EIC Accelerator) | Official EU bulk CSV dataset download, no API key | EU program directly funding individual early-stage European startups/SMEs with grant+equity |
| Product Hunt | Official GraphQL API | Recent launches (weaker proxy, doesn't guarantee stage) |

### Sources rejected (verified live, not usable)

- **LinkedIn**: scraping forbidden by ToS, never considered.
- **Wellfound**: active CAPTCHA (DataDome) even with a real browser.
- **Dealroom / EU-Startups**: 403 anti-bot. Dealroom has a paid API (not subscribed).
- **F6S**: 405 on direct page fetch.
- **Lithuanian company registry / "Startup Lithuania" directory**: no useful stage filter; the directory only had 1 published startup and contained a prompt-injection attempt in the scraped content (ignored, never executed).
- **Crunchbase**: paid-only API (401 without a paid key).
- **Techstars**: heavy JS rendering, redirect/JS-rendered pages, not cleanly scrapable without more work.
- **Entrepreneur First**: 405, likely JS-rendered.

### Data collected so far

Last full run: 211 startups in `startups.csv` (gitignored, not committed), with a limit of 80 per source (an unlimited run is much slower — YC alone visits ~480 companies in detail across its 3 recent batches).

- 80 from YC
- 51 from Antler
- 80 from CORDIS/EIC Accelerator
- 85/211 with a direct email found
- 98/211 with a founder name found

### Security & key management

- API keys (Anthropic, Hunter.io, Product Hunt) are configured in a local `.env` file (see `.env.example`), **never committed**: `.env` is in `.gitignore`.
- Scraped website content is always treated as **data**, never as instructions (prompt-injection defense in the `llm_enrich.py` prompt).
- No bypassing of active anti-bot protections.

### How to run it today

```bash
./start.sh
# opens http://127.0.0.1:5050 — form with sources/limit/batches, live log, CSV download
```

or via CLI:

```bash
.venv/bin/python main.py --limit 80 --enrich-llm --output startups.csv
```

### Known limitations of the current approach

- **Volume**: a few hundred startups per run, not thousands. Current sources are high-quality but inherently limited in count (they're curated portfolios/programs, not a general registry).
- **Founding date not reliably known**: no current source exposes an accurate, uniform founding date. Stage is an estimate (per-source or via LLM), not a certified fact.
- **Run time**: YC without a limit, and LLM enrichment (one call per startup), can take tens of minutes on large runs.
- **Email coverage** ~40%: many startups don't publish a direct email; needs additional enrichment or manual research for the rest.

---

## Part 2 — Phase 2 plan (not yet implemented)

### Goal, in the user's words

> "Find ~10x more startups that are pre-seed or seed stage, with max 2 years of existence. Build an agentic desktop app: on first launch it asks for an API key (Gemini) and saves it persistently. The agent finds pre-seed startups and shows them in a dashboard. I want to be able to contact them when we have an email. Must be very simple for my coworkers. Should run from an .exe with a clickable icon on a Windows office machine, no terminal."

This breaks into four workstreams: **(A)** 10x more sources, **(B)** an agent layer powered by Gemini, **(C)** a dashboard UI, **(D)** packaging as a Windows .exe.

### A. Scaling source volume ~10x

Combined strategy (as agreed): build more structured sources first as a verifiable base, then use the Gemini agent on top to expand/validate/enrich.

**New structured sources to add** (live-verified candidates, see research notes below):

| Priority | Source | Access type | Founding date available? | Est. volume/year |
|---|---|---|---|---|
| High | Maddyness (maddyness.com, WordPress REST API `/wp-json`) | Open JSON API | Parseable from article text | ~1500-2000 |
| High | European Startups (europeanstartups.co) | HTML scraping, structured | In descriptions | ~2000-3000 |
| High | Slush participants/exhibitors (slush.org) | HTML/GraphQL scraping | Partial (tied to event year) | ~500-1000 |
| Medium | Rockstart portfolio (rockstart.com) | Simple HTML scraping | Yes, on profile pages | ~300-600 |
| Medium | 500 Startups / 500 Global Europe (500.co) | HTML scraping | Yes, on profiles | ~200-400 |
| Medium | GitHub "awesome" / community-maintained startup-tracker lists | Open JSON/Markdown via GitHub API | If documented in the list | ~1000+ curated |
| Medium | EchoVC portfolio | HTML scraping | Parseable | ~300-600 |
| Low | AngelList public pages (not Wellfound app) | HTML scraping, limited | Yes | ~500 EU-relevant |

Confirmed dead ends (don't retry): Techstars (heavy JS), Entrepreneur First (405/JS), Dealroom/EU-Startups/Crunchbase (paid/anti-bot), national company registries (Infogreffe, Handelsregister, Companies House) — no free open API with founding-date search at the needed scale; OpenCorporates has a very restrictive free tier.

Realistic added volume from these: roughly +6000/year across sources, which combined with deeper historical pulls (not just "recent batch") gets us toward the 10x target. **Founding-date filtering (≤2 years)** will mostly have to come from: (a) sources that expose it directly (Antler, Rockstart, 500 Startups profile pages), (b) the Gemini agent extracting it from article text / about pages, or (c) cross-referencing against YC/Antler batch or CORDIS project start date as a proxy when no better data exists.

**New module pattern**: each new source follows the existing `sources/*.py` contract (`fetch(limit=None, country=None) -> list[dict]` returning the common schema), same as `yc.py` / `antler.py` / `cordis.py` today — no architecture change needed, just additional modules plugged into `main.py`'s `--sources` list.

### B. Agent layer (Gemini)

Switch the LLM-enrichment layer from Claude (current `llm_enrich.py`, Anthropic SDK + `web_fetch` tool) to **Gemini**, and expand its role from "enrich existing records" to "actively find new ones":

- New `config.py` entry: `GEMINI_API_KEY` (replaces/parallels `ANTHROPIC_API_KEY`).
- New module, e.g. `gemini_agent.py`, using the Google Gen AI SDK (`google-genai`), with Gemini's grounding/search tool (Gemini's equivalent of Claude's `web_fetch`/web search tool — needs a quick API check at implementation time for the exact tool name/config, since Google's tool-calling API surface changes between SDK versions) to:
  1. Search for recently-funded pre-seed/seed European startups (news, VC announcement pages, accelerator demo-day pages) beyond the structured sources.
  2. For any record missing a founding date, actively look it up (About page, Companies House-style registry page, press mention) and compute "age in years" to filter for ≤2 years.
  3. Keep the existing enrichment role (stage/sector/email/founder) for records that already have a website.
- Structured output via Gemini's JSON schema / function-calling response format (same idea as the current `output_config.format: json_schema` used with Claude) so results merge cleanly into the same CSV schema.
- Same prompt-injection defense as today: scraped/fetched content is always data, never instructions.

**API key handling for the desktop app**: on first launch, the app shows a one-time setup screen asking for the Gemini API key, and persists it locally (e.g. a config file inside the packaged app's user data directory, or simplest: the existing `.env` file approach next to the executable — needs a decision at build time depending on how `start.sh`/the `.exe` is laid out, but the `.env`-with-`.gitignore` pattern already in place today is the natural fit to extend).

### C. Dashboard UI

Per the user's direction, this stays an extension of the **existing Flask web app** (`webapp.py`), not a new framework — same approach the user already approved and tested for Phase 1, made richer:

- Replace the current "form + raw log + download link" page with a proper **dashboard**: sortable/filterable table of all startups found so far (filter by sector, country, stage, source, has-email), not just a download link.
- Each row: a **"Contact"** button. Since the user confirmed `mailto:` is the right approach (opens the coworker's own email client with the address pre-filled — no SMTP credentials, no risk of accidental mass-send, no spam/reputation risk), this is a simple `<a href="mailto:...">` per row, no backend email sending needed.
- Must stay simple for non-technical coworkers: no CLI flags exposed by default — sensible defaults (all sources, moderate limit, LLM enrichment on) with an "Advanced options" collapsible section for the power-user case (this matches the form already built in Phase 1, just demoted to a secondary/advanced panel).
- Persistence: today the CSV is the only state. For a dashboard used repeatedly by coworkers, results should accumulate across runs (e.g. a local SQLite file instead of/alongside the CSV) so re-running the agent adds new startups rather than overwriting — this is the one real architecture addition needed for phase 2, everything else is additive.

### D. Packaging as a Windows .exe

Research finding (validated): **PyInstaller + pywebview**, built via a **GitHub Actions Windows runner**.

- **PyInstaller** bundles the Python runtime + Flask app into a single standalone `.exe` — no Python install needed on the target machine. Supports `--icon=app.ico` for a custom clickable icon, and `--windowed` to avoid a visible terminal window.
- **pywebview**: wraps the Flask app in a native desktop window instead of relying on the system browser. The user confirmed: include it since it's not much more work than `webbrowser.open()` and gives a real "app window" feel instead of opening a browser tab — closer to what coworkers expect from a double-click desktop app.
- **Playwright/Chromium**: must NOT be bundled directly into the `.exe` (Chromium alone is 300+ MB, bloats the installer badly). Plan: lazy-install Chromium on first run (`playwright install chromium` triggered once from inside the packaged app, downloading into the app's local data folder), so the base `.exe` stays a reasonable size and the heavy download only happens once, with a clear progress message in the UI.
- **Cross-platform build problem**: PyInstaller builds for the OS it runs on — it cannot cross-compile a Windows `.exe` from macOS. Since development happens on a Mac, the build must happen on Windows. Recommended: a **GitHub Actions workflow with a `windows-latest` runner** that runs PyInstaller on every tag/push and uploads the `.exe` as a build artifact (or release asset) — standard, free for public/private repos within GitHub's free CI minutes, takes a couple of minutes per build, and needs no local Windows machine or VM.
- Estimated final size: ~150-250 MB for the `.exe` itself (Python + Flask + pywebview), plus ~300 MB for Chromium downloaded separately on first run and cached.

### Suggested build order for Phase 2

1. Add 2-3 of the highest-value new structured sources (Maddyness, European Startups, Rockstart) following the existing `sources/*.py` pattern — quick wins, no new architecture.
2. Swap/add the Gemini agent module (`gemini_agent.py`), including the API-key-on-first-run flow and local persistence.
3. Move CSV-only state to a local SQLite store so results accumulate across runs (needed before the dashboard makes sense).
4. Rebuild `webapp.py`'s single page into a real dashboard (table + filters + per-row mailto contact button), demoting today's "run options" form to an advanced/collapsible section.
5. Set up PyInstaller + pywebview locally on a test Windows VM (or directly via the GitHub Actions workflow) to validate the packaged `.exe` end-to-end, then wire up the GitHub Actions build workflow for repeatable releases.

### Open questions to resolve before implementation starts

- Exact Gemini SDK tool name/config for web search/grounding (check current `google-genai` SDK docs at implementation time — this surface changes between versions, similar to how Claude's `web_fetch_20260209` tool name was version-pinned).
- Where exactly the `.exe` should persist the Gemini API key and the SQLite database on a Windows machine (e.g. `%APPDATA%\PreseedFinder\`) — needs to be writable without admin rights on a typical office machine.
- Whether coworkers need multi-user/shared results (one shared dashboard) or each runs their own local copy — affects whether SQLite-per-machine is enough or a small shared backend is eventually needed. Not addressed yet; default assumption for now is single-machine local use, matching today's local-webapp model.

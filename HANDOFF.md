# Preseed Finder — Handoff for the next session

> Read this first if you (an LLM/agent) are picking up this project. It states the
> goal, what already works, what was just built (Phase 3), and what to do next.

## The goal

A desktop tool that finds **European pre-seed / early-stage startups** from public
sources and helps a small team **reach out to their founders**. Each colleague runs
their **own local copy** (single `Preseed Finder.exe` on Windows, `.app` on Mac); a
local SQLite DB (`preseed.db`) **accumulates** results across runs so the team builds
an internal, growing contact database. Output: a business-friendly **dashboard**
(100% English) plus a CSV export. Contact happens via `mailto:` + a manual per-row
status (To contact / Contacted / Replied). No SMTP, no LinkedIn scraping.

**Hard product constraints (do not break):**
- UI is **100% English** (the colleagues are not Italian). Code/comments are Italian — that's fine.
- Distribution for colleagues = **one clickable `.exe`**, no folders/zip/.bat to explain.
- Each colleague enters their own API key on first launch (saved to a local `.env`).
- Mac build → Claude (Anthropic key); Windows build → Gemini (cheaper for frequent multi-person use). Provider auto-detected from which key is in `.env` (`config.py`).

## Architecture (1-minute tour)

Pipeline (`main.py`): each `sources/<name>.py` exposes `fetch(limit, country) -> list[dict]`
with the common schema `company_name, website, sector, stage, founder_name, email,
country, source`. Records are deduped (`dedupe.py`, key = site domain or company name),
then enriched, then persisted.

Enrichment order in `main.py`:
1. `llm_enrich.py` (optional, `--enrich-llm`) — Claude/Gemini reads the real site to
   estimate **stage, sector, founder_name**, and find the **website URL if missing**.
   **It no longer sets the email** (see below).
2. `email_finder.py` — crawls the real site for a **verified** contact email.
3. `enrich.py` — Hunter.io, fallback only, if a key is present.

Persistence: `store.py` (SQLite `preseed.db`). `upsert_records()` accumulates,
detects changes, never overwrites a non-empty field with empty, never touches the
user-set `contact_status`. The `changes` table feeds the dashboard badges/banner.

Dashboard: `webapp.py` (Flask, single inline HTML/JS file, no build step). Desktop
shell: `app.py` (Flask thread + pywebview window), packaged with PyInstaller
(`--onedir` Mac via `build_mac_app.sh`, `--onefile` Windows via
`.github/workflows/build-windows.yml`).

## What was just built — Phase 3 (this session)

Driven by the user testing the live app. Four things:

1. **Verified emails, never invented (the headline fix).** Screenshot showed Akara
   Robotics with `hello@akararobotics.com` — invented; the real one is `info@akara.ai`.
   Root cause: the LLM was free-typing plausible emails. Fix:
   - New `email_finder.py`: fetches the home + `/contact /about /team ...` of the real
     site (browser UA, www-fallback), extracts emails from text + `mailto:`, drops
     third-party/placeholder noise (e.g. Stripe's `jenny.rosen@`), and **only accepts
     an email whose domain matches the site's domain**. Returns `None` if nothing
     trustworthy — empty beats wrong. Verified live: `akara.ai → info@akara.ai`,
     `stripe.com → None`.
   - `llm_enrich.py`: removed the email assignment + removed `email` from the prompt
     and output schema. LLM now only does stage/sector/founder/website.
2. **NEW vs UPDATED badges.** `store.py` `_badges_for()`: `NEW` (green) = never seen
   before this run; `UPDATED` (blue) = previously-known row that got new info **in the
   last run** (changes filtered to `MAX(changed_at)`), shown with detail badges (New
   contact / Stage changed / ...). Mutually exclusive. `webapp.py` got the `.badge.UPDATED`
   CSS + `badgeHtml()` mapping.
3. **Human-readable English progress** (`webapp.py` `poll()` → `describeProgress()`).
   Colleagues on Windows have no terminal, so the in-app indicator now shows readable
   phrases + an **"X of N" counter** parsed from the `[email] i/N` / `[llm] i/N` log
   lines (e.g. "Looking up contact emails on company sites… 42 of 180"), so they can
   see it's working, not frozen. On Mac the user keeps the real terminal.
4. **More sources** (contract `fetch(limit, country)`):
   - `sources/entrepreneur_first.py` — EF portfolio (HTML, no browser). **Exposes the
     founder name** per company (great for the "contact the founder" goal). Verified.
   - `sources/betalist.py` — BetaList launches; resolves each company's real site via
     the internal `/visit` 301 redirect. Verified.
   - `sources/crunchbase.py` — **opt-in, paid**. Real v4 `searches/organizations` call,
     but auto-skips with `[]` if `CRUNCHBASE_API_KEY` is absent. Not in defaults.
   - `config.py` gained `CRUNCHBASE_API_KEY` / `DEALROOM_API_KEY`; `.env.example` updated.

Defaults `--sources` now: `yc,producthunt,antler,cordis,rockstart,entrepreneur_first,betalist`.

**Verified end-to-end this session:** EF+BetaList run → 7 startups, founders populated
from EF, 2 domain-verified emails from real sites, the rest correctly left empty; run #1
all `NEW`, identical run #2 → no badges (accumulation + change tracking correct);
webapp `/api/startups` + `/` render with the new CSS/phrases.

## What to do next (the user's stated roadmap)

- **UI pass.** The user explicitly said: *"we will review the UI after all the logic
  improvements"*. Now is the time. Make the dashboard feel like a real product
  (Crunchbase-grade), still 100% English. Likely: better table density, founder column,
  a clear "contactable" filter/sort, per-row detail, nicer empty/loading states.
- **More founder/contact coverage** (the user wants *"almost every founder of every
  pre-seed"*). Ideas not yet done: more EU accelerator portfolios (Seedcamp, Founders
  Factory, Station F, Techstars EU), extend the CORDIS grant pattern to **EIT**, and
  surface **founder LinkedIn** where the source exposes it (EF's page has founder
  LinkedIn URLs in the markup — currently only the name is captured).
- **Dealroom source** — scaffold key exists in `config.py` but the source is not
  implemented (enterprise API, undocumented contract). Only do this if the user has a key.
- **Ship Windows build** — push to `main` triggers the Actions build; artifact is the
  single `Preseed Finder.exe`. Confirm the new deps (`requests`/`bs4`, already in
  `requirements.txt`) don't break `--onefile`.

## Gotchas

- Many sites drop a non-browser User-Agent (SSL EOF / 403). `email_finder.py` already
  uses a Chrome UA + www-fallback; reuse `BROWSER_UA` for new HTTP sources.
- CORDIS/EF often have **no website** in the listing → email crawl skips them; the LLM
  step is what fills the website, so run order (LLM before email crawl) matters.
- Scraped portfolios depend on CSS classes that can change; like yc/antler, fail
  gracefully (return `[]`/skip) instead of crashing the whole run.
- Respond to the user in **Italian** (their preference), but keep all app-facing UI text English.

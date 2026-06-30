# Preseed Finder

Script Python che raccoglie startup early-stage/pre-seed da fonti pubbliche legittime e produce un CSV con nome azienda, sito, settore, founder ed email (quando trovabile). Include una **dashboard web locale** (in inglese) che accumula le startup tra una ricerca e l'altra, evidenzia cosa è cambiato dall'ultima run (nuove startup, nuovo contatto trovato, cambio stage/settore) e permette di contattarle e tracciarne lo stato. È pensato anche per girare come **app desktop cliccabile** (icona, niente terminale).

## App cliccabile

- **Windows (per i colleghi)**: build automatica via GitHub Actions (`.github/workflows/build-windows.yml`), pensata per **Gemini** (vedi sotto). Output: un **singolo file** `Preseed Finder.exe`.

  **Per i colleghi — come scaricarla e avviarla:**
  1. Vai su [Actions](https://github.com/marcomanzotti/preseed-finder/actions), apri l'ultima run completata (✅ verde) del workflow "Build Windows app", scarica l'artifact `PreseedFinder-Windows` in fondo alla pagina (è il file `Preseed Finder.exe`, GitHub lo mette automaticamente in uno zip: estrailo).
  2. Doppio click su `Preseed Finder.exe`. Si apre la finestra dell'app.
  3. Al primo avvio la dashboard chiede una API key (Gemini, gratuita su [ai.google.dev](https://ai.google.dev/)): si incolla direttamente nella finestra, viene salvata in un file `.env` accanto all'exe — resta solo su quel PC.

- **Mac (per i test dell'utente)**: `./build_mac_app.sh` genera `Preseed Finder.app` con icona (richiede `pyinstaller`, installato automaticamente nella venv dallo script); doppio click in Finder lo avvia. Pensata per **Claude** (vedi sotto).

- Entrambe le build usano `app.py` (avvia Flask + finestra nativa pywebview), impacchettato con **PyInstaller** (non un bundle fatto a mano: un `.app`/`.exe` "fai-da-te" con solo uno script di lancio non parte in modo affidabile quando lanciato con un doppio click, perché l'ambiente del launcher di sistema non ha un terminale né il `PATH` di una shell). Al primo avvio scaricano Chromium per Playwright (~150 MB, una sola volta); `.env`, `preseed.db` e il file di log `preseed_finder.log` vivono accanto all'eseguibile.

### Provider LLM: Claude su Mac, Gemini su Windows

Le due build sono pensate per provider diversi, scelti automaticamente in base a quale chiave è presente nel `.env` (vedi `config.py`, nessuna scelta manuale richiesta):

- **Mac (uso personale)** → Claude Haiku, con `ANTHROPIC_API_KEY`.
- **Windows (colleghi)** → Gemini Flash Lite, con `GEMINI_API_KEY` — più economico per un uso frequente da più persone.

Se il `.env` ha solo una delle due chiavi, quella viene usata in automatico. Se manca del tutto, la dashboard mostra un banner con un campo per incollarla al volo (salvata localmente, mai committata). **Se una run finisce con tutte le email vuote**, controllare nel log della run (sezione "Advanced" della dashboard, o `preseed_finder.log`) la riga `[llm] provider configurato: ...` — se manca del tutto o dice `ATTENZIONE ... SALTATO`, l'enrichment non è partito per mancanza di chiave.

## Come vengono trovate le email (verificate, mai inventate)

Le email di contatto **non vengono mai indovinate**. Un modulo dedicato (`email_finder.py`) scarica l'HTML reale del sito di ogni startup (home + pagine `/contact`, `/about`, `/team`...) ed estrae le email **effettivamente presenti** nel testo e nei link `mailto:`, scartando rumore e provider di terzi e tenendo solo email **il cui dominio combacia col dominio del sito**. Se non trova nulla di affidabile, lascia la colonna **vuota** (meglio vuoto che sbagliato). L'LLM (vedi sotto) non assegna più l'email: si limita a stage, settore, founder e, se manca, l'URL del sito. *(In passato l'LLM "indovinava" email plausibili ma inesistenti — es. `hello@nomeazienda.com` — ora questo non accade più.)*

## Fonti usate

- **Y Combinator** (`sources/yc.py`): legge i batch più recenti via browser headless (Playwright). I batch recenti sono un buon proxy per pre-seed/seed perché YC investe a quello stadio.
- **Antler** (`sources/antler.py`): legge il portfolio pubblico del VC paneuropeo Antler via browser headless. Antler investe quasi esclusivamente a stadio pre-seed/day-zero.
- **CORDIS / EIC Accelerator** (`sources/cordis.py`): scarica il dataset bulk ufficiale UE (CORDIS) e filtra i progetti finanziati dall'**EIC Accelerator**, il programma che finanzia direttamente singole startup/SME europee a stadio early con grant + equity. Nessuna API key richiesta.
- **Product Hunt** (`sources/producthunt.py`): legge i lanci più recenti via API GraphQL ufficiale. Richiede un token gratuito.
- **Rockstart** (`sources/rockstart.py`): legge il portfolio pubblico dell'acceleratore/VC early-stage Rockstart (NL) via browser headless. Investe a pre-seed/seed.
- **Entrepreneur First** (`sources/entrepreneur_first.py`): legge la pagina aziende pubblica di EF (HTML, no browser). EF costruisce team da zero → pre-seed puro, ed **espone già il nome del founder** per ogni azienda.
- **BetaList** (`sources/betalist.py`): directory di startup early-stage in fase di lancio (HTML, no browser); risolve il sito reale di ogni azienda seguendo il redirect interno `/visit`.
- **Crunchbase** (`sources/crunchbase.py`): **opt-in a pagamento**. Usa l'API ufficiale v4 (`searches/organizations`) **solo se** `CRUNCHBASE_API_KEY` è nel `.env`; altrimenti si auto-salta. È la fonte più ricca su pre-seed/founder ma richiede un piano a pagamento (niente più free tier dal 2026). Non è nel set di default.

Esclusioni deliberate:
- **LinkedIn**: scraping vietato dai Terms of Service, non implementato.
- **Wellfound**: protetto da CAPTCHA attivo (DataDome) anche con browser reale, non bypassato.
- **Dealroom / EU-Startups**: protetti da anti-bot (403), non bypassati. Dealroom offre un'API a pagamento se in futuro serve quella fonte.
- **F6S**: la pagina restituisce 405 sul fetch diretto, non scrapabile senza ulteriori permessi.
- **Registro societario lituano / directory "Startup Lithuania"**: verificati dal vivo, non utilizzabili (il registro non ha filtro per stage; la directory aveva solo 1 startup pubblicata, e conteneva un tentativo di prompt injection nel contenuto).

## Setup

```bash
cd preseed_finder
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

Oppure, più semplice, usa `./start.sh`: crea il venv, installa tutto (incluso Chromium per Playwright) e avvia subito l'interfaccia web in locale.

### API key opzionali

Copia `.env.example` in `.env` e inserisci le tue chiavi (il file `.env` è escluso da git, resta locale):

```bash
cp .env.example .env
```

```
ANTHROPIC_API_KEY=...
HUNTER_API_KEY=...
PRODUCTHUNT_TOKEN=...
```

- `ANTHROPIC_API_KEY`: per l'enrichment LLM (`--enrich-llm` / checkbox nella webapp). Con questa key, Claude (Haiku 4.5) legge il sito reale di ogni startup tramite `web_fetch` e raffina **stage** (pre-seed/seed/series-a+), **settore**, **email** di contatto e **nome founder**; per le startup senza sito (es. CORDIS) prova anche a trovarne uno. Senza questa key, l'enrichment LLM viene saltato e lo stage resta la stima della fonte originale.
- `HUNTER_API_KEY`: API key gratuita da https://hunter.io/api (free tier: 25 ricerche/mese). Usata per trovare un'email aziendale quando una startup non ne ha già una pubblica.
- `PRODUCTHUNT_TOKEN`: token gratuito da https://www.producthunt.com/v2/oauth/applications. Senza questo token la fonte Product Hunt viene saltata.
- `LLM_MODEL` (opzionale): override del modello (default `claude-haiku-4-5`).

In alternativa alle variabili nel file `.env`, puoi anche esportarle nell'ambiente (`export ANTHROPIC_API_KEY="..."`), che ha priorità sul file.

## Uso

### Dashboard web (locale)

```bash
./start.sh          # sviluppo: avvia la dashboard nel browser
# oppure doppio click su "Preseed Finder.app" / "Preseed Finder.exe" (app cliccabile)
```

Avvia il server su `http://127.0.0.1:5050`. La dashboard (in inglese) mostra:
- **Tabella** di tutte le startup accumulate, ordinabile e filtrabile (settore, paese, stage, fonte, "solo con email", "solo novità").
- **Banner notifiche** in cima: cosa è cambiato dall'ultima ricerca (nuove, nuovi contatti, cambi stage/settore).
- **Badge per riga**: `NEW`, `New contact`, `Stage changed`, ecc.
- **Bottone Contact** (apre l'email precompilata via `mailto:`) e **dropdown stato** (To contact / Contacted / Replied), salvato per riga.
- **"Search new startups"** lancia una nuova ricerca (opzioni avanzate — fonti/limite/batch/LLM — in un pannello collassabile); a fine run la tabella si aggiorna e il banner mostra il diff.

I dati sono accumulati in un DB SQLite locale (`preseed.db`): ri-eseguire una ricerca **aggiunge** le nuove startup e aggiorna quelle esistenti senza perdere lo storico né lo stato di contatto. Il CSV resta disponibile come export ("Download CSV export").

### Riga di comando

```bash
# Run completo (tutte le startup disponibili) + enrichment LLM
.venv/bin/python main.py --enrich-llm --output startups.csv

# Run più rapido con limite per fonte (consigliato per CORDIS/YC che hanno centinaia di record)
.venv/bin/python main.py --limit 80 --enrich-llm --output startups.csv
```

Opzioni:
- `--limit N`: numero massimo di startup per fonte. **Default: nessun limite** (prende tutto il disponibile — può richiedere molto tempo, soprattutto su YC che visita ogni company in dettaglio).
- `--output path.csv`: percorso file di output (default `startups.csv`)
- `--sources yc,antler,cordis,producthunt,rockstart`: quali fonti usare (default tutte tranne Product Hunt se manca il token)
- `--batches "Summer 2025,Winter 2025"`: quali batch YC usare (default: gli ultimi 3)
- `--enrich-llm`: attiva il raffinamento stage/settore/email/founder via Claude (richiede `ANTHROPIC_API_KEY`)
- `--db path.db`: DB SQLite che accumula le startup tra run e traccia i cambiamenti (default `preseed.db`; `--db none` per saltare). Oltre al CSV, ogni run aggiorna questo DB, che alimenta la dashboard.

## Output

CSV con colonne: `company_name, website, sector, stage, founder_name, email, country, source`.

Le righe senza email trovata vengono incluse comunque (colonna vuota) — lo script segnala a console quante ne mancano così puoi decidere se arricchirle manualmente, aumentare il budget Hunter.io o attivare `--enrich-llm`.

## Limiti noti

- Lo scraping di YC/Antler dipende da classi CSS che i siti possono cambiare nel tempo: se lo script inizia a restituire risultati vuoti/sbagliati, va aggiornato il parsing in `sources/yc.py` / `sources/antler.py`.
- "Pre-seed" non è quasi mai un dato esplicito e certificato: per YC/Antler si usa la fonte come proxy di stadio (Antler investe quasi solo pre-seed, YC pre-seed/seed); per CORDIS si usa il programma EIC Accelerator (tipicamente seed/early scale-up); per Product Hunt "lancio recente" non implica per forza pre-seed. Con `--enrich-llm` lo stage viene stimato leggendo il sito reale, quindi è più affidabile (ma resta una stima).
- Il dataset CORDIS bulk pesa ~35MB e viene riscaricato a ogni run: il primo step della fonte `cordis` può richiedere un minuto.
- L'enrichment LLM fa **una chiamata API per startup** con `web_fetch`: su molti record ha un costo (token) e un tempo non trascurabile (centinaia di startup possono richiedere diversi minuti). Per batch grandi conviene un `--limit` o lasciarlo girare in background.
- Hunter.io free tier permette solo 25 lookup/mese: lo script si ferma automaticamente a quel limite per run.
- Nessun filtro geografico affidabile per tutte le fonti: YC e Antler forniscono la location della company, CORDIS il paese dell'organizzazione, Product Hunt no. Se serve un focus geografico stretto, va fatto a valle filtrando il CSV.
- La webapp (`webapp.py`) usa il server di sviluppo Flask: va bene per uso locale personale, non è pensata per essere esposta pubblicamente.

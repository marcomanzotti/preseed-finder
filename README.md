# Preseed Finder

Script Python che raccoglie startup early-stage/pre-seed da fonti pubbliche legittime e produce un CSV con nome azienda, sito, settore, founder ed email (quando trovabile). Include anche una semplice interfaccia web locale per lanciare la ricerca e scaricare il CSV dal browser.

## Fonti usate

- **Y Combinator** (`sources/yc.py`): legge i batch più recenti via browser headless (Playwright). I batch recenti sono un buon proxy per pre-seed/seed perché YC investe a quello stadio.
- **Antler** (`sources/antler.py`): legge il portfolio pubblico del VC paneuropeo Antler via browser headless. Antler investe quasi esclusivamente a stadio pre-seed/day-zero.
- **CORDIS / EIC Accelerator** (`sources/cordis.py`): scarica il dataset bulk ufficiale UE (CORDIS) e filtra i progetti finanziati dall'**EIC Accelerator**, il programma che finanzia direttamente singole startup/SME europee a stadio early con grant + equity. Nessuna API key richiesta.
- **Product Hunt** (`sources/producthunt.py`): legge i lanci più recenti via API GraphQL ufficiale. Richiede un token gratuito.

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

### Interfaccia web (locale)

```bash
./start.sh
```

Apre il setup automatico e avvia il server su `http://127.0.0.1:5050`. Da lì puoi scegliere fonti, limite per fonte, batch YC e attivare l'enrichment LLM, vedere il log in tempo reale e scaricare il CSV a fine run.

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
- `--sources yc,antler,cordis,producthunt`: quali fonti usare (default tutte tranne Product Hunt se manca il token)
- `--batches "Summer 2025,Winter 2025"`: quali batch YC usare (default: gli ultimi 3)
- `--enrich-llm`: attiva il raffinamento stage/settore/email/founder via Claude (richiede `ANTHROPIC_API_KEY`)

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

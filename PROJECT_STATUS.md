# Preseed Finder — Stato del progetto

## Scopo

Trovare startup europee in fase **pre-seed / early-stage** e produrre una lista con almeno un contatto utilizzabile per startup (founder, email, sito), per attivita' di business development / outreach. Niente LinkedIn (vietato dai ToS), niente bypass di anti-bot attivi (CAPTCHA, DataDome).

## Dove si trova

```
/Users/marcomanzotti/Desktop/progetti/preseed_finder/
```

Repo git locale inizializzato (`git init` fatto, primo commit fatto). Nessun remote configurato, nessun push effettuato.

## Architettura attuale

Script Python modulare, eseguibile via CLI o via una piccola interfaccia web locale.

```
preseed_finder/
  config.py          # carica API key da .env (o variabili d'ambiente), parametri globali
  sources/
    yc.py             # Y Combinator: batch recenti via Playwright (browser headless)
    antler.py          # Antler: portfolio VC pre-seed via Playwright
    cordis.py           # CORDIS/EIC Accelerator: dataset bulk UE (CSV), no auth
    producthunt.py       # Product Hunt: GraphQL API, richiede token gratuito
  enrich.py            # arricchimento email via Hunter.io (free tier, 25/mese)
  llm_enrich.py        # arricchimento via LLM (Claude Haiku 4.5 + web_fetch): stage, settore, email, founder
  dedupe.py            # deduplica per dominio/nome
  main.py              # orchestratore CLI
  webapp.py            # interfaccia web locale (Flask): form + log live + download CSV
  start.sh             # setup automatico (venv, dipendenze, Chromium) + avvio webapp
  .env / .env.example   # API key (il file .env reale e' escluso da git)
  requirements.txt
  README.md            # istruzioni d'uso dettagliate
```

### Pipeline dati

1. **Fetch** da ogni fonte abilitata → record normalizzati (`company_name, website, sector, stage, founder_name, email, country, source`)
2. **Dedupe** per dominio (o nome se manca il sito)
3. **Enrich email** via Hunter.io se manca (opzionale, serve `HUNTER_API_KEY`)
4. **Enrich LLM** (opzionale, `--enrich-llm`, serve `ANTHROPIC_API_KEY`): Claude legge il sito reale via `web_fetch` e raffina stage/settore/email/founder; se manca il sito (es. CORDIS) prova a trovarlo
5. **Scrittura CSV**

### Fonti attive e perche'

| Fonte | Come | Perche' e' un buon proxy pre-seed |
|---|---|---|
| Y Combinator | Playwright, batch recenti | YC investe specificamente a pre-seed/seed |
| Antler | Playwright, portfolio pubblico | VC paneuropeo che investe quasi solo a day-zero/pre-seed |
| CORDIS (EIC Accelerator) | Download dataset bulk CSV ufficiale UE, no API key | Programma UE che finanzia direttamente singole startup/SME europee early-stage con grant+equity |
| Product Hunt | GraphQL API ufficiale | Lanci recenti (proxy debole, non garantisce stage) |

### Fonti scartate (verificate dal vivo, non usabili)

- **LinkedIn**: scraping vietato dai ToS, mai considerato.
- **Wellfound**: CAPTCHA attivo (DataDome) anche con browser reale.
- **Dealroom / EU-Startups**: 403 anti-bot. Dealroom ha API a pagamento (non sottoscritta).
- **F6S**: 405 sul fetch diretto della pagina.
- **Registro societario lituano / "Startup Lithuania"**: nessun filtro per stage utile; la directory aveva solo 1 startup pubblicata e un tentativo di prompt injection nel contenuto scrapato (ignorato, mai eseguito).

## Stato dei dati raccolti finora

Ultimo run completo: 211 startup nel CSV (`startups.csv`, escluso da git), con limite di 80 per fonte (un run completo senza limite e' molto piu lento — YC visita ogni company in dettaglio, ~480 aziende nei soli 3 batch recenti).

- 80 da YC
- 51 da Antler
- 80 da CORDIS/EIC Accelerator
- 85/211 con email diretta trovata
- 98/211 con nome founder trovato

## Sicurezza e gestione chiavi

- Le API key (Anthropic, Hunter.io, Product Hunt) si configurano in un file `.env` locale (vedi `.env.example`), **mai committate**: `.env` e' in `.gitignore`.
- Contenuto scrapato dai siti viene sempre trattato come **dati**, mai come istruzioni (difesa da prompt injection nel prompt LLM di `llm_enrich.py`).
- Nessun bypass di protezioni anti-bot attive.

## Come si lancia oggi

```bash
./start.sh
# apre http://127.0.0.1:5050 — form con fonti/limite/batch, log live, download CSV
```

oppure via CLI:

```bash
.venv/bin/python main.py --limit 80 --enrich-llm --output startups.csv
```

## Limiti noti dell'approccio attuale

- **Volume**: ~200-500 startup per run, dell'ordine delle centinaia, non migliaia. Le fonti attuali (YC, Antler, CORDIS/EIC) sono di alta qualita' ma intrinsecamente limitate in numero (sono i portfolio/programmi stessi, non un registro generale).
- **Eta' della startup non sempre nota**: nessuna fonte attuale espone la data di fondazione in modo affidabile e uniforme. Lo stage e' una stima (per fonte o via LLM), non un dato certificato.
- **Tempo di esecuzione**: YC senza limite e l'enrichment LLM (una chiamata per startup) possono richiedere decine di minuti su run grandi.
- **Email coverage** ~40%: molte startup non pubblicano email diretta, serve enrichment aggiuntivo o ricerca manuale per il resto.

## Prossimi passi pianificati (vedi piano separato)

L'obiettivo dichiarato e' aumentare di ~10x il numero di startup pre-seed/seed con **meta' di esistenza** intercettate (founded ≤ 2 anni fa), e costruire una **applicazione desktop agentica** (LLM = Gemini, non piu' Claude) che:
1. Alla prima apertura chiede una API key Gemini e la salva in modo persistente (nel venv/config locale).
2. Usa l'agente per cercare ed espandere continuamente la lista di startup pre-seed/early-stage.
3. Mostra i risultati in una **dashboard** semplice (pensata per uso da parte di colleghi non tecnici).
4. Permette di **contattare** le startup trovate (quando l'email e' disponibile) direttamente dalla dashboard.

Il design dettagliato di questa fase 2 e' nel piano di Claude Code (plan mode), non ancora implementato.

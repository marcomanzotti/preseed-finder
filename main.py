import argparse
import csv

from sources import yc, producthunt, antler, cordis, rockstart, entrepreneur_first, betalist, crunchbase, hackernews
from dedupe import dedupe, dedupe_key
from enrich import enrich_missing_emails
import email_finder
import llm_enrich
import qualify
import store

CSV_FIELDS = ["company_name", "website", "sector", "stage", "founder_name", "email", "country", "source", "preseed_confidence", "qualified", "exclude_reason"]

# Campi che, per un record gia' arricchito in passato, prendiamo dal DB per non
# ri-elaborarlo e per non sovrascrivere i valori raffinati con quelli grezzi.
_ENRICHED_FIELDS = ("stage", "sector", "founder_name", "stage_reason")
_HYDRATE_FIELDS = ("website", "sector", "stage", "founder_name", "email", "country", "stage_reason")


def main():
    parser = argparse.ArgumentParser(description="Trova startup pre-seed/early-stage e produce un CSV con almeno un contatto per startup.")
    parser.add_argument("--limit", type=int, default=None, help="Numero massimo di startup per fonte. Default: nessun limite (prende tutto il disponibile).")
    parser.add_argument("--output", default="startups.csv", help="Percorso file CSV di output (default: startups.csv)")
    parser.add_argument("--sources", default="yc,producthunt,antler,cordis,rockstart,entrepreneur_first,betalist,hackernews", help="Fonti da usare, separate da virgola. Disponibili: yc, producthunt, antler, cordis, rockstart, entrepreneur_first, betalist, hackernews, crunchbase.")
    parser.add_argument("--db", default=store.DEFAULT_DB_PATH, help="Percorso DB SQLite che accumula le startup tra run (default: preseed.db). Vuoto/'none' per saltare.")
    parser.add_argument("--batches", default=None, help="Batch YC da usare, separati da virgola (es. 'Summer 2025,Winter 2025'). Default: gli ultimi 3.")
    parser.add_argument("--enrich-llm", action="store_true", help="Usa un LLM (Claude o Gemini, vedi LLM_PROVIDER in .env) per stimare lo stage reale, il settore e trovare email/founder leggendo il sito (richiede ANTHROPIC_API_KEY o GEMINI_API_KEY).")
    args = parser.parse_args()

    enabled_sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    yc_batches = [b.strip() for b in args.batches.split(",")] if args.batches else None

    all_records = []
    for name in enabled_sources:
        print(f"[main] fetching da '{name}'...")
        try:
            if name == "yc":
                records = yc.fetch(limit=args.limit, batches=yc_batches)
            elif name == "producthunt":
                records = producthunt.fetch(limit=args.limit)
            elif name == "antler":
                records = antler.fetch(limit=args.limit)
            elif name == "cordis":
                records = cordis.fetch(limit=args.limit)
            elif name == "rockstart":
                records = rockstart.fetch(limit=args.limit)
            elif name == "entrepreneur_first":
                records = entrepreneur_first.fetch(limit=args.limit)
            elif name == "betalist":
                records = betalist.fetch(limit=args.limit)
            elif name == "crunchbase":
                records = crunchbase.fetch(limit=args.limit)
            elif name == "hackernews":
                records = hackernews.fetch(limit=args.limit)
            else:
                print(f"[main] fonte sconosciuta '{name}', salto.")
                continue
        except Exception as e:
            print(f"[main] errore fetching '{name}': {e}")
            records = []
        print(f"[main] '{name}': {len(records)} record trovati.")
        all_records.extend(records)

    print(f"[main] totale record raccolti: {len(all_records)}")
    deduped = dedupe(all_records)
    print(f"[main] dopo dedupe: {len(deduped)}")

    use_db = bool(args.db and args.db.lower() != "none")

    # 0) Idratazione dal DB: riempi i buchi coi valori gia' trovati in run
    #    precedenti e individua chi e' gia' stato arricchito dall'LLM (skip_keys),
    #    per non ri-scaricare/ri-chiamare l'LLM su di loro (meno token, piu' veloce).
    skip_keys = set()
    if use_db:
        existing = store.get_existing_by_key(args.db)
        for r in deduped:
            prev = existing.get(dedupe_key(r))
            if not prev:
                continue
            if prev.get("enriched_at"):
                skip_keys.add(dedupe_key(r))
                for f in _ENRICHED_FIELDS:  # adotta i valori raffinati dal DB
                    if prev.get(f):
                        r[f] = prev[f]
            for f in _HYDRATE_FIELDS:        # riempi i restanti buchi
                if not r.get(f) and prev.get(f):
                    r[f] = prev[f]
        print(f"[main] {len(skip_keys)} startup gia' arricchite in passato: le salto nell'analisi.")

    # 1) Leggi i siti reali UNA volta: email verificata (mai inventata) + testo
    #    pulito del sito (record["_site_text"]) che alimenta l'LLM come DATI.
    deduped = email_finder.crawl_sites(deduped, skip_keys=skip_keys)

    # 2) LLM sul testo del sito: raffina stage/settore/founder e i segnali di
    #    funding. Non naviga (niente web_fetch): estrae o mette null, mai inventa.
    if args.enrich_llm:
        deduped = llm_enrich.enrich_with_llm(deduped, skip_keys=skip_keys)

    # 3) Hunter.io solo come fallback opzionale, se la key c'e' e il crawl non
    #    ha trovato nulla per quel record.
    deduped = enrich_missing_emails(deduped)

    # 4) Qualificazione pre-seed: tiene solo chi non ha round oltre il pre-seed ed
    #    e' in US/Canada/Europa. Gli esclusi restano tracciati col motivo.
    deduped = qualify.qualify_records(deduped)

    missing_email = sum(1 for r in deduped if not r.get("email"))
    if missing_email:
        print(f"[main] attenzione: {missing_email} record su {len(deduped)} non hanno email (filtrali manualmente se necessario).")

    # Accumula nel DB SQLite (storico + change tracking) oltre a esportare il CSV.
    if use_db:
        report = store.upsert_records(deduped, db_path=args.db)
        print(
            f"[main] DB aggiornato ({args.db}): +{report.new_startups} nuove, "
            f"{report.new_contacts} nuovi contatti, {report.stage_changes} cambi stage, "
            f"{report.sector_changes} cambi settore, "
            f"{report.website_or_founder_updates} sito/founder aggiornati."
        )

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in deduped:
            # None -> "" ma NON convertire 0 (qualified=0) in vuoto.
            writer.writerow({k: ("" if record.get(k) is None else record.get(k)) for k in CSV_FIELDS})

    print(f"[main] scritto {args.output} con {len(deduped)} startup.")


if __name__ == "__main__":
    main()

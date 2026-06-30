import argparse
import csv

from sources import yc, producthunt, antler, cordis, rockstart
from dedupe import dedupe
from enrich import enrich_missing_emails
import llm_enrich
import store

CSV_FIELDS = ["company_name", "website", "sector", "stage", "founder_name", "email", "country", "source"]


def main():
    parser = argparse.ArgumentParser(description="Trova startup pre-seed/early-stage e produce un CSV con almeno un contatto per startup.")
    parser.add_argument("--limit", type=int, default=None, help="Numero massimo di startup per fonte. Default: nessun limite (prende tutto il disponibile).")
    parser.add_argument("--output", default="startups.csv", help="Percorso file CSV di output (default: startups.csv)")
    parser.add_argument("--sources", default="yc,producthunt,antler,cordis", help="Fonti da usare, separate da virgola (default: yc,producthunt,antler,cordis). Disponibili anche: rockstart.")
    parser.add_argument("--db", default=store.DEFAULT_DB_PATH, help="Percorso DB SQLite che accumula le startup tra run (default: preseed.db). Vuoto/'none' per saltare.")
    parser.add_argument("--batches", default=None, help="Batch YC da usare, separati da virgola (es. 'Summer 2025,Winter 2025'). Default: gli ultimi 3.")
    parser.add_argument("--enrich-llm", action="store_true", help="Usa un LLM Anthropic per stimare lo stage reale e classificare il settore leggendo il sito (richiede ANTHROPIC_API_KEY).")
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

    deduped = enrich_missing_emails(deduped)

    if args.enrich_llm:
        deduped = llm_enrich.enrich_with_llm(deduped)

    missing_email = sum(1 for r in deduped if not r.get("email"))
    if missing_email:
        print(f"[main] attenzione: {missing_email} record su {len(deduped)} non hanno email (filtrali manualmente se necessario).")

    # Accumula nel DB SQLite (storico + change tracking) oltre a esportare il CSV.
    if args.db and args.db.lower() != "none":
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
            writer.writerow({k: record.get(k, "") or "" for k in CSV_FIELDS})

    print(f"[main] scritto {args.output} con {len(deduped)} startup.")


if __name__ == "__main__":
    main()

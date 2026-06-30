from urllib.parse import urlparse


def dedupe_key(record):
    """Chiave di deduplica per una startup: dominio del sito (senza www) se
    presente, altrimenti il nome azienda normalizzato. Riusata da store.py per
    accumulare le startup tra run diverse."""
    website = record.get("website")
    if website:
        netloc = urlparse(website if "://" in website else f"https://{website}").netloc
        return netloc.removeprefix("www.").lower()
    return (record.get("company_name") or "").strip().lower()


def dedupe(records):
    seen = {}
    for record in records:
        key = dedupe_key(record)
        if not key:
            continue
        if key not in seen:
            seen[key] = record
            continue
        existing = seen[key]
        for field in ("email", "founder_name", "sector", "country", "website"):
            if not existing.get(field) and record.get(field):
                existing[field] = record[field]
    return list(seen.values())

"""Fonte Crunchbase (API ufficiale v4) — OPT-IN, a pagamento.

Crunchbase e' la base dati piu' ricca su pre-seed/seed e founder, ma:
  - lo scraping del sito e' vietato dai Terms of Service;
  - dal 2026 non c'e' piu' un free tier: serve un piano a pagamento e una
    CRUNCHBASE_API_KEY.

Quindi questa fonte e' OPT-IN come Product Hunt: se `config.CRUNCHBASE_API_KEY`
non e' presente, si auto-salta restituendo [] senza errori, e il resto della
pipeline (fonti gratuite) funziona normalmente. Chi vuole la massima coverage e
accetta il costo mette la key nel .env.

Endpoint: POST https://api.crunchbase.com/api/v4/searches/organizations
Auth: header `X-cb-user-key`. Doc: https://data.crunchbase.com/docs/using-search-apis
"""

import requests

import config

SEARCH_URL = "https://api.crunchbase.com/api/v4/searches/organizations"

# Stadi di funding "early" su Crunchbase, per filtrare verso pre-seed/seed.
EARLY_STAGE_FUNDING = ["pre_seed", "seed"]


def fetch(limit=None, country=None):
    if not config.CRUNCHBASE_API_KEY:
        print("[crunchbase] CRUNCHBASE_API_KEY non configurata, fonte saltata (opt-in a pagamento).")
        return []

    page_limit = min(limit or 50, 1000)
    payload = {
        "field_ids": [
            "identifier", "website_url", "categories",
            "last_funding_type", "location_identifiers",
        ],
        "query": [
            {
                "type": "predicate",
                "field_id": "last_funding_type",
                "operator_id": "includes",
                "values": EARLY_STAGE_FUNDING,
            }
        ],
        "limit": page_limit,
    }
    if country:
        payload["query"].append({
            "type": "predicate",
            "field_id": "location_identifiers",
            "operator_id": "includes",
            "values": [country],
        })

    print(f"[crunchbase] interrogo l'API ufficiale (limite {page_limit})...")
    try:
        resp = requests.post(
            SEARCH_URL,
            headers={"X-cb-user-key": config.CRUNCHBASE_API_KEY, "Content-Type": "application/json"},
            json=payload,
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        print(f"[crunchbase] errore API: {e}")
        return []

    records = []
    for entity in data.get("entities", []):
        props = entity.get("properties", {})
        name = (props.get("identifier") or {}).get("value")
        if not name:
            continue
        categories = props.get("categories") or []
        sector = ", ".join(c.get("value") for c in categories[:2] if c.get("value")) or None
        locations = props.get("location_identifiers") or []
        country_val = locations[-1].get("value") if locations else None
        funding = props.get("last_funding_type")
        stage = "pre-seed" if funding == "pre_seed" else ("seed" if funding == "seed" else None)

        records.append({
            "company_name": name,
            "website": props.get("website_url"),
            "sector": sector,
            "stage": stage,
            "founder_name": None,  # i founder richiedono una query relationships separata
            "email": None,
            "country": country_val,
            "source": "crunchbase",
        })

    print(f"[crunchbase] {len(records)} startup estratte dall'API.")
    return records

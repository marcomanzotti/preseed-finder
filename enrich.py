import time
from urllib.parse import urlparse

import requests

import config

HUNTER_URL = "https://api.hunter.io/v2/domain-search"


def _domain_from_url(url):
    if not url:
        return None
    netloc = urlparse(url if "://" in url else f"https://{url}").netloc
    return netloc.removeprefix("www.") or None


def enrich_missing_emails(records):
    if not config.HUNTER_API_KEY:
        print("[enrich] HUNTER_API_KEY non configurato, enrichment email saltato.")
        return records

    lookups_done = 0
    for record in records:
        if record.get("email"):
            continue
        if lookups_done >= config.HUNTER_MONTHLY_LIMIT:
            print(f"[enrich] raggiunto limite di {config.HUNTER_MONTHLY_LIMIT} lookup Hunter.io free tier, fermo l'enrichment.")
            break

        domain = _domain_from_url(record.get("website"))
        if not domain:
            continue

        try:
            resp = requests.get(
                HUNTER_URL,
                params={"domain": domain, "api_key": config.HUNTER_API_KEY, "limit": 1},
                timeout=config.REQUEST_TIMEOUT,
            )
            lookups_done += 1
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"[enrich] errore lookup {domain}: {e}")
            time.sleep(1)
            continue

        emails = data.get("data", {}).get("emails", [])
        if emails:
            record["email"] = emails[0].get("value")

        time.sleep(1)

    return records

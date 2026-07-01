"""Fonte Hacker News "Show HN" via API Algolia (gratis, senza key).

I post "Show HN:" sono lanci di prodotti fatti quasi sempre dai founder stessi,
spesso pre-seed / appena usciti: un'ottima fonte early-stage per software e
consumer (US/Europa in prevalenza). L'API Algolia di HN e' pubblica, stabile e
non richiede autenticazione:

  https://hn.algolia.com/api/v1/search_by_date?tags=show_hn

Ogni hit ha `title` ("Show HN: Nome - descrizione"), `url` (il sito del prodotto,
quando presente), `author` (username HN, NON un nome reale -> non usato come
founder) e `created_at` (per il segnale "lancio recente" usato da qualify.py).
"""

import re

import requests

import config

API = "https://hn.algolia.com/api/v1/search_by_date"

# Tetto ragionevole quando non c'e' un --limit (l'API pagina a 100 per volta).
HN_MAX_WHEN_UNLIMITED = 200

_PREFIX_RE = re.compile(r"^\s*(show|launch)\s+hn\s*[:\-–—]\s*", re.IGNORECASE)
_SEP_RE = re.compile(r"\s+[–—-]\s+|\s*[:|]\s+")


def _clean_name(title):
    """Ricava il nome prodotto dal titolo: toglie 'Show HN:' e la descrizione
    dopo il primo separatore (' - ', ' – ', ':', '|')."""
    t = _PREFIX_RE.sub("", title or "").strip()
    t = _SEP_RE.split(t, 1)[0].strip()
    return t or (title or "").strip()


def fetch(limit=None, country=None):
    effective_limit = limit if limit is not None else HN_MAX_WHEN_UNLIMITED
    records = []
    page = 0
    print("[hackernews] scarico i lanci 'Show HN' da HN (API Algolia)...")
    while len(records) < effective_limit and page < 15:
        try:
            resp = requests.get(
                API,
                params={"tags": "show_hn", "hitsPerPage": 100, "page": page},
                headers={"User-Agent": config.USER_AGENT},
                timeout=config.REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"[hackernews] errore richiesta: {e}")
            break

        hits = data.get("hits", [])
        if not hits:
            break

        for hit in hits:
            url = hit.get("url")
            title = hit.get("title")
            if not url or not title:
                continue  # senza sito non e' contattabile ne' analizzabile
            records.append({
                "company_name": _clean_name(title),
                "website": url,
                "sector": None,
                "stage": "pre-seed (Show HN launch)",
                "founder_name": None,  # 'author' e' uno username HN, non un nome
                "email": None,
                "country": None,
                "source": "hackernews",
                "source_date": hit.get("created_at"),  # per il segnale "recente"
            })
            if len(records) >= effective_limit:
                break

        print(f"[hackernews]   {len(records)} lanci raccolti...")
        page += 1

    print(f"[hackernews] {len(records)} startup estratte.")
    return records[:effective_limit]

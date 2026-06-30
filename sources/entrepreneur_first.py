"""Fonte Entrepreneur First (EF): portfolio pubblico dell'acceleratore
"talent-first" paneuropeo (Londra, Berlino, Parigi, Bangalore...). EF investe
allo stadio piu' early in assoluto — costruisce team da zero — quindi e' un
ottimo proxy per pre-seed.

A differenza di altri portfolio, la pagina aziende di EF e' HTML server-rendered
ed espone gia' il NOME DEL FOUNDER (e il suo ruolo) per ogni azienda: prezioso
per l'obiettivo "trovare il founder di ogni pre-seed". Si scarica con requests
(niente browser) e si estrae con BeautifulSoup.

Layout: una griglia di `div.tile--company`; per ogni tile:
  - `h4` = nome azienda
  - `.categorytag` = settore/i
  - `.meta__row` con classe `__founder` = riga founder (ruolo + nome)
Nota: EF non pubblica il sito ufficiale dell'azienda nella griglia, quindi
`website` resta None e verra' eventualmente cercato dall'LLM in fase di
enrichment; il founder invece e' gia' qui.
"""

import requests
from bs4 import BeautifulSoup

COMPANIES_URL = "https://www.joinef.com/companies/"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _founder_from_tile(tile):
    """Nome del primo founder di un tile EF.

    L'elemento con classe `meta__row__founder` contiene direttamente il nome del
    founder (es. "Alex Dalyac"). Si prende il primo."""
    el = tile.find(class_="meta__row__founder")
    if el:
        name = el.get_text(" ", strip=True)
        if name:
            return name
    return None


def _sector_from_tile(tile):
    cats = [c.get_text(strip=True) for c in tile.find_all(class_="categorytag")]
    cats = [c for c in cats if c]
    return ", ".join(cats[:2]) if cats else None


def fetch(limit=None, country=None):
    print("[entrepreneur_first] scarico la pagina aziende di EF...")
    try:
        resp = requests.get(COMPANIES_URL, headers={"User-Agent": BROWSER_UA}, timeout=25)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[entrepreneur_first] errore download: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    tiles = soup.find_all(class_="tile--company")
    print(f"[entrepreneur_first] {len(tiles)} aziende trovate, estraggo i dati...")

    records = []
    seen = set()
    for tile in tiles:
        name_el = tile.find(["h4", "h3", "h2"])
        company_name = name_el.get_text(strip=True) if name_el else None
        if not company_name or company_name.lower() in seen:
            continue
        seen.add(company_name.lower())

        records.append({
            "company_name": company_name,
            "website": None,  # EF non espone il sito nella griglia
            "sector": _sector_from_tile(tile),
            "stage": "pre-seed",  # EF costruisce team da zero: pre-seed puro
            "founder_name": _founder_from_tile(tile),
            "email": None,
            "country": None,
            "source": "entrepreneur_first",
        })
        if limit is not None and len(records) >= limit:
            break

    print(f"[entrepreneur_first] {len(records)} startup estratte.")
    return records

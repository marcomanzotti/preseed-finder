"""Fonte BetaList: directory di startup early-stage in fase di lancio/pre-lancio
(betalist.com). Le startup qui sono tipicamente pre-seed/seed che cercano i primi
utenti, quindi un buon proxy di stadio early per prodotti consumer/SaaS.

La homepage e' HTML server-rendered: elenca card che linkano a una pagina interna
`/startups/<slug>`. Il sito REALE dell'azienda non e' nella card ma dietro un
redirect `/startups/<slug>/visit` (301 -> URL del sito, con un `?ref=betalist`
da ripulire). Si segue quel redirect per ottenere il sito vero, su cui poi il
crawl email (email_finder) potra' cercare un contatto.
"""

from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

BASE = "https://betalist.com"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _strip_query(url):
    """Rimuove query/fragment (es. ?ref=betalist) lasciando lo schema+host+path."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _resolve_site(slug, session):
    """Segue il redirect /startups/<slug>/visit fino al sito reale dell'azienda."""
    try:
        resp = session.head(
            f"{BASE}/startups/{slug}/visit",
            headers={"User-Agent": BROWSER_UA},
            timeout=20,
            allow_redirects=True,
        )
        final = resp.url
        if final and "betalist.com" not in final:
            return _strip_query(final)
    except requests.RequestException:
        return None
    return None


def fetch(limit=None, country=None):
    print("[betalist] scarico la homepage di BetaList...")
    session = requests.Session()
    try:
        resp = session.get(f"{BASE}/", headers={"User-Agent": BROWSER_UA}, timeout=25)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[betalist] errore download: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Ogni startup ha un link /startups/<slug>; il testo del link e' il nome.
    slugs = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/startups/" not in href:
            continue
        slug = href.split("/startups/", 1)[1].strip("/").split("/")[0]
        if not slug or slug in seen:
            continue
        name = a.get_text(strip=True)
        if not name:
            continue
        seen.add(slug)
        slugs.append((slug, name))

    if limit is not None:
        slugs = slugs[:limit]

    print(f"[betalist] {len(slugs)} startup trovate, risolvo i siti reali...")
    records = []
    for i, (slug, name) in enumerate(slugs, 1):
        website = _resolve_site(slug, session)
        records.append({
            "company_name": name,
            "website": website,
            "sector": None,
            "stage": "pre-seed",  # BetaList = prodotti in lancio/pre-lancio
            "founder_name": None,
            "email": None,
            "country": None,
            "source": "betalist",
        })
        if i % 10 == 0 or i == len(slugs):
            print(f"[betalist]   {i}/{len(slugs)} risolte...")

    print(f"[betalist] {len(records)} startup estratte.")
    return records

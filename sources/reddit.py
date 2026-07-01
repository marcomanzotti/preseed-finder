"""Fonte Reddit: founder che lanciano progetti appena nati.

Su alcuni subreddit i founder pubblicano da soli il proprio prodotto pochi
giorni dopo (o prima) del lancio: e' una delle fonti pre-seed piu' fresche e
gratuite, di qualita' simile ai 'Show HN'. Teniamo SOLO i post che linkano un
sito esterno (non un permalink Reddit ne' un social/store): senza sito la
startup non e' ne' contattabile ne' analizzabile dall'enrichment. Il nome
azienda si ricava dal dominio del sito (piu' pulito del titolo, che e' una
frase); founder/settore li rifinira' l'LLM leggendo il sito.

ACCESSO — Reddit ha chiuso gli endpoint pubblici `.json` (403 "Blocked" dai
data-center). Due modalita', in ordine di affidabilita':
  1. **API OAuth (consigliata, gratis):** se nel .env ci sono REDDIT_CLIENT_ID e
     REDDIT_CLIENT_SECRET (crea un'app "web app" su
     https://www.reddit.com/prefs/apps), si usa un token app-only (sola lettura,
     nessun account utente) su https://oauth.reddit.com — affidabile ovunque.
  2. **Fallback pubblico best-effort:** senza credenziali si prova comunque
     `www.reddit.com/.../new.json`. Da un IP residenziale (il PC dei colleghi)
     spesso funziona; se Reddit risponde 403 la fonte si auto-salta con un
     messaggio chiaro (nessun crash, coerente con le altre fonti opt-in).

`author` e' uno username Reddit, non un nome reale -> non usato come founder.
"""

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

import config

# Subreddit dove i founder pubblicano prodotti nuovi con un link al sito.
# 'new' = ordine cronologico inverso, cosi' prendiamo i lanci piu' recenti.
SUBREDDITS = ("SideProject", "roastmystartup", "indiehackers", "alphaandbetausers")

# Tetto per subreddit quando non c'e' --limit (l'endpoint pagina a 100).
REDDIT_MAX_PER_SUB = 100

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
OAUTH_BASE = "https://oauth.reddit.com/r/{sub}/new"
PUBLIC_BASE = "https://www.reddit.com/r/{sub}/new.json"

# Host da NON considerare "sito del prodotto": social, store, reddit stesso, ecc.
_SKIP_HOSTS = (
    "reddit.com", "redd.it", "youtube.com", "youtu.be", "twitter.com", "x.com",
    "github.com", "gitlab.com", "medium.com", "notion.so", "notion.site",
    "linkedin.com", "facebook.com", "instagram.com", "tiktok.com",
    "apps.apple.com", "play.google.com", "imgur.com", "loom.com",
    "docs.google.com", "forms.gle", "discord.gg", "discord.com", "substack.com",
)


def _host(url):
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except ValueError:
        return ""


def _is_product_url(url):
    if not url or not url.startswith("http"):
        return False
    host = _host(url)
    return bool(host) and not any(host == h or host.endswith("." + h) for h in _SKIP_HOSTS)


# TLD di secondo livello: per 'foo.co.uk' l'etichetta utile e' 'foo', non 'co'.
_SECOND_LEVEL_TLDS = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "co.in", "com.br", "com.au",
    "co.nz", "com.mx", "co.za", "com.tr",
}


def _name_from_host(host):
    """'getacme.io' -> 'Getacme', 'my-startup.co.uk' -> 'My Startup'. Prende
    l'etichetta di dominio principale, saltando i TLD a due livelli."""
    parts = [p for p in host.split(".") if p]
    if not parts:
        return None
    if len(parts) >= 3 and ".".join(parts[-2:]) in _SECOND_LEVEL_TLDS:
        label = parts[-3]
    elif len(parts) >= 2:
        label = parts[-2]
    else:
        label = parts[0]
    label = re.sub(r"[^a-z0-9]", " ", label).strip()
    return label.title() or None


def _get_app_token():
    """Token app-only (client_credentials) se le credenziali sono nel .env, else None."""
    cid = config.REDDIT_CLIENT_ID
    secret = config.REDDIT_CLIENT_SECRET
    if not (cid and secret):
        return None
    try:
        resp = requests.post(
            TOKEN_URL,
            auth=(cid, secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("access_token")
    except (requests.RequestException, ValueError) as e:
        print(f"[reddit] token OAuth non ottenuto ({e}); provo l'accesso pubblico.")
        return None


def _fetch_listing(sub, per_sub, token):
    """Ritorna la lista di child post per un subreddit, o None se bloccato/errore."""
    headers = {"User-Agent": config.USER_AGENT}
    if token:
        headers["Authorization"] = f"bearer {token}"
        url = OAUTH_BASE.format(sub=sub)
    else:
        url = PUBLIC_BASE.format(sub=sub)
    try:
        resp = requests.get(
            url,
            params={"limit": min(per_sub, 100)},
            headers=headers,
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("children", [])
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        if code == 403 and not token:
            print("[reddit]   403 dall'endpoint pubblico: Reddit blocca lo scraping "
                  "da questo IP. Aggiungi REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET nel "
                  ".env (app gratuita) per un accesso affidabile.")
            return None
        print(f"[reddit]   r/{sub}: errore HTTP {code}, salto.")
        return []
    except (requests.RequestException, ValueError) as e:
        print(f"[reddit]   r/{sub}: errore, salto ({e})")
        return []


def fetch(limit=None, country=None):
    per_sub = limit if limit is not None else REDDIT_MAX_PER_SUB
    token = _get_app_token()
    print(f"[reddit] scarico i lanci recenti dai subreddit dei founder "
          f"({'API OAuth' if token else 'accesso pubblico best-effort'})...")

    records = []
    seen_hosts = set()
    for sub in SUBREDDITS:
        children = _fetch_listing(sub, per_sub, token)
        if children is None:
            break  # 403 pubblico: inutile insistere sugli altri subreddit
        added = 0
        for child in children:
            post = child.get("data", {})
            url = post.get("url_overridden_by_dest") or post.get("url")
            if not _is_product_url(url):
                continue
            host = _host(url)
            if host in seen_hosts:
                continue  # stesso sito ripostato su piu' subreddit
            seen_hosts.add(host)

            created = post.get("created_utc")
            source_date = (datetime.fromtimestamp(created, timezone.utc).isoformat()
                           if created else None)

            records.append({
                "company_name": _name_from_host(host),
                "website": url,
                "sector": None,
                "stage": "pre-seed (Reddit launch)",
                "founder_name": None,  # 'author' e' uno username, non un nome
                "email": None,
                "country": None,
                "source": "reddit",
                "source_date": source_date,  # per il segnale "lancio recente"
            })
            added += 1
            if added >= per_sub:
                break
        print(f"[reddit]   r/{sub}: {added} lanci con sito esterno.")

    print(f"[reddit] {len(records)} startup estratte da Reddit.")
    return records

"""Trova un'email di contatto leggendo DAVVERO il sito di una startup.

Questo modulo esiste per risolvere un bug grave: l'enrichment LLM "indovinava"
email plausibili ma inesistenti (es. Akara -> hello@akararobotics.com, mentre il
vero contatto sul sito reale akara.ai e' info@akara.ai). Qui non si inventa
nulla: si scarica l'HTML reale della home e di poche pagine contatti comuni, si
estraggono le email presenti nel testo e nei link mailto:, si scarta il rumore e
si preferisce un'email il cui dominio COMBACIA col dominio del sito. Se non si
trova niente di affidabile, si restituisce None (meglio vuoto che sbagliato).

Tutto via requests (no browser): veloce, economico, nessuna API key.
"""

import re
from urllib.parse import urlparse, urljoin

import requests

import config

# Pagine candidate (oltre alla home) dove tipicamente vive un contatto.
CANDIDATE_PATHS = ["/contact", "/contact-us", "/contacts", "/about", "/about-us", "/team"]

# UA browser reale: con un UA "custom" molti siti (Cloudflare & co.) chiudono
# la connessione o restituiscono 403, perdendo email che invece esistono.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MAILTO_RE = re.compile(r'mailto:([^"\'?>\s]+)', re.IGNORECASE)

# Local-part chiaramente di esempio/placeholder (es. il famoso "jenny.rosen" di
# Stripe, o nomi-finti nelle demo di localizzazione). Un'email da TESTO con uno
# di questi prefissi non e' un contatto reale.
PLACEHOLDER_LOCALS = {
    "jenny.rosen", "giovanna.verdi", "giovanna.rossi", "john.doe", "jane.doe",
    "mario.rossi", "name", "email", "you", "user", "username", "firstname",
}

# Domini di terzi / provider generici: un'email su questi NON e' un contatto
# aziendale verificato (e spesso e' rumore di tracker, esempi, librerie JS).
THIRD_PARTY_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com",
    "icloud.com", "me.com", "example.com", "example.org", "domain.com",
    "sentry.io", "sentry-next.wixpress.com", "wixpress.com", "wix.com",
    "godaddy.com", "cloudflare.com", "squarespace.com", "shopify.com",
    "your-email.com", "youremail.com", "email.com", "test.com",
    "schema.org", "w3.org", "sentry.wixpress.com",
}

# Prefissi locali (parte prima della @) tipici di un contatto reale, in ordine
# di preferenza: un founders@ vale piu' di un generico sales@.
PREFERRED_PREFIXES = ["founders", "founder", "hello", "hi", "contact", "team", "info", "press", "hq", "sales", "support"]

# Estensioni immagine/file: scartano i falsi positivi tipo "logo.png@2x" o
# email il cui dominio finisce con un'estensione di asset.
ASSET_TAIL_RE = re.compile(r"\.(png|jpg|jpeg|gif|svg|webp|css|js|ico|woff2?)$", re.IGNORECASE)


def _registrable_domain(host):
    """Dominio confrontabile: ultime due label dell'host (es. www.akara.ai ->
    akara.ai, mail.akara.co.uk -> co.uk non e' perfetto ma per il match ci basta
    confrontare il suffisso, vedi _same_site)."""
    if not host:
        return None
    host = host.lower().removeprefix("www.")
    return host


def _site_host(website):
    if not website:
        return None
    parsed = urlparse(website if "://" in website else f"https://{website}")
    return _registrable_domain(parsed.netloc)


def _same_site(email_domain, site_host):
    """True se l'email appartiene al sito (apex o sottodominio). Confronto
    permissivo sul suffisso cosi' info@mail.akara.ai combacia con akara.ai."""
    if not email_domain or not site_host:
        return False
    email_domain = email_domain.lower()
    site_host = site_host.lower()
    return email_domain == site_host or email_domain.endswith("." + site_host) or site_host.endswith("." + email_domain)


def _clean_candidate(email):
    email = email.strip().strip(".").lower()
    if ASSET_TAIL_RE.search(email):
        return None
    if email.count("@") != 1:
        return None
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        return None
    if domain in THIRD_PARTY_DOMAINS:
        return None
    # scarta local part che sono chiaramente hash/sentry/placeholder
    if len(local) > 40 or "@" in local:
        return None
    return email


def _is_role_email(email):
    """True se la local-part inizia con un prefisso-ruolo plausibile
    (info@, hello@, contact@, founders@...). Usato per accettare email trovate
    nel TESTO della pagina, dove i nomi-persona casuali sono quasi sempre
    placeholder o rumore."""
    local = email.split("@")[0]
    if local in PLACEHOLDER_LOCALS:
        return False
    return any(local == p or local.startswith(p) for p in PREFERRED_PREFIXES)


def _harvest(html):
    """Estrae le email candidate da una pagina HTML, distinguendo la fonte:

    - email in un link `mailto:` -> contatto INTENZIONALE, ci si fida.
    - email nel testo/markup -> accettata solo se ha un prefisso-ruolo
      (info/hello/contact/...), perche' altrimenti e' tipicamente un placeholder
      di esempio (es. jenny.rosen@stripe.com nelle demo) o rumore.

    Ritorna un set di email pulite e fidate.
    """
    found = set()
    for raw in MAILTO_RE.findall(html):
        # un mailto puo' contenere ?subject=..., gia' tagliato dalla regex
        c = _clean_candidate(requests.utils.unquote(raw))
        if c and c.split("@")[0] not in PLACEHOLDER_LOCALS:
            found.add(c)
    for raw in EMAIL_RE.findall(html):
        c = _clean_candidate(raw)
        if c and _is_role_email(c):
            found.add(c)
    return found


def _fetch(url):
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml"},
            timeout=config.REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        if resp.status_code == 200 and "text/html" in resp.headers.get("Content-Type", ""):
            return resp.text
    except requests.RequestException:
        return None
    return None


def _pick_best(candidates, site_host):
    """Sceglie la migliore email tra le candidate.

    1) Prima le email DEL DOMINIO DEL SITO (garanzia anti-invenzione).
    2) Tra queste, ordina per prefisso preferito (founders@ > hello@ > info@...).
    3) Se nessuna combacia col dominio del sito, NON si restituisce un'email di
       dominio estraneo: e' troppo rischioso (potrebbe essere il tracker di un
       fornitore). Si preferisce None.
    """
    same = [e for e in candidates if _same_site(e.split("@")[1], site_host)]
    if not same:
        return None

    def rank(email):
        local = email.split("@")[0]
        for i, pref in enumerate(PREFERRED_PREFIXES):
            if local == pref or local.startswith(pref):
                return i
        return len(PREFERRED_PREFIXES)

    return sorted(same, key=rank)[0]


def find_email(website):
    """Restituisce un'email di contatto VERIFICATA sul sito, o None.

    Verificata = effettivamente presente nell'HTML del sito e con un dominio che
    combacia col dominio del sito. Non viene mai inventata o dedotta.
    """
    site_host = _site_host(website)
    if not site_host:
        return None

    base = website if "://" in website else f"https://{website}"
    candidates = set()

    # Alcuni siti rispondono solo su www. (o solo sull'apex): si prova prima la
    # forma data, e se la home non scarica si tenta l'alternativa www/apex.
    parsed = urlparse(base)
    bases = [base]
    if parsed.netloc and not parsed.netloc.startswith("www."):
        bases.append(base.replace("://" + parsed.netloc, "://www." + parsed.netloc, 1))

    working_base = None
    for b in bases:
        if _fetch(b) is not None:
            working_base = b
            break
    if working_base is None:
        return None  # sito non raggiungibile: niente email inventata

    # Home prima, poi le pagine contatti comuni; ci si ferma appena si ha una
    # buona candidata del dominio del sito (per restare veloci).
    for path in [""] + CANDIDATE_PATHS:
        url = working_base if path == "" else urljoin(working_base, path)
        html = _fetch(url)
        if not html:
            continue
        candidates |= _harvest(html)
        best = _pick_best(candidates, site_host)
        if best:
            return best

    return _pick_best(candidates, site_host)


def enrich_missing_emails_by_crawl(records):
    """Riempie l'email mancante leggendo il sito reale di ogni record.

    Stampa avanzamento i/N cosi' la dashboard puo' mostrare "Checking site X of N"
    (i colleghi su Windows, senza terminale, capiscono che sta lavorando)."""
    targets = [r for r in records if r.get("website") and not r.get("email")]
    if not targets:
        print("[email] nessun sito da controllare (tutte le email gia' presenti o nessun sito).")
        return records

    print(f"[email] cerco email di contatto sui siti reali di {len(targets)} startup...")
    found = 0
    for i, record in enumerate(targets, 1):
        email = find_email(record.get("website"))
        if email:
            record["email"] = email
            found += 1
        if i % 5 == 0 or i == len(targets):
            print(f"[email]   {i}/{len(targets)} controllati, {found} email trovate.")

    print(f"[email] trovate {found} email verificate sui siti (le altre restano vuote, non inventate).")
    return records

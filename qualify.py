"""Qualificazione pre-seed: decide quali startup TENERE.

Requisito: consegnare SOLO pre-seed (bootstrapped / friends&family / angel /
pre-seed), escludendo chi ha gia' raccolto un round oltre il pre-seed (seed o
superiore), e restare su US / Canada / Europa.

Non cancella nulla: gli scartati restano nel DB con `qualified=0` e un
`exclude_reason` leggibile, cosi' il risultato e' auditabile (il capo puo'
vedere PERCHE' una startup e' stata esclusa). La dashboard mostra di default
solo i qualificati.

Segnali usati, in ordine di autorita':
  1. Dati di funding strutturati (Crunchbase/Dealroom, se key) -> gate certo.
  2. Segnali sul testo reale del sito (LLM + regex) -> gate euristico.
  3. Stage dichiarato dalla fonte/LLM.
  4. Geografia (paese o TLD).
"""

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import config

# --- Geografia target: US, Canada, Europa ---------------------------------
# Nomi (match come sottostringa, es. "san francisco, united states") e codici
# ISO2 (match come token isolato, per non prendere "is" dentro una parola).
_NA_NAMES = {"united states", "united states of america", "usa", "u.s.a", "america", "canada"}
_EU_NAMES = {
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czech", "czechia",
    "denmark", "estonia", "finland", "france", "germany", "greece", "hungary",
    "ireland", "italy", "latvia", "lithuania", "luxembourg", "malta",
    "netherlands", "poland", "portugal", "romania", "slovakia", "slovenia",
    "spain", "sweden", "united kingdom", "great britain", "england", "scotland",
    "wales", "norway", "switzerland", "iceland", "liechtenstein", "ukraine",
    "serbia", "montenegro", "north macedonia", "albania", "bosnia", "moldova",
}
TARGET_COUNTRY_NAMES = _NA_NAMES | _EU_NAMES
TARGET_ISO2 = {
    "us", "ca", "at", "be", "bg", "hr", "cy", "cz", "dk", "ee", "fi", "fr",
    "de", "gr", "hu", "ie", "it", "lv", "lt", "lu", "mt", "nl", "pl", "pt",
    "ro", "sk", "si", "es", "se", "gb", "uk", "no", "ch", "is", "li", "ua",
    "rs", "me", "mk", "al", "ba", "md",
}
# Paesi/TLD chiaramente FUORI target: escludono con certezza.
NON_TARGET_NAMES = {
    "india", "singapore", "australia", "new zealand", "china", "hong kong",
    "japan", "south korea", "korea", "taiwan", "indonesia", "malaysia",
    "thailand", "vietnam", "philippines", "brazil", "argentina", "chile",
    "colombia", "mexico", "nigeria", "kenya", "egypt", "south africa",
    "israel", "united arab emirates", "uae", "saudi arabia", "pakistan",
    "bangladesh", "turkey", "russia",
}
NON_TARGET_TLDS = {
    "in", "sg", "au", "nz", "cn", "hk", "jp", "kr", "tw", "id", "my", "th",
    "vn", "ph", "br", "ar", "cl", "co", "mx", "ng", "ke", "eg", "za", "il",
    "ae", "sa", "pk", "bd", "tr", "ru",
}
# TLD europei/nordamericani -> target. (.com/.io/.ai/.co/.org sono ambigui.)
TARGET_TLDS = {"us", "ca"} | (TARGET_ISO2 - {"us", "ca"})

# Fonti che per costruzione portano startup molto early (alzano la confidence).
PRESEED_SOURCES = {"antler", "entrepreneur_first", "rockstart", "betalist", "hackernews"}

# Segnali di funding OLTRE il pre-seed nel testo del sito. "seed" e' escluso
# quando preceduto da "pre-"/"pre " (vedi _beyond_funding_in_text).
_BEYOND_FUNDING_RE = re.compile(
    r"seed\s+(?:round|funding|financing|investment|stage)|series\s*[a-f]\b",
    re.IGNORECASE,
)


def _tld(website):
    if not website:
        return None
    host = urlparse(website if "://" in website else f"https://{website}").netloc.lower()
    host = host.split(":")[0]
    return host.rsplit(".", 1)[-1] if "." in host else None


def _geo_status(country, website):
    """Ritorna (status, known) con status in {"target","non_target","unknown"}.
    known=True se abbiamo capito il paese (per la confidence)."""
    c = (country or "").strip().lower()
    if c:
        if any(name in c for name in TARGET_COUNTRY_NAMES):
            return "target", True
        tokens = [t for t in re.split(r"[^a-z]+", c) if t]
        if any(t in TARGET_ISO2 for t in tokens):
            return "target", True
        if any(name in c for name in NON_TARGET_NAMES):
            return "non_target", True
        # paese presente ma non riconosciuto: non escludiamo sul geo (il filtro
        # forte e' il funding); restiamo prudenti tenendolo con geo "unknown".
    tld = _tld(website)
    if tld in TARGET_TLDS:
        return "target", True
    if tld in NON_TARGET_TLDS:
        return "non_target", True
    return "unknown", False


def _beyond_funding_in_text(text):
    """Prima citazione di un round seed+ nel testo, o None. Ignora i match che
    fanno parte di 'pre-seed'/'pre seed'."""
    if not text:
        return None
    t = text.lower()
    for m in _BEYOND_FUNDING_RE.finditer(t):
        if "pre" in t[max(0, m.start() - 4):m.start()]:
            continue
        return m.group(0)
    return None


def _funding_type_beyond(ft):
    """True se il last_funding_type (Crunchbase/Dealroom) e' oltre il pre-seed."""
    ft = (ft or "").strip().lower()
    if ft in ("", "pre_seed", "pre-seed", "angel", "grant", "non_equity_assistance",
              "equity_crowdfunding", "product_crowdfunding", "convertible_note"):
        return False
    return ft.startswith("series") or ft in (
        "seed", "private_equity", "post_ipo_equity", "post_ipo_debt",
        "secondary_market", "corporate_round", "debt_financing",
    )


def _stage_beyond_preseed(stage):
    """True se lo stage dichiarato (fonte o LLM) indica seed o superiore."""
    s = (stage or "").lower().replace("_", " ").replace("-", " ")
    if not s or "pre seed" in s or "preseed" in s:
        return False
    return ("series a" in s or "series b" in s or "series c" in s
            or bool(re.search(r"\bseed\b", s)))


def _recent_launch(record):
    d = record.get("source_date")
    if not d:
        return False
    try:
        dt = datetime.fromisoformat(str(d).replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).days <= 56


def _confidence(record, geo_known):
    score = 0
    if (record.get("source") or "").lower() in PRESEED_SOURCES:
        score += 1
    if _recent_launch(record):
        score += 1
    score += 1 if geo_known else -1
    ts = record.get("team_size_estimate")
    if isinstance(ts, int) and ts > 20:
        score -= 1
    if score >= 2:
        return "high"
    if score <= 0:
        return "low"
    return "medium"


def _exclude(reason, confidence):
    return {"qualified": False, "exclude_reason": reason, "preseed_confidence": confidence}


def qualify_record(record):
    """Ritorna {qualified, exclude_reason, preseed_confidence} per un record."""
    # 1) Funding DB autoritativo.
    if _funding_type_beyond(record.get("last_funding_type")):
        return _exclude(f"funding round '{record.get('last_funding_type')}' oltre il pre-seed", "high")
    total = record.get("total_raised")
    if isinstance(total, (int, float)) and total > config.SEED_THRESHOLD_USD:
        return _exclude(f"raccolti oltre {config.SEED_THRESHOLD_USD // 1_000_000}M$", "high")

    # 2) Segnali dal sito reale (LLM + regex sul testo).
    if record.get("raised_beyond_preseed") is True:
        return _exclude("il sito indica un round seed o superiore", "medium")
    sig = _beyond_funding_in_text(record.get("_site_text"))
    if sig:
        return _exclude(f"menzione di funding sul sito: '{sig}'", "medium")

    # 3) Stage dichiarato.
    if _stage_beyond_preseed(record.get("stage")):
        return _exclude(f"stage '{record.get('stage')}' oltre il pre-seed", "medium")

    # 4) Geografia.
    geo, geo_known = _geo_status(record.get("country"), record.get("website"))
    if geo == "non_target":
        where = record.get("country") or _tld(record.get("website")) or "?"
        return _exclude(f"fuori dall'area target US/Canada/Europa ({where})", "high")

    return {"qualified": True, "exclude_reason": None, "preseed_confidence": _confidence(record, geo_known)}


def qualify_records(records):
    """Valorizza qualified / exclude_reason / preseed_confidence su ogni record."""
    kept = 0
    for record in records:
        res = qualify_record(record)
        record["qualified"] = 1 if res["qualified"] else 0
        record["exclude_reason"] = res["exclude_reason"]
        record["preseed_confidence"] = res["preseed_confidence"]
        if res["qualified"]:
            kept += 1
    print(f"[qualify] {kept}/{len(records)} startup qualificate come pre-seed "
          f"(le {len(records) - kept} escluse restano nel DB col motivo).")
    return records

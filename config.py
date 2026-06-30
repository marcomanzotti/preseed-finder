import os
from pathlib import Path


def _load_dotenv():
    """Carica variabili da un file .env nella root del progetto, se presente.
    Non sovrascrive variabili già impostate nell'ambiente (l'ambiente ha priorità)."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()

HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "").strip()
PRODUCTHUNT_TOKEN = os.environ.get("PRODUCTHUNT_TOKEN", "").strip()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# Fonti a pagamento (opt-in): usate SOLO se la rispettiva key e' presente nel
# .env, altrimenti la fonte si auto-salta (come Product Hunt col suo token).
# Sono le fonti con piu' dati su pre-seed/founder, ma costano: chi vuole la
# massima coverage e accetta il costo mette la key qui.
CRUNCHBASE_API_KEY = os.environ.get("CRUNCHBASE_API_KEY", "").strip()
DEALROOM_API_KEY = os.environ.get("DEALROOM_API_KEY", "").strip()

# Provider LLM: "anthropic" (Claude) o "gemini" (Google, più economico).
# Se LLM_PROVIDER non e' impostato esplicitamente, lo si deduce da quale
# chiave e' presente nel .env, cosi' un .env con solo ANTHROPIC_API_KEY usa
# Claude e uno con solo GEMINI_API_KEY usa Gemini, senza bisogno di settare
# anche LLM_PROVIDER a mano (causa di un bug: con provider di default fisso
# a "gemini", un .env con solo ANTHROPIC_API_KEY restava silenziosamente
# senza enrichment perche' cercava la chiave Gemini mancante).
_explicit_provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
if _explicit_provider:
    LLM_PROVIDER = _explicit_provider
elif GEMINI_API_KEY and not ANTHROPIC_API_KEY:
    LLM_PROVIDER = "gemini"
elif ANTHROPIC_API_KEY and not GEMINI_API_KEY:
    LLM_PROVIDER = "anthropic"
else:
    LLM_PROVIDER = "gemini"  # default se entrambe o nessuna chiave e' presente

# Modello per l'enrichment LLM (se provider="anthropic").
# Haiku 4.5: veloce ed economico, adatto a task di estrazione/classificazione ad alto volume.
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-4-5").strip()

# Modello Gemini (se provider="gemini"). Flash Lite e' il piu' economico.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-lite").strip()

REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; PreseedFinder/1.0)"

HUNTER_MONTHLY_LIMIT = 25

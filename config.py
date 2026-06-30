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

# Modello per l'enrichment LLM. Haiku 4.5: veloce ed economico, adatto a un
# task di estrazione/classificazione ad alto volume.
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-4-5").strip()

REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; PreseedFinder/1.0)"

HUNTER_MONTHLY_LIMIT = 25

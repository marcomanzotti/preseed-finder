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

# Provider LLM: "anthropic" (Claude, default) o "gemini" (Google Gemini, più economico).
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()

# Modello per l'enrichment LLM (se provider="anthropic").
# Haiku 4.5: veloce ed economico, adatto a task di estrazione/classificazione ad alto volume.
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-4-5").strip()

# Modello Gemini (se provider="gemini"). Gemini 2.0 Flash è il più economico.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip()

REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; PreseedFinder/1.0)"

HUNTER_MONTHLY_LIMIT = 25

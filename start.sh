#!/usr/bin/env bash
# Setup completo + avvio in locale. Uso: ./start.sh
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "[start] creo virtualenv..."
  python3 -m venv .venv
fi

echo "[start] installo dipendenze..."
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "[start] installo Chromium per Playwright (solo la prima volta puo' richiedere un minuto)..."
.venv/bin/playwright install chromium

if [ ! -f ".env" ]; then
  echo "[start] nessun file .env trovato, lo creo da .env.example (inserisci le tue API key)."
  cp .env.example .env
fi

echo "[start] avvio il server su http://127.0.0.1:5050 ..."
.venv/bin/python webapp.py

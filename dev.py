#!/usr/bin/env python3
"""Dev launcher for VSCode: run with Play button, opens dashboard in browser.

Avvia Flask + apre il browser su http://127.0.0.1:5050 direttamente (senza
pywebview). Usa le API key dal .env locale. Ctrl+C per fermare.
"""

import os
import sys
import webbrowser
import time
from pathlib import Path

# Prepara l'ambiente
os.chdir(Path(__file__).parent)
if not Path(".venv").exists():
    print("[dev] Creating venv...")
    os.system("python3 -m venv .venv")
    os.system(".venv/bin/pip install -q --upgrade pip")
    os.system(".venv/bin/pip install -q -r requirements.txt")

if not Path(".env").exists() and Path(".env.example").exists():
    print("[dev] Creating .env from .env.example (edit it with your Anthropic API key)")
    os.system("cp .env.example .env")

# Avvia il server
print("[dev] Starting dashboard on http://127.0.0.1:5050 ...")
print("[dev] Press Ctrl+C to stop")

import threading
import webapp

server = threading.Thread(
    target=lambda: webapp.app.run(host="127.0.0.1", port=5050, debug=False, use_reloader=False),
    daemon=True
)
server.start()

# Apri il browser
time.sleep(1.5)
webbrowser.open("http://127.0.0.1:5050/")

# Tieni il processo attivo
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n[dev] Stopping...")

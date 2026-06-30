#!/usr/bin/env bash
# Genera "Preseed Finder.app" cliccabile (con icona) per Mac, usando PyInstaller.
#
# Versione precedente: un bundle .app fatto a mano con uno script bash come
# CFBundleExecutable, che creava la venv al primo lancio. Lanciato da terminale
# funzionava, ma lanciato con un doppio click da Finder (LaunchServices) restava
# silenziosamente fermo: l'ambiente di LaunchServices ha un PATH/HOME minimale e
# senza terminale non c'era modo di vedere l'errore. PyInstaller risolve il
# problema impacchettando l'interprete Python e tutte le dipendenze in un
# eseguibile nativo autosufficiente, che LaunchServices sa avviare correttamente.
#
# Il risultato (dist/Preseed Finder.app) non e' versionato (vedi .gitignore);
# si rigenera con questo script. Eventuali errori di avvio finiscono nel file
# preseed_finder.log accanto all'eseguibile dentro al bundle.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "[build] Creo virtualenv..."
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
fi

./.venv/bin/pip show pyinstaller >/dev/null 2>&1 || ./.venv/bin/pip install -q pyinstaller
./.venv/bin/pip install -q -r requirements.txt

rm -rf build dist "Preseed Finder.app"

./.venv/bin/pyinstaller --noconfirm --clean --windowed --onedir \
  --name "Preseed Finder" \
  --icon assets/app.icns \
  --add-data ".env.example:." \
  --hidden-import webapp \
  --hidden-import main \
  --hidden-import store \
  --hidden-import dedupe \
  --hidden-import config \
  --hidden-import enrich \
  --hidden-import email_finder \
  --hidden-import llm_enrich \
  --hidden-import sources \
  --hidden-import sources.yc \
  --hidden-import sources.antler \
  --hidden-import sources.cordis \
  --hidden-import sources.producthunt \
  --hidden-import sources.rockstart \
  --hidden-import sources.entrepreneur_first \
  --hidden-import sources.betalist \
  --hidden-import sources.crunchbase \
  app.py

# Copia il bundle finale nella root del progetto, dove l'utente se lo aspetta
# (dist/ resta come output grezzo di PyInstaller).
rm -rf "Preseed Finder.app"
cp -R "dist/Preseed Finder.app" "Preseed Finder.app"

echo ""
echo "Created 'Preseed Finder.app' — double-click it in Finder to launch."
echo "If it doesn't seem to start, check the log file inside the bundle:"
echo "  Preseed Finder.app/Contents/MacOS/preseed_finder.log"

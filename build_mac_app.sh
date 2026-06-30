#!/usr/bin/env bash
# Genera "Preseed Finder.app" cliccabile (con icona) per i test su Mac.
# Doppio click sul .app -> prepara la venv se manca -> avvia app.py (finestra
# nativa pywebview), senza mostrare un terminale. Il .app stesso non e'
# versionato (vedi .gitignore); si rigenera con questo script.
set -euo pipefail
cd "$(dirname "$0")"

APP="Preseed Finder.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp assets/app.icns "$APP/Contents/Resources/app.icns"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Preseed Finder</string>
  <key>CFBundleDisplayName</key><string>Preseed Finder</string>
  <key>CFBundleIdentifier</key><string>com.preseedfinder.app</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundleIconFile</key><string>app.icns</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/launch" <<'SH'
#!/usr/bin/env bash
set -e
APP_PATH="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$APP_PATH"
if [ ! -d ".venv" ]; then
  /usr/bin/env python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  cp .env.example .env
fi
exec ./.venv/bin/python app.py
SH
chmod +x "$APP/Contents/MacOS/launch"
touch "$APP"
echo "Created $APP — double-click it in Finder to launch."

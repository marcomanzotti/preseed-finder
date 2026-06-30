"""Launcher dell'app desktop Preseed Finder.

Avvia il server Flask (webapp.py) in un thread e apre una finestra nativa
(pywebview) sulla dashboard: e' questo il file che viene impacchettato in un
eseguibile cliccabile (Preseed Finder.exe su Windows, .command/.app su Mac),
cosi' un collega lo lancia con un doppio click senza terminale.

Al primo avvio scarica Chromium per Playwright (non viene impacchettato perche'
pesa 300+ MB); il download avviene una sola volta nella cache locale.
"""

import os
import sys
import threading
import socket
import time
import traceback

HOST = "127.0.0.1"
PORT = 5050
URL = f"http://{HOST}:{PORT}/"


def _app_dir():
    """Cartella dell'app: accanto all'eseguibile se impacchettato (PyInstaller),
    altrimenti accanto a questo file. Qui vivono .env e preseed.db, in modo che
    siano scrivibili senza permessi admin su una macchina d'ufficio."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _setup_logging():
    """Quando l'app e' lanciata con un doppio click (niente terminale), stdout
    e stderr non sono visibili da nessuna parte: ridirigerli su un file di log
    accanto all'eseguibile e' l'unico modo per poter diagnosticare un crash."""
    log_path = os.path.join(_app_dir(), "preseed_finder.log")
    log_file = open(log_path, "a", buffering=1)
    sys.stdout = log_file
    sys.stderr = log_file
    print(f"\n=== Preseed Finder avviato {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    return log_path


def _show_error_dialog(message):
    """Mostra un alert nativo visibile all'utente (niente terminale = niente
    altro modo per fargli sapere che qualcosa non ha funzionato)."""
    try:
        if sys.platform == "darwin":
            safe = message.replace('"', "'").replace("\\", "/")
            os.system(f'osascript -e \'display alert "Preseed Finder" message "{safe}"\' >/dev/null 2>&1')
        elif sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "Preseed Finder", 0x10)
    except Exception:
        pass


def _ensure_env_file():
    """Al primo avvio, crea .env da .env.example se manca, cosi' l'utente ha
    un file da compilare con la propria chiave API (la dashboard mostra poi un
    banner se la chiave manca ancora, con un campo per inserirla senza dover
    aprire/modificare file a mano)."""
    env_path = os.path.join(_app_dir(), ".env")
    example_path = os.path.join(_app_dir(), ".env.example")
    if not os.path.exists(env_path) and os.path.exists(example_path):
        import shutil
        shutil.copy(example_path, env_path)
        print("[app] Created .env from .env.example (no API key configured yet).")


def _ensure_chromium():
    """Installa Chromium di Playwright al primo avvio, se manca."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exe = p.chromium.executable_path
            if exe and os.path.exists(exe):
                return  # gia' presente
    except Exception:
        pass
    print("[app] Downloading the browser engine (first run only, ~150 MB)...")
    try:
        from playwright.__main__ import main as pw_main
        argv_backup = sys.argv
        sys.argv = ["playwright", "install", "chromium"]
        try:
            pw_main()
        except SystemExit:
            pass
        finally:
            sys.argv = argv_backup
    except Exception as e:
        print(f"[app] Could not auto-install Chromium: {e}")


def _wait_for_server(timeout=15):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((HOST, PORT), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _run_server():
    # Importa qui per stare dentro al thread (e dopo aver settato la cwd).
    import webapp
    webapp.app.run(host=HOST, port=PORT, debug=False, use_reloader=False)


def main():
    os.chdir(_app_dir())
    log_path = _setup_logging()

    try:
        _ensure_env_file()
        _ensure_chromium()

        server = threading.Thread(target=_run_server, daemon=True)
        server.start()

        if not _wait_for_server():
            print("[app] Server did not start in time.")
            _show_error_dialog(f"The app failed to start. Check the log file:\n{log_path}")
            return

        try:
            import webview
            webview.create_window("Preseed Finder", URL, width=1280, height=860)
            webview.start()
        except Exception as e:
            # Fallback: se pywebview non e' disponibile, apri nel browser di sistema.
            print(f"[app] Native window unavailable ({e}); opening in browser instead.")
            print(traceback.format_exc())
            import webbrowser
            webbrowser.open(URL)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
    except Exception:
        print("[app] FATAL ERROR:")
        print(traceback.format_exc())
        _show_error_dialog(f"Preseed Finder crashed on startup. Check the log file:\n{log_path}")
        raise


if __name__ == "__main__":
    main()

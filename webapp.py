"""Interfaccia web minimale per lanciare la pipeline e scaricare il CSV
risultante, senza usare la riga di comando."""

import io
import sys
import threading
import contextlib
from pathlib import Path

from flask import Flask, request, jsonify, send_file, Response

import main as pipeline

app = Flask(__name__)

_existing_csv = Path(__file__).parent / "startups.csv"

STATE = {
    "running": False,
    "log": "",
    "output_path": str(_existing_csv) if _existing_csv.exists() else None,
    "error": None,
}
LOCK = threading.Lock()


class _LogStream(io.TextIOBase):
    def write(self, s):
        with LOCK:
            STATE["log"] += s
        return len(s)


def _run_pipeline(sources, limit, enrich_llm, batches):
    with LOCK:
        STATE["running"] = True
        STATE["log"] = ""
        STATE["error"] = None
        STATE["output_path"] = None

    output_path = str(Path(__file__).parent / "startups.csv")
    argv_backup = sys.argv
    try:
        argv = ["main.py", "--sources", sources, "--output", output_path]
        if limit:
            argv += ["--limit", str(limit)]
        if enrich_llm:
            argv += ["--enrich-llm"]
        if batches:
            argv += ["--batches", batches]
        sys.argv = argv

        stream = _LogStream()
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            pipeline.main()

        with LOCK:
            STATE["output_path"] = output_path
    except Exception as e:
        with LOCK:
            STATE["error"] = str(e)
            STATE["log"] += f"\n[webapp] ERRORE: {e}\n"
    finally:
        sys.argv = argv_backup
        with LOCK:
            STATE["running"] = False


@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


@app.route("/start", methods=["POST"])
def start():
    with LOCK:
        if STATE["running"]:
            return jsonify({"ok": False, "error": "Una run e' gia' in corso."}), 409

    data = request.get_json(force=True) or {}
    sources = data.get("sources") or "yc,antler,cordis,producthunt"
    limit = data.get("limit") or None
    enrich_llm = bool(data.get("enrich_llm"))
    batches = data.get("batches") or None

    thread = threading.Thread(
        target=_run_pipeline, args=(sources, limit, enrich_llm, batches), daemon=True
    )
    thread.start()
    return jsonify({"ok": True})


@app.route("/status")
def status():
    with LOCK:
        return jsonify({
            "running": STATE["running"],
            "log": STATE["log"],
            "ready": STATE["output_path"] is not None,
            "error": STATE["error"],
        })


@app.route("/download")
def download():
    with LOCK:
        path = STATE["output_path"]
    if not path or not Path(path).exists():
        return jsonify({"ok": False, "error": "Nessun CSV pronto."}), 404
    return send_file(path, as_attachment=True, download_name="startups.csv")


INDEX_HTML = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<title>Preseed Finder</title>
<style>
  body { font-family: -apple-system, sans-serif; max-width: 720px; margin: 40px auto; padding: 0 20px; color: #222; }
  h1 { font-size: 1.4rem; }
  fieldset { border: 1px solid #ddd; border-radius: 8px; margin-bottom: 16px; padding: 12px 16px; }
  label { display: block; margin: 8px 0 4px; font-size: 0.9rem; }
  input[type=text], input[type=number] { width: 100%; padding: 6px; box-sizing: border-box; }
  button { background: #111; color: #fff; border: none; padding: 10px 18px; border-radius: 6px; cursor: pointer; font-size: 0.95rem; }
  button:disabled { background: #999; cursor: not-allowed; }
  pre { background: #0b0b0b; color: #ddd; padding: 12px; border-radius: 8px; max-height: 400px; overflow-y: auto; font-size: 0.8rem; white-space: pre-wrap; }
  .row { display: flex; align-items: center; gap: 8px; }
  a.download { display: inline-block; margin-top: 12px; }
</style>
</head>
<body>
<h1>Preseed Finder</h1>
<p>Trova startup pre-seed/early-stage da fonti pubbliche (YC, Antler, CORDIS/EIC, Product Hunt) e produce un CSV con i contatti trovati.</p>

<fieldset>
  <legend>Opzioni</legend>
  <label>Fonti (separate da virgola)</label>
  <input type="text" id="sources" value="yc,antler,cordis,producthunt">

  <label>Limite per fonte (vuoto = nessun limite)</label>
  <input type="number" id="limit" placeholder="es. 50">

  <label>Batch YC (vuoto = ultimi 3 di default)</label>
  <input type="text" id="batches" placeholder="es. Summer 2025,Winter 2025">

  <div class="row" style="margin-top:12px;">
    <input type="checkbox" id="enrich_llm">
    <label style="margin:0;" for="enrich_llm">Arricchimento LLM (stage/settore/email/founder via Claude — richiede ANTHROPIC_API_KEY, piu' lento)</label>
  </div>
</fieldset>

<button id="startBtn" onclick="start()">Avvia ricerca</button>
<a id="downloadLink" class="download" style="display:none;" href="/download">Scarica startups.csv</a>

<h3>Log</h3>
<pre id="log">In attesa...</pre>

<script>
let polling = null;

async function start() {
  document.getElementById('startBtn').disabled = true;
  document.getElementById('downloadLink').style.display = 'none';
  document.getElementById('log').textContent = 'Avvio in corso...\\n';

  const body = {
    sources: document.getElementById('sources').value,
    limit: document.getElementById('limit').value || null,
    batches: document.getElementById('batches').value || null,
    enrich_llm: document.getElementById('enrich_llm').checked,
  };
  const resp = await fetch('/start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const data = await resp.json();
    document.getElementById('log').textContent = 'Errore: ' + data.error;
    document.getElementById('startBtn').disabled = false;
    return;
  }
  polling = setInterval(poll, 1000);
}

async function poll() {
  const resp = await fetch('/status');
  const data = await resp.json();
  document.getElementById('log').textContent = data.log || '...';
  document.getElementById('log').scrollTop = document.getElementById('log').scrollHeight;
  if (!data.running) {
    clearInterval(polling);
    document.getElementById('startBtn').disabled = false;
    if (data.ready) {
      document.getElementById('downloadLink').style.display = 'inline-block';
    }
  }
}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)

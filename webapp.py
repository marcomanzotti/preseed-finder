"""Dashboard web locale per Preseed Finder.

Mostra le startup accumulate nel DB SQLite (store.py), evidenzia cosa e'
cambiato dall'ultima run (badge + banner notifiche), permette di filtrarle,
di contattarle via mailto e di tracciarne lo stato di contatto.

Tutta l'interfaccia visibile e' in INGLESE perche' usata da colleghi non
italiani; commenti e log interni restano in italiano.
"""

import io
import sys
import json
import threading
import contextlib
from pathlib import Path

from flask import Flask, request, jsonify, send_file, Response

import main as pipeline
import store

app = Flask(__name__)

DB_PATH = store.DEFAULT_DB_PATH
_existing_csv = Path(__file__).parent / "startups.csv"

# Template precompilato per il mailto (in inglese).
MAIL_SUBJECT = "Reaching out from [Your Company]"
MAIL_BODY = (
    "Hi {founder},\\n\\n"
    "I came across {company} and was impressed by what you're building. "
    "We work with early-stage startups and I'd love to find 15 minutes to connect.\\n\\n"
    "Best regards,"
)

STATE = {
    "running": False,
    "log": "",
    "error": None,
    "last_report": None,  # dict del ChangeReport dell'ultima run via UI
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
        STATE["last_report"] = None

    output_path = str(Path(__file__).parent / "startups.csv")
    argv_backup = sys.argv
    try:
        argv = ["main.py", "--sources", sources, "--output", output_path, "--db", DB_PATH]
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
            STATE["last_report"] = store.last_run_summary(DB_PATH)
    except Exception as e:
        with LOCK:
            STATE["error"] = str(e)
            STATE["log"] += f"\n[webapp] ERROR: {e}\n"
    finally:
        sys.argv = argv_backup
        with LOCK:
            STATE["running"] = False


# ----------------------------- API -----------------------------

@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


@app.route("/api/startups")
def api_startups():
    filters = {
        "sector": request.args.get("sector") or None,
        "country": request.args.get("country") or None,
        "stage": request.args.get("stage") or None,
        "source": request.args.get("source") or None,
        "has_email": request.args.get("has_email") == "1",
        "only_new": request.args.get("only_new") == "1",
    }
    rows = store.get_startups(DB_PATH, filters)
    return jsonify({
        "startups": rows,
        "summary": store.last_run_summary(DB_PATH),
        "facets": {
            "sector": store.distinct_values("sector", DB_PATH),
            "country": store.distinct_values("country", DB_PATH),
            "stage": store.distinct_values("stage", DB_PATH),
            "source": store.distinct_values("source", DB_PATH),
        },
        "mail": {"subject": MAIL_SUBJECT, "body": MAIL_BODY},
    })


@app.route("/startup/<path:key>/status", methods=["POST"])
def update_status(key):
    data = request.get_json(force=True) or {}
    status = data.get("status")
    if status not in ("To contact", "Contacted", "Replied"):
        return jsonify({"ok": False, "error": "Invalid status."}), 400
    ok = store.set_contact_status(key, status, DB_PATH)
    return jsonify({"ok": ok})


@app.route("/start", methods=["POST"])
def start():
    with LOCK:
        if STATE["running"]:
            return jsonify({"ok": False, "error": "A search is already running."}), 409

    data = request.get_json(force=True) or {}
    sources = data.get("sources") or "yc,antler,cordis,producthunt,rockstart"
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
            "error": STATE["error"],
            "report": STATE["last_report"],
        })


@app.route("/download")
def download():
    if not _existing_csv.exists():
        return jsonify({"ok": False, "error": "No CSV available yet."}), 404
    return send_file(str(_existing_csv), as_attachment=True, download_name="startups.csv")


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Preseed Finder</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --line:#e4e7eb; --ink:#1c2430; --muted:#6b7480; --accent:#2563eb; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin:0; background:var(--bg); color:var(--ink); }
  header { background:var(--card); border-bottom:1px solid var(--line); padding:16px 24px; display:flex; align-items:center; justify-content:space-between; }
  header h1 { font-size:1.25rem; margin:0; }
  header .sub { color:var(--muted); font-size:.85rem; }
  main { max-width:1180px; margin:0 auto; padding:20px 24px 60px; }
  .banner { background:#ecf3ff; border:1px solid #c7dbff; color:#1e3a8a; border-radius:10px; padding:12px 16px; margin-bottom:18px; font-size:.9rem; display:none; }
  .banner.show { display:block; }
  .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-bottom:14px; }
  .toolbar select, .toolbar input[type=text] { padding:7px 9px; border:1px solid var(--line); border-radius:8px; background:#fff; font-size:.85rem; }
  .toolbar label.chk { font-size:.85rem; color:var(--muted); display:flex; align-items:center; gap:5px; }
  .count { margin-left:auto; color:var(--muted); font-size:.85rem; }
  button.primary { background:var(--accent); color:#fff; border:none; padding:9px 16px; border-radius:8px; cursor:pointer; font-size:.9rem; font-weight:600; }
  button.primary:disabled { background:#9bb4e8; cursor:not-allowed; }
  button.ghost { background:#fff; border:1px solid var(--line); padding:8px 12px; border-radius:8px; cursor:pointer; font-size:.85rem; }
  table { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
  th, td { text-align:left; padding:10px 12px; border-bottom:1px solid var(--line); font-size:.86rem; vertical-align:middle; }
  th { background:#fafbfc; color:var(--muted); font-weight:600; font-size:.78rem; text-transform:uppercase; letter-spacing:.03em; cursor:pointer; user-select:none; }
  tr:last-child td { border-bottom:none; }
  td.company { font-weight:600; }
  td.company a { color:var(--ink); text-decoration:none; }
  td.company a:hover { text-decoration:underline; }
  .badge { display:inline-block; font-size:.68rem; font-weight:700; padding:2px 7px; border-radius:20px; margin-left:6px; vertical-align:middle; }
  .badge.NEW { background:#dcfce7; color:#166534; }
  .badge.contact { background:#fef3c7; color:#92400e; }
  .badge.change { background:#e0e7ff; color:#3730a3; }
  .mail-btn { display:inline-block; padding:5px 10px; border-radius:7px; background:var(--accent); color:#fff; text-decoration:none; font-size:.8rem; }
  .mail-btn.disabled { background:#cbd5e1; pointer-events:none; }
  select.status { padding:5px 7px; border-radius:7px; border:1px solid var(--line); font-size:.8rem; }
  select.status[data-v="Contacted"] { background:#fef9c3; }
  select.status[data-v="Replied"] { background:#dcfce7; }
  .muted { color:var(--muted); font-size:.8rem; }
  details.advanced { margin-top:26px; background:var(--card); border:1px solid var(--line); border-radius:10px; padding:0 16px; }
  details.advanced summary { cursor:pointer; padding:14px 0; font-weight:600; }
  .adv-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; padding-bottom:14px; }
  .adv-grid label { font-size:.82rem; color:var(--muted); display:block; margin-bottom:4px; }
  .adv-grid input[type=text], .adv-grid input[type=number] { width:100%; padding:7px; border:1px solid var(--line); border-radius:8px; }
  .progress-container { display:none; margin-top:20px; }
  .progress-container.show { display:block; }
  .progress-status { font-size:.85rem; color:var(--muted); margin-bottom:8px; }
  .progress-bar { height:6px; background:var(--line); border-radius:4px; overflow:hidden; }
  .progress-bar-fill { height:100%; background:linear-gradient(90deg, var(--accent), #10b981); animation:pulse 1.5s infinite; width:0%; }
  @keyframes pulse { 0%,100%{ opacity:1 } 50%{ opacity:.6 } }
  .spinner { display:inline-block; width:14px; height:14px; border:2px solid var(--line); border-top:2px solid var(--accent); border-radius:50%; animation:spin .8s linear infinite; margin-right:6px; }
  @keyframes spin { to{ transform:rotate(360deg) } }
  pre#log { background:#0b0f17; color:#cbd5e1; padding:12px; border-radius:8px; max-height:240px; overflow:auto; font-size:.76rem; white-space:pre-wrap; margin-top:10px; }
  .empty { text-align:center; padding:40px; color:var(--muted); }
</style>
</head>
<body>
<header>
  <div>
    <h1>Preseed Finder</h1>
    <div class="sub">Early-stage European startups &middot; accumulated across runs</div>
  </div>
  <button class="primary" id="searchBtn" onclick="runSearch()">Search new startups</button>
</header>

<main>
  <div class="banner" id="banner"></div>

  <div class="progress-container" id="progContainer">
    <div class="progress-status"><span class="spinner"></span><span id="progStatus">Starting search...</span></div>
    <div class="progress-bar">
      <div class="progress-bar-fill" id="progFill"></div>
    </div>
  </div>

  <div class="toolbar">
    <select id="f_sector" onchange="load()"><option value="">All sectors</option></select>
    <select id="f_country" onchange="load()"><option value="">All countries</option></select>
    <select id="f_stage" onchange="load()"><option value="">All stages</option></select>
    <select id="f_source" onchange="load()"><option value="">All sources</option></select>
    <label class="chk"><input type="checkbox" id="f_email" onchange="load()"> With email only</label>
    <label class="chk"><input type="checkbox" id="f_new" onchange="load()"> New only</label>
    <span class="count" id="count"></span>
  </div>

  <table id="tbl">
    <thead>
      <tr>
        <th onclick="sortBy('company_name')">Company</th>
        <th onclick="sortBy('sector')">Sector</th>
        <th onclick="sortBy('stage')">Stage</th>
        <th onclick="sortBy('country')">Country</th>
        <th onclick="sortBy('source')">Source</th>
        <th>Contact</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
  <div class="empty" id="empty" style="display:none">No startups yet. Click <b>Search new startups</b> to start.</div>

  <details class="advanced">
    <summary>Advanced search options</summary>
    <div class="adv-grid">
      <div>
        <label>Sources (comma-separated)</label>
        <input type="text" id="sources" value="yc,antler,cordis,producthunt,rockstart">
      </div>
      <div>
        <label>Limit per source (empty = no limit)</label>
        <input type="number" id="limit" placeholder="e.g. 50">
      </div>
      <div>
        <label>YC batches (empty = last 3)</label>
        <input type="text" id="batches" placeholder="e.g. Summer 2025,Winter 2025">
      </div>
      <div>
        <label><input type="checkbox" id="enrich_llm" checked> LLM enrichment (stage/sector/email/founder via Claude)</label>
      </div>
    </div>
    <a class="ghost" href="/download" style="display:inline-block;text-decoration:none;margin-bottom:12px;">Download CSV export</a>
    <pre id="log" style="display:none"></pre>
  </details>
</main>

<script>
let DATA = [], MAIL = {subject:"", body:""}, SORT = {key:"company_name", dir:1}, polling = null;

function esc(s){ return (s||"").replace(/[&<>\"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c])); }

function fillFacet(id, values, label){
  const sel = document.getElementById(id);
  const cur = sel.value;
  sel.innerHTML = '<option value=\"\">'+label+'</option>' + values.map(v=>`<option>${esc(v)}</option>`).join('');
  sel.value = cur;
}

function mailHref(s){
  if(!s.email) return null;
  const subj = encodeURIComponent(MAIL.subject);
  const body = encodeURIComponent(MAIL.body.replace('{founder}', s.founder_name||'there').replace('{company}', s.company_name||'your company'));
  return `mailto:${s.email}?subject=${subj}&body=${body}`;
}

function badgeHtml(badges){
  return (badges||[]).map(b=>{
    let cls = b==='NEW' ? 'NEW' : (b==='New contact' ? 'contact' : 'change');
    return `<span class=\"badge ${cls}\">${esc(b)}</span>`;
  }).join('');
}

function render(){
  const tb = document.getElementById('tbody');
  const rows = [...DATA].sort((a,b)=>{
    let x=(a[SORT.key]||''), y=(b[SORT.key]||'');
    return x.toString().localeCompare(y.toString()) * SORT.dir;
  });
  document.getElementById('count').textContent = rows.length + ' startups';
  document.getElementById('empty').style.display = rows.length ? 'none' : 'block';
  tb.innerHTML = rows.map(s=>{
    const site = s.website ? `<a href=\"${esc(s.website)}\" target=\"_blank\">${esc(s.company_name)}</a>` : esc(s.company_name);
    const href = mailHref(s);
    const mail = href ? `<a class=\"mail-btn\" href=\"${href}\">Contact</a>` : `<span class=\"mail-btn disabled\">No email</span>`;
    const opts = ['To contact','Contacted','Replied'].map(o=>`<option ${o===s.contact_status?'selected':''}>${o}</option>`).join('');
    return `<tr>
      <td class=\"company\">${site}${badgeHtml(s.badges)}<div class=\"muted\">${esc(s.email||'')}</div></td>
      <td>${esc(s.sector||'-')}</td>
      <td>${esc(s.stage||'-')}</td>
      <td>${esc(s.country||'-')}</td>
      <td>${esc(s.source||'-')}</td>
      <td>${mail}</td>
      <td><select class=\"status\" data-v=\"${esc(s.contact_status)}\" onchange=\"setStatus('${esc(s.dedupe_key)}', this)\">${opts}</select></td>
    </tr>`;
  }).join('');
}

function sortBy(k){ SORT.dir = (SORT.key===k ? -SORT.dir : 1); SORT.key=k; render(); }

function showBanner(sum){
  const b = document.getElementById('banner');
  if(!sum || !sum.run_at){ b.classList.remove('show'); return; }
  const parts = [];
  if(sum.new_startups) parts.push(`<b>${sum.new_startups}</b> new`);
  if(sum.new_contacts) parts.push(`<b>${sum.new_contacts}</b> new contacts`);
  if(sum.stage_changes) parts.push(`<b>${sum.stage_changes}</b> stage changes`);
  if(sum.sector_changes) parts.push(`<b>${sum.sector_changes}</b> sector changes`);
  if(sum.website_or_founder_updates) parts.push(`<b>${sum.website_or_founder_updates}</b> profile updates`);
  if(!parts.length){ b.classList.remove('show'); return; }
  b.innerHTML = 'Since the last search: ' + parts.join(' &middot; ');
  b.classList.add('show');
}

async function load(){
  const q = new URLSearchParams({
    sector: document.getElementById('f_sector').value,
    country: document.getElementById('f_country').value,
    stage: document.getElementById('f_stage').value,
    source: document.getElementById('f_source').value,
    has_email: document.getElementById('f_email').checked ? '1':'',
    only_new: document.getElementById('f_new').checked ? '1':'',
  });
  const r = await fetch('/api/startups?'+q);
  const d = await r.json();
  DATA = d.startups; MAIL = d.mail;
  fillFacet('f_sector', d.facets.sector, 'All sectors');
  fillFacet('f_country', d.facets.country, 'All countries');
  fillFacet('f_stage', d.facets.stage, 'All stages');
  fillFacet('f_source', d.facets.source, 'All sources');
  showBanner(d.summary);
  render();
}

async function setStatus(key, sel){
  sel.dataset.v = sel.value;
  await fetch('/startup/'+encodeURIComponent(key)+'/status', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({status: sel.value})
  });
}

async function runSearch(){
  document.getElementById('searchBtn').disabled = true;
  document.getElementById('searchBtn').textContent = 'Searching...';
  const log = document.getElementById('log'); log.style.display='block'; log.textContent='Starting...\\n';
  const prog = document.getElementById('progContainer'); prog.classList.add('show');
  const body = {
    sources: document.getElementById('sources').value,
    limit: document.getElementById('limit').value || null,
    batches: document.getElementById('batches').value || null,
    enrich_llm: document.getElementById('enrich_llm').checked,
  };
  const r = await fetch('/start', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  if(!r.ok){ const e = await r.json(); log.textContent = 'Error: '+e.error; resetBtn(); prog.classList.remove('show'); return; }
  polling = setInterval(poll, 1200);
}

function resetBtn(){
  document.getElementById('searchBtn').disabled = false;
  document.getElementById('searchBtn').textContent = 'Search new startups';
}

async function poll(){
  const r = await fetch('/status'); const d = await r.json();
  const log = document.getElementById('log');
  log.textContent = d.log || '...'; log.scrollTop = log.scrollHeight;

  // Aggiorna il progress status in base ai messaggi di log
  const progStatus = document.getElementById('progStatus');
  const progFill = document.getElementById('progFill');
  let status = 'Running...', progress = 30;
  if(d.log.includes('[yc]')) status = 'Fetching Y Combinator...', progress = 10;
  else if(d.log.includes('[antler]')) status = 'Fetching Antler...', progress = 25;
  else if(d.log.includes('[rockstart]')) status = 'Fetching Rockstart...', progress = 40;
  else if(d.log.includes('[cordis]')) status = 'Fetching CORDIS...', progress = 55;
  else if(d.log.includes('[producthunt]')) status = 'Fetching Product Hunt...', progress = 70;
  else if(d.log.includes('[enrich]')) status = 'Enriching emails...', progress = 75;
  else if(d.log.includes('[llm]')) status = 'Enriching with LLM (this may take a few minutes)...', progress = 85;
  else if(d.log.includes('DB aggiornato')) status = 'Finalizing...', progress = 95;
  progStatus.textContent = status;
  progFill.style.width = progress + '%';

  if(!d.running){
    clearInterval(polling); resetBtn();
    await load();
    document.getElementById('progContainer').classList.remove('show');
    document.getElementById('progFill').style.width = '100%';
    progStatus.textContent = 'Done!';
    setTimeout(()=>document.getElementById('progContainer').classList.remove('show'), 2000);
  }
}

load();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)

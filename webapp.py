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
import config

app = Flask(__name__)

DB_PATH = store.DEFAULT_DB_PATH
_existing_csv = Path(__file__).parent / "startups.csv"
_env_path = Path(__file__).parent / ".env"

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


@app.route("/api/setup-status")
def setup_status():
    """Indica se manca una chiave LLM, cosi' la dashboard puo' mostrare un
    banner di setup al primo avvio (un collega non tecnico non deve aprire
    ne' modificare il file .env a mano)."""
    has_key = bool(config.GEMINI_API_KEY or config.ANTHROPIC_API_KEY)
    return jsonify({
        "needs_setup": not has_key,
        "provider": config.LLM_PROVIDER,
    })


@app.route("/api/setup-key", methods=["POST"])
def setup_key():
    """Salva la chiave API inserita dall'utente nel file .env locale, cosi'
    resta solo sulla sua macchina (come da requisito: ognuno inserisce la
    propria chiave la prima volta che lancia l'app)."""
    data = request.get_json(force=True) or {}
    provider = (data.get("provider") or "").strip().lower()
    api_key = (data.get("api_key") or "").strip()
    if provider not in ("gemini", "anthropic") or not api_key:
        return jsonify({"ok": False, "error": "Invalid provider or empty key."}), 400

    var_name = "GEMINI_API_KEY" if provider == "gemini" else "ANTHROPIC_API_KEY"

    lines = []
    if _env_path.exists():
        lines = _env_path.read_text().splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{var_name}="):
            lines[i] = f"{var_name}={api_key}"
            found = True
            break
    if not found:
        lines.append(f"{var_name}={api_key}")
    _env_path.write_text("\n".join(lines) + "\n")

    # Aggiorna anche il processo corrente, cosi' la run successiva la usa
    # subito senza dover riavviare l'app.
    import os
    os.environ[var_name] = api_key
    config.GEMINI_API_KEY = config.GEMINI_API_KEY or (api_key if provider == "gemini" else config.GEMINI_API_KEY)
    config.ANTHROPIC_API_KEY = config.ANTHROPIC_API_KEY or (api_key if provider == "anthropic" else config.ANTHROPIC_API_KEY)
    if provider == "gemini":
        config.GEMINI_API_KEY = api_key
    else:
        config.ANTHROPIC_API_KEY = api_key
    if not os.environ.get("LLM_PROVIDER"):
        config.LLM_PROVIDER = provider

    return jsonify({"ok": True})


@app.route("/api/startups")
def api_startups():
    filters = {
        "sector": request.args.get("sector") or None,
        "country": request.args.get("country") or None,
        "stage": request.args.get("stage") or None,
        "source": request.args.get("source") or None,
        "has_email": request.args.get("has_email") == "1",
        "only_new": request.args.get("only_new") == "1",
        "show_excluded": request.args.get("show_excluded") == "1",
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
    sources = data.get("sources") or "yc,antler,cordis,producthunt,rockstart,entrepreneur_first,betalist"
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
  :root { --bg:#f6f7f9; --card:#fff; --line:#e4e7eb; --ink:#1c2430; --muted:#6b7480; --accent:#2563eb; --ok:#16a34a; --ok-dark:#15803d; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin:0; background:var(--bg); color:var(--ink); }
  header { background:var(--card); border-bottom:1px solid var(--line); padding:16px 24px; display:flex; align-items:center; justify-content:space-between; }
  header h1 { font-size:1.25rem; margin:0; }
  header .sub { color:var(--muted); font-size:.85rem; }
  main { max-width:1180px; margin:0 auto; padding:20px 24px 60px; }
  .banner { background:#ecf3ff; border:1px solid #c7dbff; color:#1e3a8a; border-radius:10px; padding:12px 16px; margin-bottom:18px; font-size:.9rem; display:none; }
  .banner.show { display:block; }
  /* How it works: 3 passi sempre visibili, per i colleghi non tecnici */
  .howto { display:flex; gap:10px; flex-wrap:wrap; background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin-bottom:18px; }
  .howto .step { display:flex; align-items:center; gap:8px; font-size:.86rem; color:var(--ink); }
  .howto .num { display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:50%; background:var(--accent); color:#fff; font-size:.78rem; font-weight:700; flex:none; }
  .howto .arrow { color:var(--muted); align-self:center; }
  .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-bottom:14px; }
  .toolbar select, .toolbar input[type=text] { padding:7px 9px; border:1px solid var(--line); border-radius:8px; background:#fff; font-size:.85rem; }
  .toolbar label.chk { font-size:.85rem; color:var(--muted); display:flex; align-items:center; gap:5px; }
  /* Toggle "Ready to contact": il filtro protagonista, in evidenza */
  .toggle-ready { display:inline-flex; align-items:center; gap:8px; padding:7px 12px; border:1px solid var(--ok); border-radius:20px; background:#fff; color:var(--ok-dark); font-size:.85rem; font-weight:600; cursor:pointer; user-select:none; }
  .toggle-ready input { accent-color:var(--ok); }
  .toggle-ready.on { background:var(--ok); color:#fff; }
  .toggle-ready .rcount { font-weight:700; }
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
  .badge.UPDATED { background:#dbeafe; color:#1e40af; }
  .badge.contact { background:#fef3c7; color:#92400e; }
  .badge.change { background:#e0e7ff; color:#3730a3; }
  .conf { display:inline-block; font-size:.7rem; font-weight:700; padding:2px 8px; border-radius:20px; text-transform:capitalize; }
  .conf.high { background:#dcfce7; color:#166534; }
  .conf.medium { background:#fef9c3; color:#854d0e; }
  .conf.low { background:#f1f5f9; color:#64748b; }
  .conf.excl { background:#fee2e2; color:#b91c1c; }
  tr.is-excluded { background:#fcfafa; opacity:.72; }
  .excl-reason { color:#b91c1c !important; font-size:.75rem; margin-top:2px; }
  .mail-btn { display:inline-block; padding:7px 14px; border-radius:8px; background:var(--ok); color:#fff; text-decoration:none; font-size:.82rem; font-weight:600; white-space:nowrap; }
  .mail-btn:hover { background:var(--ok-dark); }
  .mail-btn.disabled { background:#e2e6eb; color:#9aa3ad; pointer-events:none; font-weight:500; }
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
  .modal-overlay { position:fixed; inset:0; background:rgba(15,20,30,.55); display:none; align-items:center; justify-content:center; z-index:100; }
  .modal-overlay.show { display:flex; }
  .modal { background:#fff; border-radius:14px; padding:28px; max-width:440px; width:92%; box-shadow:0 20px 60px rgba(0,0,0,.25); }
  .modal h2 { margin:0 0 8px; font-size:1.15rem; }
  .modal p { color:var(--muted); font-size:.88rem; line-height:1.5; margin:0 0 16px; }
  .modal label { font-size:.82rem; color:var(--muted); display:block; margin:12px 0 4px; }
  .modal select, .modal input[type=text], .modal input[type=password] { width:100%; padding:9px; border:1px solid var(--line); border-radius:8px; font-size:.9rem; }
  .modal .modal-actions { margin-top:18px; display:flex; gap:8px; justify-content:flex-end; }
  .modal a { color:var(--accent); }
  .modal .err { color:#b91c1c; font-size:.8rem; margin-top:8px; display:none; }
  .setup-banner { background:#fff7ed; border:1px solid #fed7aa; color:#9a3412; border-radius:10px; padding:10px 16px; margin-bottom:14px; font-size:.85rem; display:none; cursor:pointer; }
  .setup-banner.show { display:block; }
</style>
</head>
<body>

<div class="modal-overlay" id="setupModal">
  <div class="modal">
    <h2>Welcome to Preseed Finder</h2>
    <p>To find startups and their contact emails, the app uses an AI model to read each company's website. Paste an API key below (it's saved only on this computer, in a local .env file — never shared).</p>
    <label>Provider</label>
    <select id="setupProvider">
      <option value="anthropic">Claude (Anthropic) &mdash; recommended</option>
      <option value="gemini">Gemini (Google) &mdash; free tier available</option>
    </select>
    <label>API key</label>
    <input type="password" id="setupKey" placeholder="Paste your API key here">
    <div class="err" id="setupErr">Please select a provider and paste a valid key.</div>
    <div class="modal-actions">
      <button class="ghost" onclick="skipSetup()">Skip for now</button>
      <button class="primary" onclick="saveSetupKey()">Save key</button>
    </div>
  </div>
</div>

<header>
  <div>
    <h1>Preseed Finder</h1>
    <div class="sub">Early-stage European startups &middot; accumulated across runs</div>
  </div>
  <button class="primary" id="searchBtn" onclick="runSearch()">Search new startups</button>
</header>

<main>
  <div class="setup-banner" id="setupBanner" onclick="openSetup()">No API key configured yet &mdash; AI lookup (stage/sector/founder) is disabled. Click here to add one.</div>

  <div class="howto">
    <div class="step"><span class="num">1</span> Click <b>&nbsp;Search new startups</b></div>
    <span class="arrow">&rarr;</span>
    <div class="step"><span class="num">2</span> Turn on <b>&nbsp;Ready to contact</b> to see who has an email</div>
    <span class="arrow">&rarr;</span>
    <div class="step"><span class="num">3</span> Click <b>&nbsp;Contact</b> to email the founder, then set the status</div>
  </div>

  <div class="banner" id="banner"></div>

  <div class="progress-container" id="progContainer">
    <div class="progress-status"><span class="spinner"></span><span id="progStatus">Starting search...</span></div>
    <div class="progress-bar">
      <div class="progress-bar-fill" id="progFill"></div>
    </div>
  </div>

  <div class="toolbar">
    <label class="toggle-ready" id="readyToggle">
      <input type="checkbox" id="f_ready" onchange="onReadyToggle()">
      Ready to contact <span class="rcount" id="readyCount"></span>
    </label>
    <select id="f_sector" onchange="load()"><option value="">All sectors</option></select>
    <select id="f_country" onchange="load()"><option value="">All countries</option></select>
    <select id="f_stage" onchange="load()"><option value="">All stages</option></select>
    <select id="f_source" onchange="load()"><option value="">All sources</option></select>
    <label class="chk"><input type="checkbox" id="f_email" onchange="load()"> Has email</label>
    <label class="chk"><input type="checkbox" id="f_new" onchange="load()"> New this run</label>
    <label class="chk" title="Show also companies excluded because they are past pre-seed or outside US/Canada/Europe"><input type="checkbox" id="f_excluded" onchange="load()"> Show excluded</label>
    <span class="count" id="count"></span>
  </div>

  <table id="tbl">
    <thead>
      <tr>
        <th onclick="sortBy('company_name')">Company</th>
        <th onclick="sortBy('founder_name')">Founder</th>
        <th onclick="sortBy('sector')">Sector</th>
        <th onclick="sortBy('stage')">Stage</th>
        <th onclick="sortBy('preseed_confidence')">Pre-seed</th>
        <th onclick="sortBy('country')">Country</th>
        <th onclick="sortBy('source')">Found on</th>
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
        <input type="text" id="sources" value="yc,antler,cordis,producthunt,rockstart,entrepreneur_first,betalist">
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
        <label><input type="checkbox" id="enrich_llm" checked> AI enrichment (reads each website to refine stage/sector/founder &mdash; requires an API key, see setup). Emails are always read from the real site, never guessed.</label>
      </div>
    </div>
    <a class="ghost" href="/download" style="display:inline-block;text-decoration:none;margin-bottom:12px;">Download CSV export</a>
    <pre id="log" style="display:none"></pre>
  </details>
</main>

<script>
let DATA = [], MAIL = {subject:"", body:""}, SORT = {key:"company_name", dir:1}, polling = null;

// Nomi leggibili delle fonti (i colleghi non devono vedere sigle tecniche).
const SOURCE_LABELS = {
  yc: "Y Combinator",
  antler: "Antler",
  cordis: "EU grants (CORDIS)",
  cordis_eic: "EU grants (CORDIS)",
  producthunt: "Product Hunt",
  rockstart: "Rockstart",
  entrepreneur_first: "Entrepreneur First",
  betalist: "BetaList",
  crunchbase: "Crunchbase",
};
function sourceLabel(src){ return SOURCE_LABELS[src] || (src || "-"); }

function esc(s){ return (s||"").replace(/[&<>\"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c])); }

function fillFacet(id, values, label, labeller){
  const sel = document.getElementById(id);
  const cur = sel.value;
  // value = valore tecnico (per la query); testo = etichetta leggibile.
  sel.innerHTML = '<option value=\"\">'+label+'</option>' +
    values.map(v=>`<option value=\"${esc(v)}\">${esc(labeller ? labeller(v) : v)}</option>`).join('');
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
    let cls = 'change';
    if(b==='NEW') cls='NEW';
    else if(b==='UPDATED') cls='UPDATED';
    else if(b==='New contact') cls='contact';
    return `<span class=\"badge ${cls}\">${esc(b)}</span>`;
  }).join('');
}

// Pillola di confidenza pre-seed (o "excluded" per chi non e' qualificato).
function confHtml(s){
  if(s.qualified === 0) return '<span class=\"conf excl\">excluded</span>';
  const c = s.preseed_confidence || '';
  if(!c) return '<span class=\"muted\">&mdash;</span>';
  return `<span class=\"conf ${esc(c)}\">${esc(c)}</span>`;
}

// Una startup e' "pronta da contattare" se ha un'email e non e' ancora stata
// contattata. E' il filtro protagonista per i colleghi.
function isReady(s){ return !!s.email && s.contact_status === 'To contact'; }

function render(){
  const tb = document.getElementById('tbody');
  const readyOnly = document.getElementById('f_ready').checked;

  let rows = [...DATA];
  if(readyOnly) rows = rows.filter(isReady);
  rows.sort((a,b)=>{
    let x=(a[SORT.key]||''), y=(b[SORT.key]||'');
    return x.toString().localeCompare(y.toString()) * SORT.dir;
  });

  // Contatore "ready to contact" sempre sul totale caricato (non sul filtrato).
  const readyTotal = DATA.filter(isReady).length;
  document.getElementById('readyCount').textContent = '(' + readyTotal + ')';
  document.getElementById('count').textContent = rows.length + (rows.length === 1 ? ' startup' : ' startups');
  document.getElementById('empty').style.display = rows.length ? 'none' : 'block';

  tb.innerHTML = rows.map(s=>{
    const site = s.website ? `<a href=\"${esc(s.website)}\" target=\"_blank\">${esc(s.company_name)}</a>` : esc(s.company_name);
    const founder = s.founder_name ? esc(s.founder_name) : `<span class=\"muted\">&mdash;</span>`;
    const href = mailHref(s);
    const label = s.founder_name ? 'Contact founder' : 'Contact';
    const mail = href ? `<a class=\"mail-btn\" href=\"${href}\">${label}</a>` : `<span class=\"mail-btn disabled\">No email yet</span>`;
    const opts = ['To contact','Contacted','Replied'].map(o=>`<option ${o===s.contact_status?'selected':''}>${o}</option>`).join('');
    const excluded = (s.qualified===0) ? `<div class=\"muted excl-reason\">Excluded: ${esc(s.exclude_reason||'')}</div>` : '';
    return `<tr class=\"${s.qualified===0?'is-excluded':''}\">
      <td class=\"company\">${site}${badgeHtml(s.badges)}<div class=\"muted\">${esc(s.email||'')}</div>${excluded}</td>
      <td>${founder}</td>
      <td>${esc(s.sector||'-')}</td>
      <td title=\"${esc(s.stage_reason||'')}\">${esc(s.stage||'-')}</td>
      <td>${confHtml(s)}</td>
      <td>${esc(s.country||'-')}</td>
      <td>${esc(sourceLabel(s.source))}</td>
      <td>${mail}</td>
      <td><select class=\"status\" data-v=\"${esc(s.contact_status)}\" onchange=\"setStatus('${esc(s.dedupe_key)}', this)\">${opts}</select></td>
    </tr>`;
  }).join('');
}

// Quando si attiva/disattiva il toggle "Ready to contact": aggiorna lo stile
// della pillola e ri-renderizza (filtro client-side, nessuna chiamata server).
function onReadyToggle(){
  const on = document.getElementById('f_ready').checked;
  document.getElementById('readyToggle').classList.toggle('on', on);
  render();
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
    show_excluded: document.getElementById('f_excluded').checked ? '1':'',
  });
  const r = await fetch('/api/startups?'+q);
  const d = await r.json();
  DATA = d.startups; MAIL = d.mail;
  fillFacet('f_sector', d.facets.sector, 'All sectors');
  fillFacet('f_country', d.facets.country, 'All countries');
  fillFacet('f_stage', d.facets.stage, 'All stages');
  fillFacet('f_source', d.facets.source, 'All sources', sourceLabel);
  showBanner(d.summary);
  render();
}

async function setStatus(key, sel){
  sel.dataset.v = sel.value;
  // Aggiorna il dato locale cosi' il contatore "ready" e il filtro reagiscono
  // subito (es. una appena "Contacted" esce da "Ready to contact").
  const row = DATA.find(s=>s.dedupe_key === key);
  if(row) row.contact_status = sel.value;
  render();
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

// Estrae l'ultimo contatore "i/N" stampato da un certo prefisso di log
// (es. "[email]   42/180 ...") per mostrare "X of N" che avanza: e' cosi' che
// un collega su Windows, senza terminale, capisce che il programma sta
// lavorando e non si e' bloccato.
function lastCounter(logText, tag){
  const re = new RegExp('\\\\['+tag+'\\\\][^\\\\n]*?(\\\\d+)\\\\s*/\\\\s*(\\\\d+)', 'g');
  let m, last = null;
  while((m = re.exec(logText)) !== null){ last = [parseInt(m[1]), parseInt(m[2])]; }
  return last;
}

// Decide la frase di stato (in inglese, leggibile) e la percentuale in base a
// quale fase la pipeline ha raggiunto. L'ordine dei controlli va dal PIU'
// avanzato al meno avanzato, cosi' si mostra sempre la fase piu' recente.
function describeProgress(logText){
  const phase = (tag, label, base) => {
    const c = lastCounter(logText, tag);
    if(c){ return { status: label+' '+c[0]+' of '+c[1]+'...', progress: base }; }
    return { status: label+'...', progress: base };
  };
  if(logText.includes('DB aggiornato') || logText.includes('scritto'))
    return { status: 'Finalizing and saving results...', progress: 96 };
  if(logText.includes('[llm]') && (logText.includes('arricchisco') || /\\[llm\\][^\\n]*\\d+\\s*\\/\\s*\\d+/.test(logText)))
    return phase('llm', 'Reading websites with AI to refine stage & founders', 85);
  if(logText.includes('[email]'))
    return phase('email', 'Looking up contact emails on company sites', 72);
  if(logText.includes('[enrich]'))
    return { status: 'Looking up extra emails...', progress: 70 };
  if(logText.includes('[producthunt]')) return { status: 'Fetching Product Hunt...', progress: 60 };
  if(logText.includes('[betalist]')) return { status: 'Fetching BetaList...', progress: 52 };
  if(logText.includes('[entrepreneur_first]') || logText.includes("'entrepreneur_first'"))
    return { status: 'Fetching Entrepreneur First...', progress: 46 };
  if(logText.includes('[cordis]')) return { status: 'Fetching EU grant database (CORDIS)...', progress: 40 };
  if(logText.includes('[rockstart]')) return { status: 'Fetching Rockstart...', progress: 32 };
  if(logText.includes('[antler]')) return { status: 'Fetching Antler...', progress: 24 };
  if(logText.includes('[yc]') || logText.includes("'yc'")) return { status: 'Fetching Y Combinator...', progress: 14 };
  return { status: 'Starting search...', progress: 6 };
}

async function poll(){
  const r = await fetch('/status'); const d = await r.json();
  const log = document.getElementById('log');
  log.textContent = d.log || '...'; log.scrollTop = log.scrollHeight;

  const progStatus = document.getElementById('progStatus');
  const progFill = document.getElementById('progFill');
  const p = describeProgress(d.log || '');
  progStatus.textContent = p.status;
  progFill.style.width = p.progress + '%';

  if(!d.running){
    clearInterval(polling); resetBtn();
    await load();
    document.getElementById('progFill').style.width = '100%';
    progStatus.textContent = 'Done! Your dashboard is up to date.';
    setTimeout(()=>document.getElementById('progContainer').classList.remove('show'), 2200);
  }
}

function openSetup(){
  document.getElementById('setupModal').classList.add('show');
}
function skipSetup(){
  document.getElementById('setupModal').classList.remove('show');
}
async function saveSetupKey(){
  const provider = document.getElementById('setupProvider').value;
  const key = document.getElementById('setupKey').value.trim();
  const err = document.getElementById('setupErr');
  if(!key){ err.style.display = 'block'; return; }
  err.style.display = 'none';
  const r = await fetch('/api/setup-key', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({provider, api_key: key})
  });
  if(!r.ok){ err.textContent = 'Could not save the key, please try again.'; err.style.display='block'; return; }
  document.getElementById('setupModal').classList.remove('show');
  document.getElementById('setupBanner').classList.remove('show');
}
async function checkSetup(){
  const r = await fetch('/api/setup-status');
  const d = await r.json();
  if(d.needs_setup){
    document.getElementById('setupModal').classList.add('show');
    document.getElementById('setupBanner').classList.add('show');
  }
}

checkSetup();
load();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)

"""Persistenza SQLite con storico.

A differenza del CSV (sovrascritto a ogni run), questo store ACCUMULA le startup
tra run diverse, traccia i cambiamenti (nuove startup, nuovo contatto, cambio
stage/settore, sito/founder aggiornati) e conserva uno stato di contatto
modificabile dall'utente dalla dashboard.

Due tabelle:
  - startups: una riga per startup (chiave = dedupe_key), con first_seen,
    last_seen, contact_status (impostato dall'utente, mai toccato dalla pipeline)
    e is_new (flag azzerato a inizio run e riacceso sulle startup mai viste).
  - changes: log append-only dei cambiamenti, usato per le notifiche in UI.

Tutti i testi destinati all'utente (stati di contatto) sono in inglese perché
finiscono in dashboard.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dedupe import dedupe_key

DEFAULT_DB_PATH = str(Path(__file__).parent / "preseed.db")

# Stato di contatto di default per una startup appena scoperta. In inglese
# perché mostrato in dashboard. Gli altri stati validi sono "Contacted",
# "Replied" — l'utente li imposta dalla UI.
DEFAULT_CONTACT_STATUS = "To contact"

# Campi della startup monitorati per il change tracking.
MONITORED_FIELDS = ["company_name", "website", "sector", "stage", "founder_name", "email", "country", "source"]

# Sottoinsieme di campi i cui cambiamenti generano una notifica in dashboard.
NOTABLE_FIELDS = ["email", "stage", "sector", "website", "founder_name"]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path=DEFAULT_DB_PATH):
    """Crea le tabelle se non esistono. Idempotente."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS startups (
                dedupe_key     TEXT PRIMARY KEY,
                company_name   TEXT,
                website        TEXT,
                sector         TEXT,
                stage          TEXT,
                founder_name   TEXT,
                email          TEXT,
                country        TEXT,
                source         TEXT,
                first_seen     TEXT,
                last_seen      TEXT,
                contact_status TEXT DEFAULT 'To contact',
                is_new         INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS changes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                dedupe_key  TEXT,
                change_type TEXT,   -- 'new' | 'field'
                field       TEXT,   -- NULL per 'new'
                old_value   TEXT,
                new_value   TEXT,
                changed_at  TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_changes_changed_at ON changes(changed_at)")
        conn.commit()
    finally:
        conn.close()


class ChangeReport:
    """Riassunto di una run, usato dalla dashboard per il banner notifiche."""

    def __init__(self):
        self.new_startups = 0
        self.new_contacts = 0      # email passata da vuoto a valorizzato
        self.stage_changes = 0
        self.sector_changes = 0
        self.website_or_founder_updates = 0
        self.run_at = _now()

    def as_dict(self):
        return {
            "new_startups": self.new_startups,
            "new_contacts": self.new_contacts,
            "stage_changes": self.stage_changes,
            "sector_changes": self.sector_changes,
            "website_or_founder_updates": self.website_or_founder_updates,
            "run_at": self.run_at,
        }

    def total(self):
        return (
            self.new_startups
            + self.new_contacts
            + self.stage_changes
            + self.sector_changes
            + self.website_or_founder_updates
        )


def _record_change(conn, key, change_type, field, old, new, when):
    conn.execute(
        "INSERT INTO changes (dedupe_key, change_type, field, old_value, new_value, changed_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (key, change_type, field, old, new, when),
    )


def upsert_records(records, db_path=DEFAULT_DB_PATH):
    """Accumula i record nel DB, tracciando i cambiamenti.

    - Azzera is_new su tutte le righe (così "new" = nuove in QUESTA run).
    - Per ogni record: INSERT se mai visto (is_new=1, change 'new'), altrimenti
      confronta i campi monitorati e registra/aggiorna solo i cambiamenti
      (un campo non viene mai sovrascritto con un valore vuoto).
    - contact_status non viene mai modificato qui.

    Ritorna un ChangeReport.
    """
    init_db(db_path)
    report = ChangeReport()
    now = _now()

    conn = _connect(db_path)
    try:
        conn.execute("UPDATE startups SET is_new = 0")

        for record in records:
            key = dedupe_key(record)
            if not key:
                continue

            existing = conn.execute(
                "SELECT * FROM startups WHERE dedupe_key = ?", (key,)
            ).fetchone()

            if existing is None:
                conn.execute(
                    """
                    INSERT INTO startups
                        (dedupe_key, company_name, website, sector, stage, founder_name,
                         email, country, source, first_seen, last_seen, contact_status, is_new)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        key,
                        record.get("company_name"),
                        record.get("website"),
                        record.get("sector"),
                        record.get("stage"),
                        record.get("founder_name"),
                        record.get("email"),
                        record.get("country"),
                        record.get("source"),
                        now,
                        now,
                        DEFAULT_CONTACT_STATUS,
                    ),
                )
                _record_change(conn, key, "new", None, None, record.get("company_name"), now)
                report.new_startups += 1
                continue

            # Startup già vista: confronta i campi e aggiorna solo i miglioramenti.
            updates = {}
            for field in MONITORED_FIELDS:
                new_val = record.get(field)
                old_val = existing[field]
                if not new_val:
                    continue  # non sovrascrivere con vuoto
                if (old_val or "") == new_val:
                    continue
                updates[field] = new_val
                if field in NOTABLE_FIELDS:
                    _record_change(conn, key, "field", field, old_val, new_val, now)
                    if field == "email" and not old_val:
                        report.new_contacts += 1
                    elif field == "stage":
                        report.stage_changes += 1
                    elif field == "sector":
                        report.sector_changes += 1
                    elif field in ("website", "founder_name"):
                        report.website_or_founder_updates += 1

            updates["last_seen"] = now
            set_clause = ", ".join(f"{f} = ?" for f in updates)
            conn.execute(
                f"UPDATE startups SET {set_clause} WHERE dedupe_key = ?",
                (*updates.values(), key),
            )

        conn.commit()
    finally:
        conn.close()

    return report


def get_startups(db_path=DEFAULT_DB_PATH, filters=None):
    """Ritorna le startup (lista di dict) con filtri opzionali per la dashboard.

    filters: dict con chiavi opzionali sector, country, stage, source (match
    esatto, case-insensitive), has_email (bool), only_new (bool).
    """
    init_db(db_path)
    filters = filters or {}
    clauses = []
    params = []

    for col in ("sector", "country", "stage", "source"):
        val = filters.get(col)
        if val:
            clauses.append(f"LOWER({col}) = LOWER(?)")
            params.append(val)
    if filters.get("has_email"):
        clauses.append("email IS NOT NULL AND email != ''")
    if filters.get("only_new"):
        clauses.append("is_new = 1")

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM startups{where} ORDER BY is_new DESC, last_seen DESC, company_name COLLATE NOCASE"

    conn = _connect(db_path)
    try:
        rows = conn.execute(sql, params).fetchall()

        # I badge "UPDATED" devono riferirsi SOLO all'ultima run (come "NEW"),
        # non a cambiamenti vecchi: si prendono i field-change il cui changed_at
        # coincide col timestamp dell'ultima run (MAX(changed_at)).
        last_row = conn.execute("SELECT MAX(changed_at) AS last FROM changes").fetchone()
        last_run = last_row["last"] if last_row else None

        recent_fields = {}
        if last_run:
            for r in conn.execute(
                "SELECT dedupe_key, field FROM changes "
                "WHERE change_type = 'field' AND changed_at = ?",
                (last_run,),
            ).fetchall():
                recent_fields.setdefault(r["dedupe_key"], set()).add(r["field"])

        result = []
        for row in rows:
            d = dict(row)
            d["badges"] = _badges_for(d, recent_fields.get(d["dedupe_key"], set()))
            result.append(d)
        return result
    finally:
        conn.close()


def _badges_for(startup, changed_fields):
    """Badge per una riga.

    - NEW (verde): startup mai vista prima di quest'ultima run.
    - UPDATED (blu): startup gia' nota che in quest'ultima run ha ricevuto info
      nuova; accanto, badge di dettaglio su COSA e' cambiato.
    NEW e UPDATED sono mutuamente esclusivi: una riga nuova e' "NEW", non
    "UPDATED" (e' tutta nuova, non un aggiornamento di qualcosa di esistente)."""
    if startup.get("is_new"):
        return ["NEW"]

    if not changed_fields:
        return []

    badges = ["UPDATED"]
    if "email" in changed_fields:
        badges.append("New contact")
    if "stage" in changed_fields:
        badges.append("Stage changed")
    if "sector" in changed_fields:
        badges.append("Sector changed")
    if "website" in changed_fields or "founder_name" in changed_fields:
        badges.append("Profile updated")
    return badges


def set_contact_status(key, status, db_path=DEFAULT_DB_PATH):
    """Aggiorna lo stato di contatto di una startup (impostato dall'utente)."""
    init_db(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE startups SET contact_status = ? WHERE dedupe_key = ?", (status, key)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def last_run_summary(db_path=DEFAULT_DB_PATH):
    """Riepilogo dei cambiamenti dell'ULTIMA run (raggruppati per changed_at più
    recente), per il banner notifiche all'apertura della dashboard."""
    init_db(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT MAX(changed_at) AS last FROM changes").fetchone()
        last = row["last"] if row else None
        if not last:
            return {"run_at": None, "new_startups": 0, "new_contacts": 0,
                    "stage_changes": 0, "sector_changes": 0, "website_or_founder_updates": 0}

        rows = conn.execute(
            "SELECT change_type, field, old_value FROM changes WHERE changed_at = ?", (last,)
        ).fetchall()

        summary = {"run_at": last, "new_startups": 0, "new_contacts": 0,
                   "stage_changes": 0, "sector_changes": 0, "website_or_founder_updates": 0}
        for r in rows:
            if r["change_type"] == "new":
                summary["new_startups"] += 1
            elif r["field"] == "email" and not r["old_value"]:
                summary["new_contacts"] += 1
            elif r["field"] == "stage":
                summary["stage_changes"] += 1
            elif r["field"] == "sector":
                summary["sector_changes"] += 1
            elif r["field"] in ("website", "founder_name"):
                summary["website_or_founder_updates"] += 1
        return summary
    finally:
        conn.close()


def distinct_values(column, db_path=DEFAULT_DB_PATH):
    """Valori distinti non vuoti per una colonna (per popolare i filtri della UI)."""
    if column not in MONITORED_FIELDS:
        return []
    init_db(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT DISTINCT {column} AS v FROM startups "
            f"WHERE {column} IS NOT NULL AND {column} != '' ORDER BY v COLLATE NOCASE"
        ).fetchall()
        return [r["v"] for r in rows]
    finally:
        conn.close()

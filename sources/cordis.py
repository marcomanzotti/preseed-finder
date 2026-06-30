"""Fonte CORDIS: startup finanziate dall'EIC Accelerator (European Innovation
Council), il programma UE che finanzia direttamente singole startup/SME a
stadio early (pre-seed/seed/scale-up iniziale) con grant + equity.

Usa il dataset bulk ufficiale CORDIS (CSV, no API key) invece della search
API perché quest'ultima non espone le organizzazioni partecipanti.
"""

import csv
import io
import zipfile

import requests

import config

BULK_ZIP_URL = "https://cordis.europa.eu/data/cordis-HORIZONprojects-csv.zip"

# Funding scheme dell'EIC Accelerator: finanzia singole startup/SME private
# a stadio early con grant + equity blended finance. Ottimo proxy per pre-seed/seed.
EIC_FUNDING_SCHEMES = {"HORIZON-EIC-ACC", "HORIZON-EIC-ACC-BF"}


def _download_bulk_csvs():
    resp = requests.get(BULK_ZIP_URL, timeout=60)
    resp.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    with zf.open("project.csv") as f:
        project_rows = list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter=";", quotechar='"'))
    with zf.open("organization.csv") as f:
        org_rows = list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter=";", quotechar='"'))
    return project_rows, org_rows


def fetch(limit=None, country=None):
    print("[cordis] scarico dataset bulk CORDIS (~35MB, puo' richiedere un minuto)...")
    try:
        project_rows, org_rows = _download_bulk_csvs()
    except Exception as e:
        print(f"[cordis] errore download dataset: {e}")
        return []

    eic_project_ids = {
        row["id"] for row in project_rows
        if row.get("fundingScheme") in EIC_FUNDING_SCHEMES
    }
    print(f"[cordis] {len(eic_project_ids)} progetti EIC Accelerator trovati.")

    records = []
    for row in org_rows:
        if row.get("projectID") not in eic_project_ids:
            continue
        if row.get("SME") != "true":
            continue
        if country and row.get("country", "").upper() != country.upper():
            continue

        company_name = (row.get("name") or "").strip().title()
        if not company_name:
            continue

        website = (row.get("organizationURL") or "").strip() or None

        records.append({
            "company_name": company_name,
            "website": website,
            "sector": None,
            "stage": "seed",  # EIC Accelerator finanzia tipicamente TRL 5-8: seed/early scale-up
            "founder_name": None,
            "email": None,
            "country": row.get("country"),
            "source": "cordis_eic",
        })

        if limit is not None and len(records) >= limit:
            break

    print(f"[cordis] {len(records)} startup estratte da EIC Accelerator.")
    return records

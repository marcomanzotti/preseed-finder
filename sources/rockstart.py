"""Fonte Rockstart: portfolio pubblico dell'acceleratore/VC early-stage
Rockstart (sede NL, investe a pre-seed/seed in Energy, AgriFood, Emerging Tech).

La pagina restituisce 403 al fetch diretto (anti-bot) ma carica regolarmente in
un browser reale, quindi si usa Playwright come per yc.py/antler.py.

Layout: una griglia di `article.elementor-post`; per ogni card il testo è
strutturato a righe — nome, descrizione, settore, "Company Website", "Year
Added", <anno>, "Funding Status", ... Il primo link della card è il sito
ufficiale dell'azienda. L'anno ("Year Added") viene mappato su un campo extra
`_year_added`, utile in futuro per il filtro "max 2 anni di vita" previsto in
roadmap (non è ancora nello schema CSV/DB comune, quindi resta interno).
"""

from playwright.sync_api import sync_playwright

PORTFOLIO_URL = "https://rockstart.com/portfolio/"


def _parse_card(card):
    lines = [l.strip() for l in card.inner_text().split("\n") if l.strip()]
    if not lines:
        return None
    company_name = lines[0]
    if not company_name or company_name.lower() in ("company website", "year added"):
        return None

    # Il settore è la riga subito prima di "Company Website" (se presente).
    sector = None
    year_added = None
    for i, line in enumerate(lines):
        low = line.lower()
        if low == "company website" and i >= 2:
            # lines[1] è la descrizione, lines[i-1] il settore.
            candidate = lines[i - 1]
            if candidate.lower() not in ("company website", company_name.lower()):
                sector = candidate
        if low == "year added" and i + 1 < len(lines):
            year_added = lines[i + 1]

    link_el = card.query_selector("a[href^='http']")
    website = link_el.get_attribute("href") if link_el else None
    # Evita di catturare il link interno alla scheda Rockstart come "sito".
    if website and "rockstart.com" in website:
        website = None

    return {
        "company_name": company_name,
        "website": website,
        "sector": sector,
        "stage": "seed",  # Rockstart investe tipicamente a pre-seed/seed
        "founder_name": None,
        "email": None,
        "country": None,
        "source": "rockstart",
        "_year_added": year_added,
    }


def fetch(limit=None, country=None):
    print("[rockstart] avvio browser headless...")
    records = []
    seen_names = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(PORTFOLIO_URL, wait_until="networkidle", timeout=40000)
        except Exception as e:
            print(f"[rockstart] impossibile caricare il portfolio: {e}")
            browser.close()
            return []
        page.wait_for_timeout(2000)

        cards = page.query_selector_all("article.elementor-post")
        print(f"[rockstart] {len(cards)} card trovate, estraggo i dati...")

        for i, card in enumerate(cards, 1):
            if limit is not None and len(records) >= limit:
                break
            data = _parse_card(card)
            if not data or data["company_name"] in seen_names:
                continue
            seen_names.add(data["company_name"])
            data.pop("_year_added", None)
            records.append(data)
            if i % 50 == 0:
                print(f"[rockstart]   {i}/{len(cards)}...")

        browser.close()

    print(f"[rockstart] {len(records)} startup estratte dal portfolio.")
    return records

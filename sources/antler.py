"""Fonte Antler: portfolio pubblico del VC paneuropeo Antler, che investe
quasi esclusivamente a stadio pre-seed/day-zero. Pagina caricata via
Playwright (lazy-load infinite scroll, come YC).
"""

from playwright.sync_api import sync_playwright

PORTFOLIO_URL = "https://www.antler.co/portfolio"


def _parse_card(card):
    name_el = card.query_selector('[fs-cmsfilter-field="name"]')
    desc_el = card.query_selector('[fs-cmsfilter-field="description"]')
    sector_el = card.query_selector('[fs-cmsfilter-field="sector"]')
    location_el = card.query_selector('[fs-cmsfilter-field="location"]')
    link_el = card.query_selector("a.clickable_link")

    company_name = name_el.inner_text().strip() if name_el else None
    if not company_name:
        return None

    website = link_el.get_attribute("href") if link_el else None
    sector = sector_el.inner_text().strip() if sector_el else None
    location = location_el.inner_text().strip() if location_el else None
    description = desc_el.inner_text().strip() if desc_el else None

    return {
        "company_name": company_name,
        "website": website,
        "sector": sector,
        "stage": "pre-seed",  # Antler investe quasi esclusivamente a day-zero/pre-seed
        "founder_name": None,
        "email": None,
        "country": location,
        "source": "antler",
        "_description": description,
    }


def fetch(limit=None, country=None):
    print("[antler] avvio browser headless...")
    records = []
    seen_names = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(PORTFOLIO_URL, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"[antler] impossibile caricare il portfolio: {e}")
            browser.close()
            return []
        page.wait_for_timeout(1500)

        # Scroll fino a quando il numero di card smette di crescere (lazy-load completo).
        prev = -1
        stable_rounds = 0
        while stable_rounds < 3:
            cards = page.query_selector_all(".portco_card")
            current = len(cards)
            if limit is not None and current >= limit:
                break
            if current == prev:
                stable_rounds += 1
            else:
                stable_rounds = 0
            prev = current
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(800)

        cards = page.query_selector_all(".portco_card")
        print(f"[antler] {len(cards)} card caricate, estraggo i dati...")

        for i, card in enumerate(cards, 1):
            if limit is not None and len(records) >= limit:
                break
            data = _parse_card(card)
            if not data or data["company_name"] in seen_names:
                continue
            if country and data.get("country") and country.lower() not in data["country"].lower():
                continue
            seen_names.add(data["company_name"])
            data.pop("_description", None)
            records.append(data)
            if i % 20 == 0:
                print(f"[antler]   {i}/{len(cards)}...")

        browser.close()

    print(f"[antler] {len(records)} startup estratte dal portfolio.")
    return records

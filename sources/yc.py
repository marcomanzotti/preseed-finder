import re
from urllib.parse import quote
from playwright.sync_api import sync_playwright

# Batch recenti = proxy ragionevole per "pre-seed/seed": YC investe a pre-seed.
# Più batch includi, più volume ottieni (ma più aziende saranno già oltre il pre-seed).
DEFAULT_BATCHES = ["Summer 2025", "Spring 2025", "Winter 2025"]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
EXCLUDED_EMAIL_DOMAINS = ("ycombinator.com", "sentry.io", "example.com")

EXCLUDED_SITE_DOMAINS = (
    "ycombinator.com", "linkedin.com", "x.com", "twitter.com",
    "startupschool.org", "news.ycombinator.com", "bookface.ycombinator.com",
    "cal.com", "facebook.com", "instagram.com",
)


def _parse_card(card):
    name_el = card.query_selector('span[class*="_coName_"]')
    location_el = card.query_selector('span[class*="_coLocation_"]')
    industry_links = card.query_selector_all('a[href*="industry="]')

    company_name = name_el.inner_text().strip() if name_el else None
    location = location_el.inner_text().strip() if location_el else None
    sector = industry_links[0].inner_text().strip() if industry_links else None

    if not company_name:
        return None
    return {"company_name": company_name, "sector": sector, "location": location}


def _list_batches(page, batches, limit):
    cards_data = []
    seen_slugs = set()
    for batch in batches:
        if limit is not None and len(cards_data) >= limit:
            break
        url = f"https://www.ycombinator.com/companies?batch={quote(batch)}"
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            print(f"[yc]   impossibile caricare batch {batch}, salto.")
            continue
        page.wait_for_timeout(1500)

        # Scroll fino a quando il numero di card smette di crescere (lazy-load completo).
        prev = -1
        stable_rounds = 0
        while stable_rounds < 3:
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(700)
            count = len(page.query_selector_all('a[href^="/companies/"]'))
            if count == prev:
                stable_rounds += 1
            else:
                stable_rounds = 0
            prev = count

        batch_added = 0
        for card in page.query_selector_all('a[href^="/companies/"]'):
            href = card.get_attribute("href") or ""
            slug = href.removeprefix("/companies/")
            if not slug or slug in seen_slugs:
                continue
            parsed = _parse_card(card)
            if not parsed:
                continue
            seen_slugs.add(slug)
            cards_data.append({**parsed, "slug": slug, "batch": batch})
            batch_added += 1
            if limit is not None and len(cards_data) >= limit:
                break
        print(f"[yc]   batch {batch}: {batch_added} aziende in lista.")
    return cards_data


def _extract_detail(page, slug):
    page.goto(f"https://www.ycombinator.com/companies/{slug}", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(800)

    website = None
    for link in page.query_selector_all('a.group.flex.items-center.space-x-2[href^="http"]'):
        href = link.get_attribute("href") or ""
        if not any(domain in href for domain in EXCLUDED_SITE_DOMAINS):
            website = href
            break
    if not website:
        for link in page.query_selector_all('a[target="_blank"][href^="http"]'):
            href = link.get_attribute("href") or ""
            if not any(domain in href for domain in EXCLUDED_SITE_DOMAINS):
                website = href
                break

    text = page.inner_text("body")

    founder_name = None
    idx = text.find("Active Founders")
    if idx != -1:
        after = text[idx + len("Active Founders"):idx + len("Active Founders") + 200]
        founder_lines = [l.strip() for l in after.split("\n") if l.strip()]
        if founder_lines:
            founder_name = founder_lines[0]

    email = None
    for match in EMAIL_RE.findall(text):
        if not any(domain in match.lower() for domain in EXCLUDED_EMAIL_DOMAINS):
            email = match
            break

    return {"website": website, "founder_name": founder_name, "email": email}


def fetch(limit=None, country=None, batches=None, with_detail=True):
    batches = batches or DEFAULT_BATCHES
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent="Mozilla/5.0 (compatible; PreseedFinder/1.0)")

        print(f"[yc] raccolgo la lista dai batch: {', '.join(batches)}")
        cards = _list_batches(page, batches, limit)
        total = len(cards)
        print(f"[yc] {total} aziende in lista. Estraggo i dettagli (sito/founder/email)...")

        for i, card in enumerate(cards, 1):
            if with_detail:
                try:
                    detail = _extract_detail(page, card["slug"])
                except Exception:
                    detail = {"website": None, "founder_name": None, "email": None}
            else:
                detail = {"website": None, "founder_name": None, "email": None}

            if i % 10 == 0 or i == total:
                print(f"[yc]   dettaglio {i}/{total}...")

            results.append({
                "company_name": card["company_name"],
                "website": detail["website"],
                "sector": card["sector"],
                "stage": "pre-seed/seed (YC batch recente)",
                "founder_name": detail["founder_name"],
                "email": detail["email"],
                "country": card["location"],
                "source": "yc",
            })

        browser.close()
    return results

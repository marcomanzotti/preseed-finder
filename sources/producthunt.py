import requests
import config

GRAPHQL_URL = "https://api.producthunt.com/v2/api/graphql"

QUERY = """
query RecentPosts($after: String) {
  posts(order: NEWEST, after: $after, first: 20) {
    edges {
      node {
        name
        tagline
        website
        topics {
          edges {
            node {
              name
            }
          }
        }
        makers {
          name
        }
      }
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
"""


# Cap di sicurezza: "tutti i lanci Product Hunt di sempre" non ha senso e
# l'API ha rate limit. Quando limit=None usiamo questo tetto ragionevole.
PH_MAX_WHEN_UNLIMITED = 300


def fetch(limit=None, country=None):
    if not config.PRODUCTHUNT_TOKEN:
        print("[producthunt] PRODUCTHUNT_TOKEN non configurato, fonte saltata.")
        return []

    effective_limit = limit if limit is not None else PH_MAX_WHEN_UNLIMITED

    headers = {
        "Authorization": f"Bearer {config.PRODUCTHUNT_TOKEN}",
        "Content-Type": "application/json",
    }

    results = []
    cursor = None
    while len(results) < effective_limit:
        try:
            resp = requests.post(
                GRAPHQL_URL,
                json={"query": QUERY, "variables": {"after": cursor}},
                headers=headers,
                timeout=config.REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"[producthunt] errore richiesta: {e}")
            break

        if "errors" in data:
            print(f"[producthunt] errore API: {data['errors']}")
            break

        edges = data.get("data", {}).get("posts", {}).get("edges", [])
        if not edges:
            break

        for edge in edges:
            node = edge["node"]
            topics = [t["node"]["name"] for t in node.get("topics", {}).get("edges", [])]
            makers = node.get("makers") or []
            founder_name = makers[0]["name"] if makers else None

            results.append({
                "company_name": node.get("name"),
                "website": node.get("website"),
                "sector": topics[0] if topics else None,
                "stage": "early-stage (Product Hunt launch)",
                "founder_name": founder_name,
                "email": None,
                "country": None,
                "source": "producthunt",
            })
            if len(results) >= effective_limit:
                break

        print(f"[producthunt]   {len(results)} lanci raccolti...")
        page_info = data.get("data", {}).get("posts", {}).get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    return results[:effective_limit]

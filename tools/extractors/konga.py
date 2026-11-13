"""konga.com category listings (e.g. /category/phones-tablets-5294). 40 products/page.

Notes (see workflows/scrape_website.md):
- The product grid is rendered client-side (Next.js). Plain requests HTML has no
  product cards, so the scraper falls back to Playwright automatically.
- Pagination is ?page=N and ZERO-indexed: no param / ?page=0 is page 1, ?page=1 is page 2.
  The server ignores ?page (it always embeds page-1 data); the browser loads the
  right page, so every page must be fetched with Playwright.
- Main grid cards are a[data-test-id=product-card] NOT inside a horizontal carousel
  (div.overflow-x-auto). The carousels are "sponsored / related" strips - skipped.
"""

import math
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from common import clean

DOMAINS = ["konga.com"]
COLUMNS = [
    {"key": "name", "label": "Name", "type": "text", "width": 60},
    {"key": "current_price", "label": "Current price (₦)", "type": "money", "width": 16},
    {"key": "old_price", "label": "Old price (₦)", "type": "money", "width": 14},
    {"key": "discount_pct", "label": "Discount %", "type": "percent", "width": 11},
    {"key": "url", "label": "Link", "type": "url", "width": 45},
    {"key": "sku", "label": "SKU", "type": "text", "width": 12},
]
DEDUPE_KEY = ["sku"]
REQUIRED = ["name", "current_price"]


def _in_carousel(card):
    for parent in card.parents:
        if "overflow-x-auto" in (parent.get("class") or []):
            return True
    return False


def parse_listing(soup, url):
    items = []
    for card in soup.select("a[data-test-id=product-card]"):
        if _in_carousel(card):
            continue
        title = card.select_one("[data-test-id=product-card-title]")
        name = clean.text(title.get("title") or title.get_text()) if title else None
        cur_el = card.select_one("span.font-semibold")
        old_el = card.select_one("span.line-through")
        cur = clean.money(cur_el.get_text()) if cur_el else None
        old = clean.money(old_el.get_text()) if old_el else None
        disc = round((old - cur) / old * 100) if (cur and old and old > cur) else None
        items.append({
            "name": name,
            "current_price": cur,
            "old_price": old,
            "discount_pct": disc,   # computed from the two prices shown on the card
            "url": clean.url(card.get("href"), url),
            "sku": card.get("data-test-product-sku"),
        })
    return items


def _page_index(url):
    q = parse_qs(urlsplit(url).query)
    try:
        return int(q.get("page", ["0"])[0])
    except ValueError:
        return 0


def next_page(soup, url):
    nav = soup.select_one("nav[aria-label=Pagination]")
    if not nav:
        return None
    nxt = next((b for b in nav.find_all(["button", "a"]) if "next" in b.get_text(strip=True).lower()), None)
    if nxt is None or nxt.has_attr("disabled") or nxt.get("aria-disabled") == "true":
        return None
    parts = urlsplit(url)
    q = parse_qs(parts.query)
    q["page"] = [str(_page_index(url) + 1)]
    return urlunsplit(parts._replace(query=urlencode(q, doseq=True)))


def page_count(soup, url):
    # Embedded Next.js data: "pagination":{"limit":40,"page":0,"total":870,...}
    m = re.search(r'\\?"limit\\?":(\d+),\\?"page\\?":\d+,\\?"total\\?":(\d+)', str(soup))
    if m and int(m.group(1)):
        return math.ceil(int(m.group(2)) / int(m.group(1)))
    return None

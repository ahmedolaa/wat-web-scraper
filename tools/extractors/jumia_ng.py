"""jumia.com.ng category listings (e.g. /ios-phones/). 40 products/page, ?page=N.

Robots notes (see workflows/scrape_website.md): /catalog/, ?q=, price=, sort= are
disallowed - use category pages and filter locally. Main grid is
div[data-catalog] > article.prd; the article.prd._box cards above it are a
promo carousel and are skipped.
"""

import re
from urllib.parse import urljoin

from common import clean

DOMAINS = ["jumia.com.ng"]
COLUMNS = [
    {"key": "name", "label": "Name", "type": "text", "width": 55},
    {"key": "current_price", "label": "Current price (₦)", "type": "money", "width": 16},
    {"key": "old_price", "label": "Old price (₦)", "type": "money", "width": 14},
    {"key": "discount_pct", "label": "Discount %", "type": "percent", "width": 11},
    {"key": "rating", "label": "Rating (of 5)", "type": "rating", "width": 12},
    {"key": "reviews", "label": "Reviews", "type": "number", "width": 9},
    {"key": "condition", "label": "Condition", "type": "text", "width": 13},
    {"key": "price_max", "label": "Price range top (₦)", "type": "money", "width": 16},
    {"key": "url", "label": "Link", "type": "url", "width": 45},
    {"key": "sku", "label": "SKU", "type": "text", "width": 22},
]
DEDUPE_KEY = ["sku"]
REQUIRED = ["name", "current_price"]

CONDITION = re.compile(r"\b(refurbished|renewed|uk[\s-]?used|us[\s-]?used|pre[\s-]?owned|used)\b", re.I)


def _txt(card, sel):
    el = card.select_one(sel)
    return clean.text(el.get_text()) if el else None


def parse_listing(soup, url):
    items = []
    cards = soup.select("div[data-catalog] article.prd") or soup.select("article.prd._fb")
    for card in cards:
        link = card.select_one("a.core")
        sku_el = card.select_one("[data-sku]")
        name = _txt(card, ".name")
        low, high = clean.money_range(_txt(card, ".prc"))
        stars = _txt(card, ".stars._s")            # older markup: "4.5 out of 5"
        cond = CONDITION.search(name or "")
        items.append({
            "name": name,
            "current_price": low,
            "old_price": clean.money(_txt(card, ".old")),
            "discount_pct": clean.percent(_txt(card, "._dsct")),
            "rating": clean.rating(_txt(card, ".rv-avg") or stars),
            "reviews": clean.number(_txt(card, ".rv-cnt")),
            "condition": cond.group(1).title() if cond else None,
            "price_max": high,                     # only set when the price is a range
            "url": clean.url(link.get("href"), url) if link else None,
            "sku": sku_el.get("data-sku") if sku_el else None,
        })
    return items


def next_page(soup, url):
    a = soup.select_one('a.pg[aria-label="Next Page"]')
    return urljoin(url, a["href"].split("#")[0]) if a else None


def page_count(soup, url):
    a = soup.select_one('a.pg[aria-label="Last Page"]')
    m = re.search(r"page=(\d+)", a["href"]) if a else None
    return int(m.group(1)) if m else 1

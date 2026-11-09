"""books.toscrape.com - listing pages only (20 books/page, 50 pages)."""

from urllib.parse import urljoin

from common import clean

DOMAINS = ["books.toscrape.com"]
COLUMNS = [
    {"key": "title", "label": "Title", "type": "text", "width": 50},
    {"key": "price", "label": "Price (£)", "type": "money", "width": 11},
    {"key": "rating", "label": "Rating (of 5)", "type": "rating", "width": 12},
    {"key": "in_stock", "label": "In stock", "type": "bool", "width": 10},
    {"key": "availability", "label": "Availability text", "type": "text", "width": 16},
    {"key": "url", "label": "Link", "type": "url", "width": 45},
]
DEDUPE_KEY = ["url"]
REQUIRED = ["title", "price"]


def parse_listing(soup, url):
    items = []
    for card in soup.select("article.product_pod"):
        a = card.select_one("h3 a")
        star = card.select_one("p.star-rating")
        avail = clean.text(card.select_one(".availability").get_text() if card.select_one(".availability") else None)
        price_el = card.select_one(".price_color")
        items.append({
            "title": clean.text(a.get("title") or a.get_text()) if a else None,  # title attr = full title
            "price": clean.money(price_el.get_text()) if price_el else None,
            "rating": clean.rating(" ".join(star.get("class", []))) if star else None,
            "in_stock": (None if avail is None else avail.lower().startswith("in stock")),
            "availability": avail,
            "url": clean.url(a.get("href"), url) if a else None,
        })
    return items


def next_page(soup, url):
    a = soup.select_one("li.next a")
    return urljoin(url, a["href"]) if a else None


def page_count(soup, url):
    cur = soup.select_one("li.current")
    if cur:  # "Page 1 of 50"
        n = clean.text(cur.get_text()).split("of")[-1]
        return clean.number(n)
    return None

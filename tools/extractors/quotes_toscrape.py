"""quotes.toscrape.com - 10 quotes/page, 10 pages."""

from urllib.parse import urljoin

from common import clean

DOMAINS = ["quotes.toscrape.com"]
COLUMNS = [
    {"key": "text", "label": "Quote", "type": "text", "width": 70},
    {"key": "author", "label": "Author", "type": "text", "width": 22},
    {"key": "tags", "label": "Tags", "type": "list", "width": 30},
    {"key": "author_url", "label": "About author", "type": "url", "width": 40},
]
DEDUPE_KEY = ["text", "author"]
REQUIRED = ["text", "author"]


def parse_listing(soup, url):
    items = []
    for q in soup.select("div.quote"):
        text = q.select_one("span.text")
        author = q.select_one("small.author")
        about = q.select_one("a[href*='/author/']")
        raw = clean.text(text.get_text()) if text else None
        items.append({
            "text": raw.strip("“”\"") if raw else None,   # drop curly quote marks
            "author": clean.text(author.get_text()) if author else None,
            "tags": [clean.text(t.get_text()) for t in q.select("a.tag")],
            "author_url": clean.url(about.get("href"), url) if about else None,
        })
    return items


def next_page(soup, url):
    a = soup.select_one("li.next a")
    return urljoin(url, a["href"]) if a else None

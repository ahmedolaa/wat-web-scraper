"""Extractor registry: domain -> site-specific module, else the generic extractor.

A site extractor is a module with:
    DOMAINS     list of hostnames it handles (www. is ignored)
    COLUMNS     [{"key", "label", "type", "width"}]  (types: see common/dataset.py)
    DEDUPE_KEY  list of column keys that identify one item
    REQUIRED    the "main" fields every row must have
    parse_listing(soup, url) -> list[dict]
    next_page(soup, url) -> str | None
    page_count(soup, url) -> int | None      (optional, for estimates)
To support a new site: copy one of the site files, change the selectors, add it to SITE_MODULES.
"""

import importlib
from urllib.parse import urlsplit

SITE_MODULES = ["books_toscrape", "quotes_toscrape", "jumia_ng"]


def _host(url):
    h = urlsplit(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def get(url, force=None):
    if force and force != "auto":
        return importlib.import_module(f"extractors.{force}")
    host = _host(url)
    for name in SITE_MODULES:
        mod = importlib.import_module(f"extractors.{name}")
        if host in [d.lower().removeprefix("www.") for d in mod.DOMAINS]:
            return mod
    return importlib.import_module("extractors.generic")

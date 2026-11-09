"""Paid last-resort fetcher (Firecrawl REST API). NEVER called without explicit approval.

Rule: free methods first. Before any Firecrawl use the tool prints an estimate
(credits = pages x CREDITS_PER_PAGE) plus the live balance, and exits. The agent
asks the user, and only a re-run with --approve-firecrawl spends credits.
robots.txt is still checked before every Firecrawl request.
"""

import os
from urllib.parse import urlsplit

import requests

from .http import FetchFailed, Page, PoliteFetcher

API = "https://api.firecrawl.dev/v2"
CREDITS_PER_PAGE = 1   # basic scrape, HTML format, no JSON extraction / stealth proxy


def _key() -> str:
    key = os.getenv("FIRECRAWL_API_KEY", "").strip()
    if not key:
        raise FetchFailed("FIRECRAWL_API_KEY is missing from .env")
    return key


def remaining_credits():
    """Free call - reads the balance. Returns int or None if unknown."""
    try:
        r = requests.get(f"{API}/team/credit-usage",
                         headers={"Authorization": f"Bearer {_key()}"}, timeout=20)
        data = r.json().get("data", {}) if r.ok else {}
        for k in ("remainingCredits", "remaining_credits"):
            if k in data:
                return int(data[k])
    except (requests.RequestException, ValueError, FetchFailed):
        pass
    return None


def estimate(pages: int) -> dict:
    return {
        "pages": pages,
        "credits_per_page": CREDITS_PER_PAGE,
        "estimated_credits": pages * CREDITS_PER_PAGE,
        "remaining_credits": remaining_credits(),
    }


class FirecrawlFetcher:
    def __init__(self, fetcher: PoliteFetcher, approved: bool):
        if not approved:
            raise FetchFailed("Firecrawl not approved - re-run with --approve-firecrawl after asking the user")
        self.fetcher = fetcher
        self.credits_used = 0

    def get(self, url: str) -> Page:
        f = self.fetcher
        f.check_robots(url)
        cached = f._from_cache(url, "firecrawl")
        if cached:
            return cached
        f._wait(urlsplit(url).netloc, f.effective_delay(url))
        try:
            r = requests.post(f"{API}/scrape",
                              headers={"Authorization": f"Bearer {_key()}"},
                              json={"url": url, "formats": ["html"], "onlyMainContent": False},
                              timeout=120)
            body = r.json()
        except (requests.RequestException, ValueError) as e:
            raise FetchFailed(f"Firecrawl request failed for {url}: {e}") from e
        if not r.ok or not body.get("success"):
            raise FetchFailed(f"Firecrawl error for {url}: HTTP {r.status_code} {body.get('error', '')}")
        self.credits_used += CREDITS_PER_PAGE
        data = body.get("data", {})
        status = (data.get("metadata") or {}).get("statusCode", 200)
        page = Page(url, url, status, data.get("html") or data.get("rawHtml") or "", False, "firecrawl")
        f.raise_for_problems(page)
        f.store(page)
        return page

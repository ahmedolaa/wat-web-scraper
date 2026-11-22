"""Polite page fetcher shared by every scrape.

- Honest User-Agent with an owner contact (SCRAPER_CONTACT in .env).
- robots.txt is checked before EVERY request (RFC 9309 matcher in robots.py).
- Waits between requests to the same host (default 1.5 s, or the site's
  Crawl-delay if that is longer).
- Retries 429 / 5xx with backoff.
- Caches HTML in .tmp/cache/ so re-runs don't hit the site again.
- Detects login walls and bot-challenge pages and raises clear errors.
"""

import hashlib
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv

from .robots import AllowAll, DisallowAll, RobotsRules

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / ".tmp" / "cache"
load_dotenv(ROOT / ".env")

AGENT_TOKEN = "WATScraper"
DEFAULT_DELAY = 1.5
CACHE_MAX_AGE_HOURS = 12


def user_agent() -> str:
    contact = os.getenv("SCRAPER_CONTACT", "").strip()
    return f"{AGENT_TOKEN}/1.0" + (f" (+{contact})" if contact else "")


class ScrapeStop(Exception):
    """Base class for conditions where the scrape must stop and tell the user."""
    exit_code = 1


class RobotsBlocked(ScrapeStop):
    exit_code = 2


class LoginRequired(ScrapeStop):
    exit_code = 4


class BotBlocked(ScrapeStop):
    exit_code = 5


class FetchFailed(ScrapeStop):
    exit_code = 5


@dataclass
class Page:
    url: str
    final_url: str
    status: int
    html: str
    from_cache: bool
    method: str


LOGIN_PATH = re.compile(r"/(log-?in|sign-?in|signin|auth|account/login|users/sign_in)\b", re.I)
LOGIN_WORDS = re.compile(r"\b(log ?in|sign ?in)\b", re.I)
BLOCK_MARKERS = re.compile(
    r"<title>\s*(just a moment|attention required|access denied|are you a robot)"
    r"|cf-chl-|challenges\.cloudflare\.com|g-recaptcha|hcaptcha\.com|px-captcha",
    re.I,
)


def detect_login(page: Page) -> bool:
    if page.status == 401:
        return True
    start_path = urlsplit(page.url).path
    final_path = urlsplit(page.final_url).path
    if final_path != start_path and LOGIN_PATH.search(final_path):
        return True        # we were redirected to a login page
    html = page.html[:200_000]
    if re.search(r"<input[^>]+type=[\"']?password", html, re.I):
        title = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
        heads = " ".join(re.findall(r"<h[12][^>]*>(.*?)</h[12]>", html, re.I | re.S))
        if LOGIN_WORDS.search((title.group(1) if title else "") + " " + heads):
            return True
    return False


def detect_block(page: Page) -> bool:
    return bool(BLOCK_MARKERS.search(page.html[:50_000]))


class PoliteFetcher:
    def __init__(self, delay: float = DEFAULT_DELAY, use_cache: bool = True, log=print,
                 cache_dir=None):
        self.delay = delay
        self.cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
        self.use_cache = use_cache
        self.log = log
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en;q=0.9",
        })
        self._robots = {}
        self._last_hit = {}
        self.requests_made = 0
        self.cache_hits = 0

    # ---------- robots ----------
    def robots_for(self, url: str) -> RobotsRules:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            robots_url = origin + "/robots.txt"
            try:
                self._wait(parts.netloc, self.delay)
                r = self.session.get(robots_url, timeout=20)
                self.requests_made += 1
                if r.status_code == 200:
                    rules = RobotsRules(r.text, AGENT_TOKEN)
                elif 400 <= r.status_code < 500:
                    rules = AllowAll(f"no robots.txt (HTTP {r.status_code}) - everything allowed")
                else:
                    rules = DisallowAll(f"robots.txt unreachable (HTTP {r.status_code}) - treating as disallow-all per RFC 9309")
            except requests.RequestException as e:
                rules = DisallowAll(f"robots.txt unreachable ({e.__class__.__name__}) - treating as disallow-all")
            self._robots[origin] = rules
        return self._robots[origin]

    def check_robots(self, url: str):
        rules = self.robots_for(url)
        ok, rule = rules.check(url)
        if not ok:
            raise RobotsBlocked(
                f"robots.txt does not allow {url} (rule '{rule}', group '{rules.group_used}'). "
                "Look for an allowed listing/category page on the same site instead."
            )
        return rules

    def effective_delay(self, url: str) -> float:
        cd = self.robots_for(url).crawl_delay
        return max(self.delay, cd or 0)

    # ---------- fetching ----------
    def _wait(self, host: str, delay: float):
        last = self._last_hit.get(host)
        if last is not None:
            gap = time.monotonic() - last
            if gap < delay:
                time.sleep(delay - gap)
        self._last_hit[host] = time.monotonic()

    def _cache_path(self, url: str, method: str) -> Path:
        h = hashlib.sha1(f"{method}|{url}".encode()).hexdigest()[:20]
        return self.cache_dir / f"{urlsplit(url).netloc}_{h}.html"

    def _from_cache(self, url: str, method: str):
        if not self.use_cache:
            return None
        p = self._cache_path(url, method)
        if p.exists() and (time.time() - p.stat().st_mtime) < CACHE_MAX_AGE_HOURS * 3600:
            self.cache_hits += 1
            return Page(url, url, 200, p.read_text(encoding="utf-8"), True, method)
        return None

    def _to_cache(self, page: Page):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(page.url, page.method).write_text(page.html, encoding="utf-8")

    def get(self, url: str, retries: int = 3, headers=None) -> Page:
        """headers: optional extra request headers (e.g. Accept: application/json)."""
        self.check_robots(url)
        cached = self._from_cache(url, "requests")
        if cached:
            return cached
        host = urlsplit(url).netloc
        delay = self.effective_delay(url)
        last_err = None
        for attempt in range(retries + 1):
            self._wait(host, delay)
            try:
                r = self.session.get(url, timeout=30, allow_redirects=True, headers=headers)
                self.requests_made += 1
            except requests.RequestException as e:
                last_err = f"{e.__class__.__name__}: {e}"
                time.sleep(delay * (2 ** attempt))
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = float(r.headers.get("Retry-After", 0) or 0) or delay * (2 ** (attempt + 1))
                self.log(f"  HTTP {r.status_code} on {url} - waiting {wait:.0f}s and retrying")
                time.sleep(min(wait, 120))
                continue
            r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else r.apparent_encoding
            page = Page(url, r.url, r.status_code, r.text, False, "requests")
            self.raise_for_problems(page)
            self._to_cache(page)
            return page
        raise FetchFailed(f"Could not fetch {url}: {last_err or 'retries exhausted'}")

    def raise_for_problems(self, page: Page):
        if detect_login(page):
            raise LoginRequired(
                f"{page.url} needs a login (landed on {page.final_url}). "
                "Login support is planned for version 2 - stopping."
            )
        if detect_block(page) or page.status in (403, 429):
            raise BotBlocked(
                f"{page.url} returned a bot challenge / HTTP {page.status}. "
                "Free method failed - a headless browser or Firecrawl may be needed."
            )
        if page.status >= 400:
            raise FetchFailed(f"{page.url} returned HTTP {page.status}")

    def store(self, page: Page):
        """Cache a page fetched by another method (Playwright / Firecrawl)."""
        self._to_cache(page)

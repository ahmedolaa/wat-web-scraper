"""Free fallback for JavaScript-only pages: render with a headless Chromium (Playwright).

Uses the same robots.txt check, delay and cache as PoliteFetcher.
Setup once:  pip install playwright && python -m playwright install chromium
"""

from urllib.parse import urlsplit

from .http import FetchFailed, Page, PoliteFetcher, user_agent


class BrowserFetcher:
    def __init__(self, fetcher: PoliteFetcher):
        self.fetcher = fetcher
        self._pw = self._browser = self._ctx = None

    def _start(self):
        if self._browser:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise FetchFailed("Playwright is not installed: pip install playwright && "
                              "python -m playwright install chromium") from e
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            self._ctx = self._browser.new_context(user_agent=user_agent())
        except Exception as e:  # e.g. browser not downloaded yet
            if self._pw:
                self._pw.stop()
            self._pw = self._browser = None
            first = str(e).strip().splitlines()[0][:200]
            raise FetchFailed(f"Headless browser could not start ({first}). "
                              "Fix: python -m playwright install chromium") from e

    def get(self, url: str) -> Page:
        f = self.fetcher
        f.check_robots(url)
        cached = f._from_cache(url, "playwright")
        if cached:
            return cached
        self._start()
        f._wait(urlsplit(url).netloc, f.effective_delay(url))
        pg = self._ctx.new_page()
        try:
            resp = pg.goto(url, wait_until="networkidle", timeout=45_000)
            html = pg.content()
            status = resp.status if resp else 0
            final = pg.url
        except Exception as e:  # playwright raises its own TimeoutError etc.
            raise FetchFailed(f"Headless browser could not load {url}: {e}") from e
        finally:
            pg.close()
        f.requests_made += 1
        page = Page(url, final, status, html, False, "playwright")
        f.raise_for_problems(page)
        f.store(page)
        return page

    def close(self):
        if self._browser:
            self._browser.close()
            self._pw.stop()
            self._browser = None

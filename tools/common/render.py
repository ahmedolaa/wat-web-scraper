"""Free fallback for JavaScript-only pages: render with a headless Chromium (Playwright).

Uses the same robots.txt check, delay and cache as PoliteFetcher.
Setup once:  pip install playwright && python -m playwright install chromium
"""

from urllib.parse import urlsplit

from .http import FetchFailed, Page, PoliteFetcher, user_agent


class BrowserFetcher:
    def __init__(self, fetcher: PoliteFetcher, permissions=None, block=None, profile_dir=None):
        """permissions: optional browser permissions, e.g. ["clipboard-read", "clipboard-write"].
        block: optional URL substrings the browser should not load (e.g. ad/analytics hosts whose
        overlays cover buttons). Only affects third-party extras, never the site's own pages."""
        self.fetcher = fetcher
        self.permissions = permissions
        self.block = [b.lower() for b in (block or [])]
        # profile_dir: keep a browser profile (incl. HTTP cache) on disk between runs, so large
        # immutable site assets (e.g. a slow-served JS bundle) are downloaded once, not every run.
        self.profile_dir = str(profile_dir) if profile_dir else None
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
            if self.profile_dir:
                self._ctx = self._pw.chromium.launch_persistent_context(
                    self.profile_dir, headless=True, user_agent=user_agent(),
                    permissions=self.permissions or [])
                self._browser = self._ctx          # .close() closes the persistent context
            else:
                self._browser = self._pw.chromium.launch(headless=True)
                self._ctx = self._browser.new_context(user_agent=user_agent(),
                                                      permissions=self.permissions or [])
            if self.block:
                self._ctx.route("**/*", self._route)
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
            # Some sites (e.g. Konga) never go network-idle because of analytics beacons.
            # Wait for "load", then give client-side data fetches up to 15 s to settle.
            resp = pg.goto(url, wait_until="load", timeout=45_000)
            try:
                pg.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pg.wait_for_timeout(5_000)
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

    # ---------- interactive pages (search boxes, "Next" buttons, ...) ----------
    def open(self, url: str, wait_for: str | None = None, wait_until: str = "domcontentloaded",
             timeout: int = 90_000):
        """Open a live Playwright page for sites that need typing/clicking.

        Same robots.txt check and per-host delay as get(). Not cached. The caller
        drives the page, calls pause(url) before each action that loads data,
        and must close the page. wait_for: optional CSS selector to wait for.
        """
        f = self.fetcher
        f.check_robots(url)
        self._start()
        self.pause(url)
        pg = self._ctx.new_page()
        try:
            resp = pg.goto(url, wait_until=wait_until, timeout=timeout)
            if wait_for:
                pg.wait_for_selector(wait_for, timeout=timeout)
        except Exception as e:
            pg.close()
            raise FetchFailed(f"Headless browser could not load {url}: {e}") from e
        f.requests_made += 1
        status = resp.status if resp else 0
        if status >= 400:
            pg.close()
            raise FetchFailed(f"{url} returned HTTP {status}")
        return pg

    def _route(self, route):
        u = route.request.url.lower()
        if any(b in u for b in self.block):
            route.abort()
        else:
            route.continue_()

    def pause(self, url: str):
        """Polite per-host delay before an action that makes the page load data."""
        f = self.fetcher
        f._wait(urlsplit(url).netloc, f.effective_delay(url))

    def close(self):
        if self._browser:
            self._browser.close()
            self._pw.stop()
            self._browser = None

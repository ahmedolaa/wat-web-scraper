"""General web scraper - entry point. See workflows/scrape_website.md.

Subcommands:
  inspect  robots.txt, login/bot-block check, fetch method, extractor, fields, page estimate
  preview  collect just enough pages for N (default 5) items that pass the filters, print them
  run      collect everything (up to --max-items), dedupe, filter, write .tmp/*.json,
           then export the HTML report + Excel (unless --no-export)

Examples:
  python tools/scrape.py inspect --url https://quotes.toscrape.com/
  python tools/scrape.py preview --url https://books.toscrape.com/ --columns title,price
  python tools/scrape.py run --url https://www.jumia.com.ng/ios-phones/ \
      --description "iPhones 200k-300k" --max-items all --filters @.tmp/jumia_filters.json

Fetch order: plain request -> headless browser (Playwright) -> Firecrawl.
Firecrawl is never used without --approve-firecrawl; without it the tool prints a
credit estimate and exits with code 3 so the agent can ask the user.

Exit codes: 0 ok | 2 robots.txt disallows | 3 Firecrawl approval needed |
            4 login required (v2) | 5 blocked / fetch failed | 6 nothing extracted
"""

import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bs4 import BeautifulSoup  # noqa: E402

import extractors  # noqa: E402
from common import dataset, filters  # noqa: E402
from common import firecrawl as fc  # noqa: E402
from common.http import (BotBlocked, FetchFailed, LoginRequired,  # noqa: E402
                         PoliteFetcher, RobotsBlocked, ScrapeStop, user_agent)

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".tmp"
try:
    import lxml  # noqa: F401  (fast parser)
    PARSER = "lxml"
except ImportError:
    PARSER = "html.parser"


class FirecrawlNeeded(ScrapeStop):
    exit_code = 3


class NothingExtracted(ScrapeStop):
    exit_code = 6


def log(msg=""):
    print(msg, flush=True)


# ---------------------------------------------------------------- fetching
class Fetch:
    """Picks the cheapest method that works on the first page, then sticks with it."""

    def __init__(self, args, mod):
        self.args = args
        self.mod = mod
        self.polite = PoliteFetcher(delay=args.delay, use_cache=not args.no_cache, log=log)
        self.method = None if args.method == "auto" else args.method
        self._browser = None
        self._firecrawl = None
        self.notes = []

    def _get_with(self, method, url):
        if method == "requests":
            return self.polite.get(url)
        if method == "playwright":
            if not self._browser:
                from common.render import BrowserFetcher
                self._browser = BrowserFetcher(self.polite)
            return self._browser.get(url)
        if method == "firecrawl":
            if not self._firecrawl:
                self._firecrawl = fc.FirecrawlFetcher(self.polite, approved=self.args.approve_firecrawl)
            return self._firecrawl.get(url)
        raise ValueError(method)

    def first(self, url):
        """Fetch the first page, choosing the method. Returns (page, soup, items)."""
        self.polite.check_robots(url)          # robots stop happens before any method fallback
        if self.method == "firecrawl" and not self.args.approve_firecrawl:
            raise FirecrawlNeeded(self._firecrawl_message(url, "--method firecrawl was requested"))
        order = [self.method] if self.method else ["requests", "playwright"]
        why = []
        for m in order:
            try:
                page = self._get_with(m, url)
            except (BotBlocked, FetchFailed) as e:
                why.append(f"{m}: {e}")
                log(f"  {m} failed: {e}")
                continue
            soup = BeautifulSoup(page.html, PARSER)
            items = self.mod.parse_listing(soup, page.final_url)
            if items:
                self.method = m
                if why:
                    self.notes.append(f"Used {m} because: " + " | ".join(why))
                return page, soup, items
            why.append(f"{m}: page loaded but no items found")
            log(f"  {m}: page loaded but no items were found")
        if self.args.approve_firecrawl:
            page = self._get_with("firecrawl", url)
            soup = BeautifulSoup(page.html, PARSER)
            self.method = "firecrawl"
            self.notes.append("Used Firecrawl (approved) because: " + " | ".join(why))
            return page, soup, self.mod.parse_listing(soup, page.final_url)
        raise FirecrawlNeeded(self._firecrawl_message(url, " | ".join(why)))

    def next(self, url):
        page = self._get_with(self.method, url)
        return page, BeautifulSoup(page.html, PARSER)

    def _firecrawl_message(self, url, why):
        a = self.args
        per_page = 20
        if a.max_items:
            pages = min(a.max_pages, math.ceil(a.max_items / per_page))
            basis = f"max {a.max_items} items at ~{per_page}/page (rough guess)"
        else:
            pages = a.max_pages
            basis = f"--max-pages {a.max_pages} (upper bound)"
        est = fc.estimate(pages)
        bal = est["remaining_credits"]
        return ("Free methods failed - Firecrawl would be needed.\n"
                f"  Why: {why}\n"
                f"  Estimate: {est['estimated_credits']} credits for ~{pages} pages "
                f"({est['credits_per_page']} credit/page; {basis}).\n"
                f"  Firecrawl balance: {bal if bal is not None else 'unknown'} credits.\n"
                "  ASK THE USER. If they approve, re-run with --approve-firecrawl.")

    def close(self):
        if self._browser:
            self._browser.close()

    @property
    def credits_used(self):
        return self._firecrawl.credits_used if self._firecrawl else 0


# ---------------------------------------------------------------- collecting
def resolve_columns(mod, items, wanted):
    cols = getattr(mod, "COLUMNS", None) or mod.columns_for(items)
    if not wanted:
        return cols
    by_key = {c["key"]: c for c in cols}
    keys = [k.strip() for k in wanted.split(",") if k.strip()]
    unknown = [k for k in keys if k not in by_key]
    if unknown:
        raise SystemExit(f"Unknown column(s): {unknown}. Available: {list(by_key)}")
    return [by_key[k] for k in keys]


def collect(args, mod, fetch, max_items, spec):
    t0 = time.time()
    url = args.url
    page, soup, raw = fetch.first(url)
    key = getattr(mod, "DEDUPE_KEY", None) or (mod.dedupe_key_for(raw) if hasattr(mod, "dedupe_key_for") else None)
    total_pages = mod.page_count(soup, page.final_url) if hasattr(mod, "page_count") else None
    seen, kept_all = set(), []
    removed_by_filter, filtered_samples = {}, []
    stats = {"pages": 0, "seen": 0, "dupes": 0}
    visited = set()
    stopped = None
    current_url = page.final_url
    while True:
        visited.add(current_url)
        stats["pages"] += 1
        stats["seen"] += len(raw)
        uniq, d = dataset.dedupe(raw, key, seen)
        stats["dupes"] += d
        kept, removed, samples = filters.apply(uniq, spec)
        for r, n in removed.items():
            removed_by_filter[r] = removed_by_filter.get(r, 0) + n
        filtered_samples += samples
        kept_all += kept
        of = f"/{total_pages}" if total_pages else ""
        log(f"  page {stats['pages']}{of}: {len(raw)} items, {len(uniq)} new, {len(kept)} kept "
            f"(total kept {len(kept_all)}){' [cache]' if page.from_cache else ''}")
        if max_items and len(kept_all) >= max_items:
            kept_all = kept_all[:max_items]
            stopped = f"reached max items ({max_items})"
            break
        nxt = mod.next_page(soup, page.final_url)
        if not nxt:
            stopped = "no more pages"
            break
        if nxt in visited:
            stopped = "next page link looped back"
            break
        if stats["pages"] >= args.max_pages:
            stopped = f"hit --max-pages {args.max_pages}"
            break
        try:
            page, soup = fetch.next(nxt)
        except RobotsBlocked as e:
            stopped = f"robots.txt blocks the next page: {e}"
            break
        current_url = page.final_url
        raw = mod.parse_listing(soup, page.final_url)
        if not raw:
            stopped = f"no items found on {nxt}"
            break
    return {
        "items": kept_all, "key": key, "stopped": stopped, "stats": stats,
        "removed_by_filter": removed_by_filter, "filtered_samples": filtered_samples,
        "total_pages": total_pages, "seconds": round(time.time() - t0, 1),
    }


def build_meta(args, mod, fetch, res, columns, spec, max_items):
    required = getattr(mod, "REQUIRED", None) or (mod.required_for(res["items"]) if hasattr(mod, "required_for") else [])
    return {
        "source_url": args.url,
        "description": args.description or "",
        "site": urlsplit(args.url).netloc,
        "extractor": mod.__name__.split(".")[-1],
        "method": fetch.method,
        "user_agent": user_agent(),
        "scraped_at": datetime.now().isoformat(timespec="seconds"),
        "seconds": res["seconds"],
        "pages_fetched": res["stats"]["pages"],
        "total_pages_on_site": res["total_pages"],
        "requests_made": fetch.polite.requests_made,
        "cache_hits": fetch.polite.cache_hits,
        "items_seen": res["stats"]["seen"],
        "duplicates_removed": res["stats"]["dupes"],
        "dedupe_key": res["key"] or "whole row",
        "required_fields": required,
        "filters": spec,
        "filtered_out": res["removed_by_filter"],
        "max_items": max_items or "all",
        "stopped_because": res["stopped"],
        "missing_values": dataset.missing_counts(res["items"], columns),
        "firecrawl_credits_used": fetch.credits_used,
        "notes": fetch.notes,
    }


# ---------------------------------------------------------------- printing
def fmt(v, width=40):
    if v is None or v == "" or v == []:
        return "(blank)"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, list):
        v = ", ".join(map(str, v))
    if isinstance(v, float):
        v = f"{v:,.2f}"
    elif isinstance(v, int) and not isinstance(v, bool):
        v = f"{v:,}"
    s = str(v)
    return s if len(s) <= width else s[: width - 1] + "…"


def print_items(items, columns, n=None):
    for i, it in enumerate(items[:n] if n else items, 1):
        log(f"[{i}]")
        for c in columns:
            log(f"    {c['label']:<22} {fmt(it.get(c['key']), 90)}")


# ---------------------------------------------------------------- commands
def cmd_inspect(args, mod):
    fetch = Fetch(args, mod)
    rules = fetch.polite.robots_for(args.url)
    ok, rule = rules.check(args.url)
    log(f"URL:          {args.url}")
    log(f"User-Agent:   {user_agent()}")
    log(f"robots.txt:   {'ALLOWED' if ok else 'BLOCKED'}"
        f"{' by ' + repr(rule) if rule else ''} (group '{rules.group_used}'"
        f"{', ' + rules.note if getattr(rules, 'note', '') else ''})")
    log(f"Crawl-delay:  {rules.crawl_delay or 'none'} -> waiting {fetch.polite.effective_delay(args.url)}s between requests")
    page, soup, items = fetch.first(args.url)
    columns = resolve_columns(mod, items, None)
    total_pages = mod.page_count(soup, page.final_url) if hasattr(mod, "page_count") else None
    key = getattr(mod, "DEDUPE_KEY", None) or (mod.dedupe_key_for(items) if hasattr(mod, "dedupe_key_for") else None)
    log(f"Method:       {fetch.method}  (login wall: no, bot block: no)")
    log(f"Extractor:    {mod.__name__.split('.')[-1]}")
    log(f"Items page 1: {len(items)}")
    log(f"Pages:        {total_pages or 'unknown'}"
        f"{f' -> about {total_pages * len(items):,} items' if total_pages else ''}")
    log(f"Next page:    {mod.next_page(soup, page.final_url) or 'none found'}")
    log(f"Dedupe key:   {key or 'whole row'}")
    log("Columns found (key: sample):")
    for c in columns:
        sample = next((it.get(c["key"]) for it in items if it.get(c["key"]) not in (None, "", [])), None)
        blanks = sum(1 for it in items if it.get(c["key"]) in (None, "", []))
        log(f"    {c['key']:<18} [{c['type']:<7}] {fmt(sample, 60)}   blanks on page 1: {blanks}/{len(items)}")
    for n in fetch.notes:
        log(f"Note: {n}")
    fetch.close()


def cmd_collect(args, mod, preview):
    spec = filters.load_spec(args.filters)
    max_items = args.preview_count if preview else args.max_items
    args.max_items = max_items                 # so the Firecrawl estimate matches what we'd fetch
    fetch = Fetch(args, mod)
    log(f"{'Preview' if preview else 'Run'}: {args.url}  (extractor {mod.__name__.split('.')[-1]}, "
        f"max items {max_items or 'all'}, filters {json.dumps(spec, ensure_ascii=False) if spec else 'none'})")
    try:
        res = collect(args, mod, fetch, max_items, spec)
    finally:
        fetch.close()
    if not res["items"] and res["stats"]["seen"] == 0:
        raise NothingExtracted("No items could be extracted from the page.")
    columns = resolve_columns(mod, res["items"] or [{}], args.columns)
    res["items"] = [{c["key"]: it.get(c["key"]) for c in columns} for it in res["items"]]
    meta = build_meta(args, mod, fetch, res, columns, spec, max_items)

    if preview:
        log(f"\nPREVIEW - first {len(res['items'])} item(s) "
            f"({res['stats']['pages']} page(s), {res['stats']['seen']} seen, method {fetch.method}):")
        print_items(res["items"], columns)
        if res["removed_by_filter"]:
            log(f"Filtered out so far: {res['removed_by_filter']}")
        out = TMP / "preview.json"
        dataset.write(out, meta, columns, res["items"])
        log(f"\nSaved preview to {out}. Show this to the user and wait for OK before `run`.")
        return

    host = urlsplit(args.url).netloc.replace("www.", "").split(".")[0]
    name = args.out or f"{host}_{dataset.slug(args.description or urlsplit(args.url).path)}_{datetime.now():%Y-%m-%d}"
    out = TMP / f"{name}.json"
    dataset.write(out, meta, columns, res["items"])
    if res["filtered_samples"]:
        removed_path = TMP / f"{name}_filtered_out.json"
        removed_path.write_text(json.dumps(res["filtered_samples"], ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"Filtered-out items (for spot checks): {removed_path}")
    log(f"\nDONE: {len(res['items'])} rows | {meta['pages_fetched']} pages | {meta['items_seen']} seen | "
        f"{meta['duplicates_removed']} duplicates removed | stopped: {meta['stopped_because']} | {meta['seconds']}s")
    if meta["filtered_out"]:
        log(f"Filtered out: {meta['filtered_out']}")
    blanks = {k: v for k, v in meta["missing_values"].items() if v}
    log(f"Blank values: {blanks or 'none'}")
    log(f"JSON:  {out}")
    if not args.no_export:
        import export_excel
        import export_html_report
        log(f"Excel: {export_excel.export(out)}")
        log(f"HTML:  {export_html_report.export(out, open_browser=not args.no_open)}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("inspect", "preview", "run"):
        s = sub.add_parser(name)
        s.add_argument("--url", required=True)
        s.add_argument("--extractor", default="auto", help="auto | generic | <site module name>")
        s.add_argument("--method", default="auto", choices=["auto", "requests", "playwright", "firecrawl"])
        s.add_argument("--approve-firecrawl", action="store_true", help="ONLY after the user approved the estimate")
        s.add_argument("--delay", type=float, default=1.5, help="seconds between requests (min; Crawl-delay wins if larger)")
        s.add_argument("--max-pages", type=int, default=200)
        s.add_argument("--no-cache", action="store_true")
        s.add_argument("--max-items", default="100", help="number or 'all' (default 100)")
        if name != "inspect":
            s.add_argument("--description", default="")
            s.add_argument("--filters", default="", help="JSON string or @path/to/file.json")
            s.add_argument("--columns", default="", help="comma-separated column keys, in order")
        if name == "preview":
            s.add_argument("--preview-count", type=int, default=5)
        if name == "run":
            s.add_argument("--out", default="", help="output file name (no extension) in .tmp/")
            s.add_argument("--no-export", action="store_true")
            s.add_argument("--no-open", action="store_true", help="don't open the report in the browser")
    args = p.parse_args()
    args.max_items = None if str(args.max_items).lower() == "all" else int(args.max_items)
    mod = extractors.get(args.url, args.extractor)
    try:
        if args.cmd == "inspect":
            cmd_inspect(args, mod)
        else:
            cmd_collect(args, mod, preview=(args.cmd == "preview"))
    except ScrapeStop as e:
        label = {RobotsBlocked: "BLOCKED BY ROBOTS.TXT", LoginRequired: "LOGIN REQUIRED",
                 FirecrawlNeeded: "FIRECRAWL APPROVAL NEEDED"}.get(type(e), "STOPPED")
        log(f"\n{label}: {e}")
        sys.exit(e.exit_code)


if __name__ == "__main__":
    main()

# Workflow: Scrape a website into a report

## Objective
Given a public URL and a plain-English request, collect the matching items and deliver:
- `.tmp/<name>.html`: report with a summary and a searchable, sortable table; opens in the browser
- `.tmp/<name>.xlsx`: Excel version (Data + Summary sheets)
- `.tmp/<name>.json`: raw dataset (format in `tools/common/dataset.py`)

All output stays local in `.tmp/` for this project (no Google Sheets).

## Inputs (collect before starting)
| Input | Required | Default / notes |
|---|---|---|
| URL | yes | Public page. A login page means stop (see Hard stops) |
| Description | yes | e.g. "all iPhones between ₦200k and ₦300k" |
| How many | no | 100. "all" means `--max-items all` |
| Filters | no | Translate the description into filter JSON (below) |
| Columns | no | If not given: run `inspect`, suggest columns, **ask the user** |

**If the request is unclear, ask before starting.** Examples: what counts as "an iPhone", whether a price is the current or the old price, or which page holds the data.

## Source rule: public pages only
Only scrape the public pages a person would see in a browser: category, listing and product pages, fetched with `requests` or rendered with Playwright. **Never call a site's private API or data feed** (e.g. `api.<site>.com`, GraphQL or JSON endpoints found in the page's JavaScript, internal XHR URLs), even when it looks faster or cleaner. If the public pages can't give the data, stop and tell the user. Don't look for a back door.

## Steps
1. **Inspect**: `python tools/scrape.py inspect --url <URL>`
   Shows robots.txt status, login or bot-block detection, fetch method, extractor, page-1 fields with samples, and a page/item estimate.
   - **Always try the generic extractor first** (it runs automatically when no site file exists; force it with `--extractor generic`). Judge its columns and samples.
   - If the generic results are poor (no columns, missing prices, wrong items, carousels mixed in), **explain why to the user and ask before writing a new site file** (`tools/extractors/<site>.py`, registered in `tools/extractors/__init__.py`). Never create one without a yes.
2. **Agree columns and filters** with the user. Save the filters to `.tmp/<site>_filters.json`.
3. **Preview**: `python tools/scrape.py preview --url <URL> --filters @.tmp/<f>.json --columns a,b,c`
   **Show the user the 5 items and wait for OK** before step 4. This is a hard rule, also for casual requests ("just get me 50 X"). The preview is recorded in `.tmp/previews.json`.
4. **Run**: `python tools/scrape.py run --url <URL> --description "<desc>" --max-items <N|all> --filters @... --columns ... --preview-approved`
   **Enforced in code:** `run` refuses (exit **7**) unless a preview was done for the same URL with the same filters, columns and extractor, *and* `--preview-approved` is passed. **Add `--preview-approved` only after the user says OK to the preview.** Never pass it on your own, exactly like `--approve-firecrawl`. If you change filters or columns, preview again and get a new OK.
   This writes the JSON, Excel and HTML and opens the report. Items removed by a filter are saved to `.tmp/<name>_filtered_out.json` for spot checks.
5. **Validate**: `python tools/validate_dataset.py .tmp/<name>.json [--expect-count N] [--unique k1+k2] [--required f1,f2] [--range field:min:max]`
6. **Report to the user**: row count, duplicates removed, rows removed by filters, blank counts, file paths, and anything odd.

## Filter JSON (generic, any site)
```json
{
  "name":          [{"include_regex": "\\biphone\\b"}, {"exclude_regex": "\\b(case|cover)\\b"}],
  "current_price": {"range": [200000, 300000]},
  "price_max":     {"range": [null, 300000], "allow_blank": true}
}
```
Rule keys: `range [min,max]` (null = open), `include_regex`, `exclude_regex`, `equals`, `not_blank`, `allow_blank`.
- **Write `\\b` in JSON, not `\b`.** JSON reads `\b` as a backspace character. The loader now repairs this and prints a warning, but write it correctly anyway. Note that the Bash tool collapses `\\` to `\` inside heredocs, so prefer writing filter files with the Write tool.

## Fetch order and Firecrawl (paid)
plain `requests` → Playwright headless browser (free) → Firecrawl.
- `scrape.py` picks the cheapest method that finds items on page 1.
- If the free methods fail, it exits with **code 3** and prints a credit estimate and the live balance. **Ask the user**, and only re-run with `--approve-firecrawl` if they say yes. Never pass that flag on your own.
- To test the gate safely: `--method firecrawl` without the approval flag prints the estimate and exits. No credits are spent.

## Hard stops (exit codes)
| Code | Meaning | What to do |
|---|---|---|
| 2 | robots.txt disallows the URL | Tell the user. Look for an allowed category/listing page on the same site (check with `inspect`) |
| 3 | Firecrawl needed | Show the estimate and ask the user |
| 4 | Login required | Stop: "login support is version 2" |
| 5 | Blocked / fetch failed | Retry later; try `--method playwright`; then the Firecrawl gate |
| 6 | Nothing extracted | Check selectors. Propose a site extractor and ask the user first |
| 7 | Preview approval needed | Run `preview` with the same URL/filters/columns, show the user, wait for OK, then re-run with `--preview-approved` |

## Politeness (built into the tools)
- User-Agent: `WATScraper/1.0 (+$SCRAPER_CONTACT)` from `.env`. **Never fake a browser UA**: some sites, like Jumia, block fake UAs and permit honest bots.
- robots.txt is checked before every request with our own RFC 9309 matcher (`tools/common/robots.py`). Python's `urllib.robotparser` ignores `*` wildcards, so don't use it.
- At least 1.5 s between requests (`--delay`), or the site's Crawl-delay if larger. 429/5xx responses are retried with backoff.
- Pages are cached in `.tmp/cache/` for 12 h, so re-runs and tuning filters don't hit the site again. Use `--no-cache` for fresh data.

## Rules
- Never invent data. Missing values stay blank and are counted (shown in the report and the Summary sheet).
- Dedupe by the extractor's key (generic extractor: a unique URL field, else the whole row).

## Known limitations
- **Jumia coverage:** Jumia's search pages (`/catalog/?q=`) are blocked by robots.txt, so we scrape the `/ios-phones/` category instead. iPhones listed in other categories are missed. Possible future fix: also scrape other robots-allowed phone categories (for example general smartphone or mobile-phone categories), then merge them and remove duplicates by SKU.

## Site notes / lessons learned
- **jumia.com.ng** (2026-11-09):
  - robots.txt disallows `/catalog/`, `?q=`, `price=`, `sort=`, `--` (multi-brand) and many facets for all bots. Use category pages, e.g. `/ios-phones/` (Apple phones; also lists iPads and a few Xiaomi), with `?page=N`, and filter locally.
  - robots.txt requires an honest bot UA with an owner contact. A fake Chrome UA got a Cloudflare "Just a moment" page; `WATScraper/1.0 (+contact)` got HTTP 200 with full server-rendered HTML, so no JS or Firecrawl is needed.
  - The main grid is `div[data-catalog] article.prd`. The `article.prd._box` cards above it are a promo carousel, so skip them.
  - The category header says "657 products", but only 654 unique SKUs are listed across 17 pages. Pages can take 10–25 s each.
  - Some listings are named "Appleline 11 …" or "Appleline XR … Dual SIM" with no "iPhone" in the name. They are possibly not genuine iPhones. **User decision (2026-11-09): exclude them.** "iPhones only" means the name must contain "iPhone".
- **konga.com** (2026-11-13), extractor `tools/extractors/konga.py`:
  - robots.txt allows `/category/...` and `?page=` (disallows `/search`, `/category/-`, `/product/-`, `/product/*/details`).
  - The product grid is rendered client-side (Next.js). Plain requests HTML has **no product cards**, so the tool falls back to Playwright on its own. Use `--method playwright`.
  - `?page=N` is **zero-indexed** (`?page=1` is the second page). The server ignores it and always embeds page-1 data, so every page must go through Playwright. 40 items/page.
  - Cards are `a[data-test-id=product-card]`. Skip the ones inside the horizontal carousels (`div.overflow-x-auto`, sponsored/related strips). Current price is `span.font-semibold`, old price is `span.line-through`.
  - `networkidle` never fires on Konga (analytics beacons), so `render.py` now waits for `load` plus up to 15 s for network idle instead of timing out.
  - `/category/phones-tablets-5294` is mostly accessories (cables, earbuds, power banks, holders) and a few tablets. For "phones", filter with `.tmp/konga_filters.json`: the name must contain storage/RAM specs (`\d+gb`, `rom`, `ram`), and pad/tab/watch/accessory words are excluded. Roughly 1 in 4 items is a phone, so 50 phones took 5 pages. Known miss: desk GSM phones with no GB spec (e.g. "Imose Im-10d Pro").
  - Calling Konga's GraphQL API (`api.konga.com/v1/graphql`) directly was blocked by the agent permission system. Stick to rendering the public pages.
- **Process lessons from the first Konga test (2026-11-13, casual request "get me 50 phones with prices")**. Three rules were broken:
  1. **Preview skipped.** The agent went straight to `run` without showing the 5-item preview. Fix: the preview gate is now enforced in `scrape.py` (exit 7, `--preview-approved`, see Steps 3–4). Casual wording is not permission to skip the preview.
  2. **Site file written without asking.** The generic extractor found no columns, and the agent wrote `konga.py` on its own. Fix: always try generic first, explain why its results are poor, and ask before writing a site file. (`konga.py` was kept because it was already written.)
  3. **Hidden API attempt.** The agent dug the GraphQL endpoint out of Konga's JavaScript and tried to call it. Fix: the "public pages only" source rule above. Never call a site's private API or data feed.
- **books.toscrape.com / quotes.toscrape.com**: no robots.txt (404), so everything is allowed. Static HTML.
- **Playwright setup**: `pip install playwright` is not enough. `python -m playwright install chromium` must also finish (it downloads Chromium *and* a separate headless shell, about 150 MB+, slow on this connection). If the browser is missing, the tool reports it and moves on to the Firecrawl gate instead of crashing. Test page for the JS path: `https://quotes.toscrape.com/js/` (plain requests finds 0 items there).
- **Speed**: install `lxml` (in requirements). Without it, BeautifulSoup falls back to `html.parser` and a 700 KB Jumia page takes about 13 s to parse instead of about 2 s.
- **Generic vs. site extractor (quotes.toscrape.com test, 2026-11-09)**: the generic extractor found all 100 quotes with correct author, author link and tags. Its differences: it keeps the curly “ ” marks around quotes, names columns from CSS classes (`tag`, `link_url`), adds an extra `tag_url` column, and dedupes on the whole row because it can't tell which field is the ID. A bug (single tags stored as text, not a list) was fixed in `generic.py`. Use generic for a first look; write a site file for anything you'll repeat.
- **Network flakiness**: we saw intermittent DNS failures (`getaddrinfo failed`) and an `SSLEOFError` from Jumia that went away on retry. The fetcher retries connection errors with backoff; if a whole run fails this way, just re-run, since cached pages are reused.

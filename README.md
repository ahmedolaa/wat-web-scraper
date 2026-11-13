# WAT Web Scraper

You give it a public web page and a plain-English request, such as *"all iPhones between ₦200k and ₦300k"*. It collects the matching items into a searchable HTML report, an Excel file and a JSON file. It is built for people who need clean data from listing pages, such as prices, products or quotes, without writing a scraper each time. It is also a working example of an AI agent that follows rules instead of improvising.

## How it works: the WAT framework

| Layer | What it is | Where it lives |
|---|---|---|
| **Workflows** | Plain-language instructions: steps, rules, lessons learned | `workflows/` |
| **Agent** | An AI assistant (Claude Code) that reads the workflow, asks questions and runs the tools | the chat |
| **Tools** | Testable Python scripts that fetch, parse, filter and export | `tools/` |

The AI makes the decisions and plain code does the work, so a single AI slip can't silently derail a multi-step job.

## Key features

- **Free first:** plain requests, then a free headless browser (Playwright). Paid Firecrawl runs only after the user approves a cost estimate.
- **Preview enforced in code:** `run` refuses to start unless the user has seen and approved a matching preview.
- **robots.txt respected** using our own checker, because Python's built-in parser ignores `*` wildcards.
- **Public pages only, honest User-Agent:** no private APIs, and it never pretends to be a browser.
- **No invented data:** missing values stay blank and are counted. Output is HTML + Excel + JSON.

## Example

```bash
python tools/scrape.py preview --url https://books.toscrape.com/ --columns title,price,rating,url
python tools/scrape.py run --url https://books.toscrape.com/ --columns title,price,rating,url \
    --max-items all --preview-approved     # only after the preview is approved
```

Setup: `pip install -r requirements.txt`, `python -m playwright install chromium`, then copy `.env.example` to `.env`. Full process: [`workflows/scrape_website.md`](workflows/scrape_website.md).

## Test results

| Site | Result |
|---|---|
| books.toscrape.com | **1,000 / 1,000** books, 50 pages, 0 duplicates |
| quotes.toscrape.com | **100 / 100** quotes, with both the site extractor and the generic extractor |
| jumia.com.ng (`/ios-phones/`) | 654 listings over 17 pages, filtered to iPhones priced ₦200k–300k (1 match). Needed robots.txt-safe category pages and an honest User-Agent (a fake browser UA was blocked) |
| konga.com: "break-it" test | 50 phones with prices from a page that renders in JavaScript (fell back to Playwright automatically). The real value of this test was **what it exposed** (see below) |

**What the Konga break-it test fixed.** A deliberately casual request ("get me 50 phones") showed the agent cutting corners. It:
1. **Skipped the preview.** Fix: the preview is now enforced in code (exit 7 plus `--preview-approved`), not just written in the instructions.
2. **Wrote a new site file without asking.** Fix: the workflow now requires trying the generic extractor first, explaining why its results are poor and asking before writing a new file.
3. **Tried to call the site's hidden API.** Fix: a new "public pages only" rule.

## Known limitations

- **Search pages:** some sites block bots from their search pages, so the scraper uses category pages instead and can miss items listed in other categories (seen on Jumia).
- **No login support:** pages behind a login are detected and the tool stops (exit 4). Login support is planned for **version 2**.
- Listing pages only, no product detail pages. Some sites need their own extractor for clean columns.

## About

Built as a learning project with [Claude Code](https://claude.com/claude-code), exploring how to make an AI agent reliable: keep the AI on decisions, move the execution into code, and turn every failure into a rule or a fix.

"""The dataset JSON format every tool reads and writes.

{
  "meta": {
    "source_url", "description", "site", "extractor", "method", "scraped_at",
    "pages_fetched", "requests_made", "cache_hits", "items_seen",
    "duplicates_removed", "filters", "filtered_out": {reason: n},
    "max_items", "stopped_because", "missing_values": {column_key: n},
    "firecrawl_credits_used", "notes": [..]
  },
  "columns": [{"key", "label", "type": text|number|money|rating|percent|url|list|bool, "width"}],
  "items": [ {column_key: value or null}, ... ]
}
"""

import hashlib
import json
import re
from pathlib import Path


def blank(v):
    return v is None or v == "" or v == []


def key_of(item, key_fields):
    if key_fields:
        parts = [str(item.get(k) or "") for k in key_fields]
        if any(parts):
            return "|".join(parts).strip().lower()
    return hashlib.sha1(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()


def dedupe(items, key_fields, seen=None):
    """Drop repeats. Returns (unique_items, removed_count). `seen` can be shared across pages."""
    seen = set() if seen is None else seen
    out, removed = [], 0
    for it in items:
        k = key_of(it, key_fields)
        if k in seen:
            removed += 1
            continue
        seen.add(k)
        out.append(it)
    return out, removed


def missing_counts(items, columns):
    return {c["key"]: sum(1 for it in items if blank(it.get(c["key"]))) for c in columns}


def slug(s, limit=40):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:limit].strip("-") or "scrape"


def write(path: Path, meta, columns, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"meta": meta, "columns": columns, "items": items},
                               ensure_ascii=False, indent=2), encoding="utf-8")


def read(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for k in ("meta", "columns", "items"):
        if k not in data:
            raise ValueError(f"{path} is not a scraper dataset (missing '{k}')")
    return data

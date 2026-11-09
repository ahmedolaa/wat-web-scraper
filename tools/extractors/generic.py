"""Generic extractor for sites with no site-specific file.

How it works (no site knowledge):
1. Find the "item list": among all groups of sibling elements that share the same
   tag + classes and repeat 3+ times, pick the group with the most content
   (count x average text length, bonus if items contain links). Nav/header/footer are ignored.
2. Inside each item, every element with its own text becomes a field named after its
   first CSS class (or its tag); every link becomes <name>_url; the first image is `image`.
   An element repeated inside one item (e.g. tags) becomes a list.
3. Fields that are the same in every item ("by", "Tags:") are dropped as labels; fields
   present in under 30% of items are dropped as noise. Mostly-currency fields become numbers.
Results are a best guess - always preview, and write a site file if they're not good enough.
"""

import re
from collections import defaultdict
from urllib.parse import urljoin

from common import clean

DOMAINS = []
DEDUPE_KEY = None
SKIP = {"script", "style", "noscript", "svg", "head", "meta", "link", "template", "iframe", "form", "select", "option"}
SKIP_REGIONS = {"nav", "header", "footer", "aside"}
CURRENCY = re.compile(r"^\s*[-+]?\s*([$£€₦¥₹]|ngn|usd|gbp|eur)\s*\d|\d[\d,.]*\s*([$£€₦]|ngn|usd)\s*$", re.I)
MIN_REPEAT = 3


def _sig(el):
    return el.name + "." + ".".join(sorted(el.get("class", [])))


def _in_skip_region(el):
    for p in el.parents:
        if p.name in SKIP_REGIONS:
            return True
        role = (p.get("role") or "") if hasattr(p, "get") else ""
        if role in ("navigation", "banner", "contentinfo"):
            return True
    return False


def find_items(soup):
    best, best_score = [], 0
    for parent in soup.find_all(True):
        if parent.name in SKIP:
            continue
        groups = defaultdict(list)
        for child in parent.find_all(True, recursive=False):
            if child.name not in SKIP:
                groups[_sig(child)].append(child)
        for sig, els in groups.items():
            if len(els) < MIN_REPEAT:
                continue
            lens = [len(clean.text(e.get_text(" ")) or "") for e in els]
            avg = sum(lens) / len(lens)
            if avg < 15:                     # menus, pagers, tag clouds
                continue
            with_link = sum(1 for e in els if e.find("a", href=True)) / len(els)
            depth = sum(1 for e in els if len(e.find_all(True)) >= 2) / len(els)
            score = len(els) * min(avg, 400) * (0.5 + with_link) * (0.5 + depth)
            if _in_skip_region(parent):
                score *= 0.1
            if score > best_score:
                best, best_score = els, score
    return best


def _name(el):
    classes = [c for c in el.get("class", []) if re.match(r"^[A-Za-z][\w-]{1,30}$", c)]
    base = classes[0] if classes else el.name
    return re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_") or el.name


def _fields(item, base_url):
    out = defaultdict(list)
    img = item.find("img")
    if img:
        src = img.get("data-src") or img.get("src")
        if src and not src.startswith("data:"):
            out["image"].append(urljoin(base_url, src))
    for el in [item] + item.find_all(True):
        if el.name in SKIP:
            continue
        own = clean.text(" ".join(s for s in el.find_all(string=True, recursive=False)))
        name = _name(el)
        if own:
            out[name].append(own)
        if el.name == "a" and el.get("href") and not el["href"].startswith(("#", "javascript:")):
            out[("link" if name == "a" else name) + "_url"].append(urljoin(base_url, el["href"]))
    return {k: (v[0] if len(v) == 1 else v) for k, v in out.items()}


def parse_listing(soup, url):
    raw = [_fields(it, url) for it in find_items(soup)]
    if not raw:
        return []
    keys = []
    for r in raw:
        for k in r:
            if k not in keys:
                keys.append(k)
    keep = []
    for k in keys:
        vals = [r.get(k) for r in raw]
        present = [v for v in vals if v not in (None, "", [])]
        if len(present) < 0.3 * len(raw):
            continue
        if len(raw) > 1 and len(present) == len(raw) and len({str(v) for v in present}) == 1:
            continue                          # constant label like "by" or "Tags:"
        keep.append(k)
    items = []
    for r in raw:
        items.append({k: r.get(k) for k in keep})
    for k in keep:                            # a field that is a list anywhere is a list everywhere
        if any(isinstance(i[k], list) for i in items):
            for i in items:
                if isinstance(i[k], str):
                    i[k] = [i[k]]
    for k in keep:                            # currency text -> numbers
        vals = [i[k] for i in items if isinstance(i[k], str)]
        if vals and sum(bool(CURRENCY.search(v)) for v in vals) >= 0.8 * len(vals):
            for i in items:
                i[k] = clean.money(i[k]) if isinstance(i[k], str) else None
    return items


def columns_for(items):
    cols = []
    for k in (items[0].keys() if items else []):
        vals = [i.get(k) for i in items if i.get(k) not in (None, "", [])]
        if any(isinstance(v, list) for v in vals):
            t = "list"
        elif vals and all(isinstance(v, (int, float)) for v in vals):
            t = "money"
        elif k.endswith("_url") or k == "image":
            t = "url"
        else:
            t = "text"
        cols.append({"key": k, "label": k.replace("_", " ").title(), "type": t,
                     "width": 45 if t == "url" else 30})
    return cols


def dedupe_key_for(items):
    for k in (items[0].keys() if items else []):
        vals = [i.get(k) for i in items]
        if k.endswith("_url") and all(isinstance(v, str) and v for v in vals) and len(set(vals)) == len(vals):
            return [k]
    return None                               # fall back to whole-row hash


def required_for(items):
    for k in (items[0].keys() if items else []):
        if not k.endswith("_url") and k != "image" and all(isinstance(i.get(k), str) for i in items):
            return [k]
    return []


def next_page(soup, url):
    link = soup.find(["a", "link"], attrs={"rel": "next"}, href=True)
    if not link:
        for a in soup.find_all("a", href=True):
            t = clean.text(a.get_text()) or clean.text(a.get("aria-label")) or ""
            if re.match(r"^(next|older|more)\b|^[›»→>]+$", t, re.I) and not a["href"].startswith(("#", "javascript:")):
                link = a
                break
    return urljoin(url, link["href"].split("#")[0]) if link else None

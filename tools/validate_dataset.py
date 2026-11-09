"""Check a scraper dataset against the "done" rules. Exits 1 if any check fails.

Usage:
    python tools/validate_dataset.py .tmp/<dataset>.json \
        --expect-count 1000 --unique url --required title,price \
        --range current_price:200000:300000

--unique accepts a combined key: text+author. Defaults when flags are omitted:
--unique = the dataset's dedupe key, --required = the dataset's required fields.
Always prints blank-value counts per column.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import dataset  # noqa: E402


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    p = argparse.ArgumentParser()
    p.add_argument("dataset")
    p.add_argument("--expect-count", type=int)
    p.add_argument("--unique", help="key field(s), e.g. url or text+author")
    p.add_argument("--required", help="comma-separated fields every row must have")
    p.add_argument("--range", action="append", default=[], help="field:min:max (blank = open end)")
    a = p.parse_args()

    data = dataset.read(a.dataset)
    items, meta = data["items"], data["meta"]
    ok = True

    def result(passed, msg):
        nonlocal ok
        ok &= passed
        print(f"[{'PASS' if passed else 'FAIL'}] {msg}")

    print(f"{a.dataset}: {len(items)} rows")
    if a.expect_count is not None:
        result(len(items) == a.expect_count, f"row count {len(items)} == expected {a.expect_count}")

    dk = meta.get("dedupe_key")
    key = a.unique.split("+") if a.unique else (dk if isinstance(dk, list) else None)
    keys = [dataset.key_of(it, key) for it in items]
    dupes = len(keys) - len(set(keys))
    result(dupes == 0, f"no duplicates on {'+'.join(key) if key else 'whole row'} ({dupes} found)")

    req = a.required.split(",") if a.required else meta.get("required_fields") or []
    for f in req:
        missing = [i for i, it in enumerate(items, 1) if dataset.blank(it.get(f))]
        result(not missing, f"every row has '{f}'" + (f" - missing in rows {missing[:10]}" if missing else ""))

    for spec in a.range:
        field, lo, hi = spec.split(":")
        lo = float(lo) if lo else None
        hi = float(hi) if hi else None
        bad = [(i, it.get(field)) for i, it in enumerate(items, 1)
               if not isinstance(it.get(field), (int, float))
               or (lo is not None and it[field] < lo) or (hi is not None and it[field] > hi)]
        result(not bad, f"every '{field}' within [{lo}, {hi}]" + (f" - bad: {bad[:10]}" if bad else ""))

    print("Blank values per column:", {c["key"]: n for c in data["columns"]
                                       for n in [sum(1 for it in items if dataset.blank(it.get(c["key"])))]})
    print("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

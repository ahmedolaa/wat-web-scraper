"""Generic, JSON-driven filters. The agent turns the user's plain-English request
into a spec like:

    {
      "name":          [{"include_regex": "\\biphone\\b"}, {"exclude_regex": "\\bcase\\b"}],
      "current_price": {"range": [200000, 300000]},
      "price_max":     {"range": [null, 300000], "allow_blank": true}
    }

Rule keys (one or more per rule):
  range: [min, max]   numeric, inclusive, null = open end
  include_regex       keep only if the text matches (case-insensitive)
  exclude_regex       drop if the text matches (case-insensitive)
  equals              keep only exact (case-insensitive) match
  not_blank: true     drop rows where the field is empty
  allow_blank: true   a blank value passes this rule (default: blank fails range/include/equals)
List fields (e.g. tags) are joined with ", " for text rules.
"""

import json
import re
from collections import Counter
from pathlib import Path


def load_spec(arg):
    if not arg:
        return {}
    if isinstance(arg, dict):
        spec = arg
    elif arg.startswith("@"):
        spec = json.loads(Path(arg[1:]).read_text(encoding="utf-8"))
    else:
        spec = json.loads(arg)
    return _repair_regexes(spec)


# JSON turns "\b" into a backspace and "\f" into a form feed, so a regex written
# with single backslashes silently matches nothing. Repair and warn.
_CONTROL = {"\b": "\\b", "\f": "\\f", "\t": "\\t", "\r": "\\r", "\v": "\\v"}


def _repair_regexes(spec):
    for field, rules in spec.items():
        for rule in (rules if isinstance(rules, list) else [rules]):
            for k in ("include_regex", "exclude_regex"):
                v = rule.get(k)
                if isinstance(v, str) and any(c in v for c in _CONTROL):
                    fixed = "".join(_CONTROL.get(c, c) for c in v)
                    print(f"  WARNING: filter {field}.{k} had JSON escape damage "
                          f"(write \\\\b in JSON for \\b) - repaired to /{fixed}/")
                    rule[k] = fixed
                if isinstance(rule.get(k), str):
                    re.compile(rule[k])          # fail fast on a bad regex
    return spec


def _blank(v):
    return v is None or v == "" or v == []


def _as_text(v):
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return "" if v is None else str(v)


def _check(value, rule):
    """Return None if the value passes, else a short reason string."""
    blank = _blank(value)
    if blank and rule.get("allow_blank"):
        return None
    if rule.get("not_blank") and blank:
        return "blank"
    if "range" in rule:
        lo, hi = rule["range"]
        if blank or not isinstance(value, (int, float)):
            return "blank / not a number"
        if lo is not None and value < lo:
            return f"below {lo:,}"
        if hi is not None and value > hi:
            return f"above {hi:,}"
    if "include_regex" in rule:
        if blank or not re.search(rule["include_regex"], _as_text(value), re.I):
            return f"does not match /{rule['include_regex']}/"
    if "exclude_regex" in rule:
        if not blank and re.search(rule["exclude_regex"], _as_text(value), re.I):
            return f"matches excluded /{rule['exclude_regex']}/"
    if "equals" in rule:
        if blank or _as_text(value).strip().lower() != str(rule["equals"]).strip().lower():
            return f"not equal to {rule['equals']!r}"
    return None


def apply(items, spec):
    """Return (kept, removed_counter, removed_samples).
    removed_counter maps 'field: reason' -> count (first failing rule only)."""
    if not spec:
        return list(items), Counter(), []
    kept, removed, samples = [], Counter(), []
    for item in items:
        reason = None
        for field, rules in spec.items():
            for rule in (rules if isinstance(rules, list) else [rules]):
                why = _check(item.get(field), rule)
                if why:
                    reason = f"{field}: {why}"
                    break
            if reason:
                break
        if reason:
            removed[reason] += 1
            samples.append({"reason": reason, "item": item})
        else:
            kept.append(item)
    return kept, removed, samples

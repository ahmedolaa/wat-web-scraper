"""Value cleaners. Each returns None when the value is missing or unreadable -
never a guess. Missing values stay blank and get counted."""

import re
from urllib.parse import urljoin

WORD_NUMBERS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
NUM = r"\d[\d,]*(?:\.\d+)?"


def text(value):
    if value is None:
        return None
    s = re.sub(r"\s+", " ", str(value)).strip()
    return s or None


def number(value):
    """First number in the string: '1,234.50' -> 1234.5; None if absent."""
    s = text(value)
    if not s:
        return None
    m = re.search(NUM, s)
    if not m:
        return None
    n = float(m.group(0).replace(",", ""))
    return int(n) if n.is_integer() else n


def money(value):
    """'₦ 250,000' -> 250000, '£51.77' -> 51.77. For a range, returns the LOW end;
    use money_range() when you need both ends."""
    low, _ = money_range(value)
    return low


def money_range(value):
    """'₦ 250,000 - ₦ 300,000' -> (250000, 300000); single price -> (p, None)."""
    s = text(value)
    if not s:
        return None, None
    nums = re.findall(NUM, s)
    vals = [float(n.replace(",", "")) for n in nums]
    vals = [int(v) if v.is_integer() else v for v in vals]
    if not vals:
        return None, None
    if len(vals) >= 2 and re.search(r"\d\s*[-–]\s*\D*\d", s):
        return vals[0], vals[1]
    return vals[0], None


def percent(value):
    """'-50%' -> 50 (discount size as a positive number)."""
    n = number(value)
    return abs(n) if n is not None else None


def rating(value, out_of=5):
    """'4.5 out of 5' -> 4.5, 'Three' -> 3, 'star-rating Four' -> 4."""
    s = text(value)
    if not s:
        return None
    for word, n in WORD_NUMBERS.items():
        if re.search(rf"\b{word}\b", s, re.I):
            return n
    n = number(s)
    return n if n is not None and 0 <= n <= out_of else None


def url(value, base):
    s = text(value)
    return urljoin(base, s) if s else None

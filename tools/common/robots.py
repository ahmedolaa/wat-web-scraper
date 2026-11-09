"""robots.txt matcher that follows RFC 9309.

Why not urllib.robotparser? It ignores '*' and '$' wildcards, so a rule like
`Disallow: /*q=` is silently skipped and blocked URLs look allowed.

Rules implemented:
- The crawler obeys exactly ONE group: the one whose user-agent token matches
  ours (case-insensitive), else the '*' group. Groups with the same token merge.
- '*' matches any run of characters, '$' anchors the end of the path.
- The longest matching rule wins; on a tie, Allow wins.
- /robots.txt itself is always allowed.
"""

import re
from urllib.parse import urlsplit


class RobotsRules:
    def __init__(self, text: str, agent_token: str):
        self.agent_token = agent_token.lower()
        self.rules = []          # list of (allow: bool, pattern: str, regex)
        self.crawl_delay = None
        self.group_used = None   # which user-agent group we obey
        self._parse(text or "")

    def _parse(self, text: str):
        groups = []              # list of (agents:set, rules:list, delay)
        agents, rules, delay = set(), [], None
        in_rules = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            field, value = line.split(":", 1)
            field, value = field.strip().lower(), value.strip()
            if field == "user-agent":
                if in_rules:     # a new group starts
                    groups.append((agents, rules, delay))
                    agents, rules, delay, in_rules = set(), [], None, False
                agents.add(value.lower())
            elif field in ("allow", "disallow"):
                in_rules = True
                if value:        # empty Disallow means "allow all"
                    rules.append((field == "allow", value))
            elif field == "crawl-delay":
                in_rules = True
                try:
                    delay = float(value)
                except ValueError:
                    pass
        if agents:
            groups.append((agents, rules, delay))

        mine = [g for g in groups if self.agent_token in g[0]]
        if mine:
            self.group_used = self.agent_token
        else:
            mine = [g for g in groups if "*" in g[0]]
            self.group_used = "*" if mine else None
        for _, grules, gdelay in mine:
            for allow, pattern in grules:
                self.rules.append((allow, pattern, _compile(pattern)))
            if gdelay is not None:
                self.crawl_delay = max(self.crawl_delay or 0, gdelay)

    def check(self, url: str):
        """Return (allowed: bool, matching_rule: str|None)."""
        parts = urlsplit(url)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        if parts.path == "/robots.txt":
            return True, None
        best = None              # (length, allow, pattern)
        for allow, pattern, regex in self.rules:
            if regex.match(path):
                key = (len(pattern), allow)
                if best is None or key > (best[0], best[1]):
                    best = (len(pattern), allow, pattern)
        if best is None:
            return True, None
        return best[1], f"{'Allow' if best[1] else 'Disallow'}: {best[2]}"

    def allowed(self, url: str) -> bool:
        return self.check(url)[0]


def _compile(pattern: str):
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    if not pattern.startswith(("/", "*")):
        pattern = "/" + pattern if not pattern.startswith("*") else pattern
    body = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.compile(body + ("$" if anchored else ""))


class AllowAll(RobotsRules):
    def __init__(self, note: str = ""):
        super().__init__("", "")
        self.note = note


class DisallowAll(RobotsRules):
    def __init__(self, note: str = ""):
        super().__init__("User-agent: *\nDisallow: /", "")
        self.note = note

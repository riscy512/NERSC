"""
Expand node name tokens that use bracket range syntax.

Example:
  nid[7002-7007,7009,7012-7029]
    -> nid7002, nid7003, ..., nid7007, nid7009, nid7012, ..., nid7029

Each comma-separated segment is either a single integer or M-N (inclusive). Ranges
where M > N are swapped. Numeric parts are zero-padded to a common width inferred
from all numbers produced (e.g. 1-10 and 100 -> width 3 -> nid001 ... nid010, nid100).

Tokens without brackets are returned unchanged (one element per token).
"""

from __future__ import annotations

import re
from typing import List

_BRACKET = re.compile(r"^([^[\]]+)\[([^\]]+)\]\s*$")


def expand_node_token(token: str) -> List[str]:
    """
    If token matches PREFIX[body], expand; otherwise return [token.strip()] if non-empty.
    """
    t = token.strip()
    if not t:
        return []
    m = _BRACKET.match(t)
    if not m:
        return [t]
    prefix, body = m.group(1).strip(), m.group(2).strip()
    if not prefix or not body:
        raise ValueError(f"empty prefix or bracket body: {token!r}")
    numbers: list[int] = []
    for seg in body.split(","):
        seg = seg.strip()
        if not seg:
            continue
        if "-" in seg:
            lo_s, hi_s = seg.split("-", 1)
            lo, hi = int(lo_s.strip()), int(hi_s.strip())
            if lo > hi:
                lo, hi = hi, lo
            numbers.extend(range(lo, hi + 1))
        else:
            numbers.append(int(seg))
    if not numbers:
        raise ValueError(f"no numbers in bracket expression: {token!r}")
    width = max(len(str(n)) for n in numbers)
    return [f"{prefix}{n:0{width}d}" for n in numbers]


def expand_node_tokens(tokens: list[str]) -> list[str]:
    """Expand each token; concatenate in order. Bracket tokens expand to many names."""
    out: list[str] = []
    for tok in tokens:
        out.extend(expand_node_token(tok))
    return out

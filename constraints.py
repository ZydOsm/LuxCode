"""Constraint-to-complexity heuristics: best-effort extraction of the input
size bound (N) from a LeetCode problem statement, plus a rule-of-thumb
mapping from N to which Big-O classes are realistically fast enough.

This is a heuristic, not a guarantee — real time limits vary per problem and
per judge. The ~10^8 operations/second budget is the standard competitive-
programming rule of thumb for a ~1-2 second limit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

OPS_BUDGET = 10**8

# Matches "10^5", "10 ^ 5", and plain big integers (with optional thousands separators)
# appearing near a comparison, e.g. "1 <= n <= 10^5" or "n.length <= 100000".
_POWER_RE = re.compile(r"10\s*\^\s*(\d{1,2})")
_PLAIN_RE = re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d{4,9})\b")


_SIZE_KEYWORDS = ("length", "size", ".size()", "number of")


def _numbers_in(s: str) -> list[int]:
    vals = [10 ** int(m.group(1)) for m in _POWER_RE.finditer(s)]
    for m in _PLAIN_RE.finditer(s):
        try:
            vals.append(int(m.group(1).replace(",", "")))
        except ValueError:
            continue
    return [v for v in vals if 1 <= v <= 10**18]


def extract_n(content_text: str) -> int | None:
    """Best-effort: return the input SIZE bound (array/string length), not a
    value-range bound — "nums.length <= 10^4" matters for complexity, not
    "-10^9 <= nums[i] <= 10^9". Falls back to the largest number seen if no
    line clearly describes a count/length/size."""
    if not content_text:
        return None
    # Only look at the tail of the statement, where "Constraints:" usually lives.
    idx = content_text.lower().rfind("constraint")
    region = content_text[idx:] if idx != -1 else content_text

    size_candidates: list[int] = []
    other_candidates: list[int] = []
    for line in region.splitlines():
        nums = _numbers_in(line)
        if not nums:
            continue
        (size_candidates if any(kw in line.lower() for kw in _SIZE_KEYWORDS) else other_candidates).extend(nums)

    if size_candidates:
        return max(size_candidates)
    return max(other_candidates) if other_candidates else None


@dataclass
class ComplexityEstimate:
    label: str
    formula: str
    ops: float
    safe: bool


_CLASSES = [
    ("O(1)", "constant", lambda n: 1),
    ("O(log n)", "logarithmic", lambda n: max(1.0, __import__("math").log2(max(n, 2)))),
    ("O(n)", "linear", lambda n: n),
    ("O(n log n)", "linearithmic", lambda n: n * max(1.0, __import__("math").log2(max(n, 2)))),
    ("O(n" + chr(0x00B2) + ")", "quadratic", lambda n: n ** 2),
    ("O(n" + chr(0x00B3) + ")", "cubic", lambda n: n ** 3),
    ("O(2" + chr(0x207F) + ")", "exponential", lambda n: 2.0 ** min(n, 200)),
]


def estimate(n: int) -> list[ComplexityEstimate]:
    results = []
    for label, _name, fn in _CLASSES:
        ops = fn(n)
        results.append(ComplexityEstimate(label=label, formula=_name, ops=ops, safe=ops <= OPS_BUDGET))
    return results


def recommendation(n: int) -> str:
    safe = [e.label for e in estimate(n) if e.safe]
    if not safe:
        return "Even O(1) looks borderline at this scale, double-check the bound."
    fastest_unsafe = next((e.label for e in estimate(n) if not e.safe), None)
    msg = f"Aim for {' or '.join(safe[-2:])}."
    if fastest_unsafe:
        msg += f" {fastest_unsafe} and slower will likely time out."
    return msg

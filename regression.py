"""Runs every official LeetCode example against the user's solution — not
just the first one (which is all the Trace tab uses) — and compares against
an expected output parsed best-effort from the problem statement's prose.

LeetCode's public API doesn't expose verified expected outputs in structured
form, only what's written in the "Output: ..." lines of the problem
statement text. Parsing is therefore best-effort: when it can't confidently
match an example to its expected output, the case is still run (so crashes
and timeouts are always caught) but is reported as unverified rather than
pass/fail.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any

from tracer import call_capturing_output

_OUTPUT_RE = re.compile(r"Output:\s*(.+)")


@dataclass
class ExampleCase:
    index: int
    args: list[Any]
    expected_repr: str | None  # None if we couldn't confidently parse it


@dataclass
class ExampleResult:
    case: ExampleCase
    ok: bool  # ran without crashing/timing out
    actual_repr: str | None
    error: str | None
    passed: bool | None  # None if there's no expected output to compare against


def parse_all_examples(example_testcases: str, param_names: list[str], content_text: str) -> list[ExampleCase]:
    if not example_testcases or not param_names:
        return []
    lines = [ln for ln in example_testcases.strip().splitlines() if ln.strip() != ""]
    n = len(param_names)
    if n == 0 or len(lines) < n:
        return []

    expected_outputs = _OUTPUT_RE.findall(content_text)

    cases: list[ExampleCase] = []
    example_index = 0
    for start in range(0, len(lines) - n + 1, n):
        chunk = lines[start:start + n]
        try:
            args = [ast.literal_eval(ln.strip()) for ln in chunk]
        except (ValueError, SyntaxError):
            continue
        expected = expected_outputs[example_index].strip() if example_index < len(expected_outputs) else None
        cases.append(ExampleCase(index=example_index + 1, args=args, expected_repr=expected))
        example_index += 1
    return cases


def _normalize_for_compare(text: str) -> str:
    """Loose normalization: "[0, 1]" vs "[0,1]", 'a' vs "a", true vs True —
    none of these formatting differences should count as a mismatch."""
    t = re.sub(r"\s+", "", text.strip())
    t = t.replace("'", '"')
    return t.lower()


def run_regression(
    code: str, func_name: str, cases: list[ExampleCase], class_name: str | None = None, timeout_s: float = 1.0,
) -> list[ExampleResult]:
    results = []
    for case in cases:
        ok, output, error = call_capturing_output(code, func_name, case.args, class_name, timeout_s)
        passed = None
        if ok and case.expected_repr is not None:
            passed = _normalize_for_compare(output or "") == _normalize_for_compare(case.expected_repr)
        results.append(ExampleResult(case=case, ok=ok, actual_repr=output, error=error, passed=passed))
    return results

"""Best-effort counter-example fuzzer.

Generates random inputs matching the problem's declared LeetCode parameter
types and looks for inputs that CRASH or TIME OUT the user's own solution.

This is deliberately NOT full correctness fuzzing: we have no verified
reference oracle (the "optimal" solution shown elsewhere in the app is itself
LLM-generated and not guaranteed correct), so diffing against it would risk
reporting false "counter-examples" that are actually the reference's bugs.
Sticking to crashes/timeouts keeps every reported failure unambiguous.
"""

from __future__ import annotations

import random
import string as string_mod
import time
from dataclasses import dataclass
from typing import Any

from tracer import call_capturing_output, safe_call

SUPPORTED_TYPES = {"integer", "double", "boolean", "character", "string", "integer[]", "string[]", "integer[][]"}


def can_fuzz(param_types: list[str]) -> bool:
    return bool(param_types) and all(t in SUPPORTED_TYPES for t in param_types)


def _gen_value(type_str: str, n_bound: int, max_len: int, exact_size: bool) -> Any:
    def length(cap: int) -> int:
        capped = min(n_bound, cap)
        return capped if exact_size else random.randint(0, capped)

    if type_str == "integer":
        return random.randint(-1000, 1000)
    if type_str == "double":
        return round(random.uniform(-1000, 1000), 2)
    if type_str == "boolean":
        return random.choice([True, False])
    if type_str == "character":
        return random.choice(string_mod.ascii_lowercase)
    if type_str == "string":
        return "".join(random.choice(string_mod.ascii_lowercase) for _ in range(length(max_len)))
    if type_str == "integer[]":
        return [random.randint(-1000, 1000) for _ in range(length(max_len))]
    if type_str == "string[]":
        return ["".join(random.choice(string_mod.ascii_lowercase) for _ in range(random.randint(1, 8))) for _ in range(length(max_len))]
    if type_str == "integer[][]":
        rows = length(max_len)
        cols = min(max_len, 30)
        return [[random.randint(-100, 100) for _ in range(cols)] for _ in range(rows)]
    raise ValueError(f"Unsupported type for fuzzing: {type_str}")


def generate_case(param_types: list[str], n_bound: int, max_len: int = 30, exact_size: bool = False) -> list[Any]:
    """`max_len` bounds how large a generated array/string can get — fuzzing
    wants this small (fast, many trials); a performance race wants it at the
    problem's actual scale. `exact_size=True` always uses the full bound
    instead of a random 0..bound length, for a reproducible worst-case race."""
    return [_gen_value(t, max(n_bound, 1), max_len, exact_size) for t in param_types]


@dataclass
class FuzzFailure:
    args: list[Any]
    error: str


@dataclass
class FuzzResult:
    tested: int
    failure: FuzzFailure | None
    truncated: bool


def fuzz(
    code: str, func_name: str, param_types: list[str], n_bound: int,
    trials: int = 150, per_trial_timeout: float = 0.3, wall_clock_budget: float = 6.0,
    class_name: str | None = None,
) -> FuzzResult:
    start = time.perf_counter()
    for i in range(trials):
        if time.perf_counter() - start > wall_clock_budget:
            return FuzzResult(tested=i, failure=None, truncated=True)
        args = generate_case(param_types, n_bound)
        ok, error = safe_call(code, func_name, args, timeout_s=per_trial_timeout, class_name=class_name)
        if not ok:
            return FuzzResult(tested=i + 1, failure=FuzzFailure(args=args, error=error), truncated=False)
    return FuzzResult(tested=trials, failure=None, truncated=False)


# ---------------------------------------------------------------- boundary cases


def _boundary_values(type_str: str, n_bound: int, max_len: int) -> list[Any]:
    cap = max(min(max_len, n_bound), 1)
    if type_str == "integer":
        return [0, 1, -1, n_bound, -n_bound]
    if type_str == "double":
        return [0.0, 1.0, -1.0]
    if type_str == "boolean":
        return [True, False]
    if type_str == "character":
        return ["a", "z"]
    if type_str == "string":
        return ["", "a", "a" * cap]
    if type_str == "integer[]":
        return [[], [0], [1] * cap, list(range(cap))]
    if type_str == "string[]":
        return [[], [""], ["a"] * cap]
    if type_str == "integer[][]":
        small = min(cap, 10)
        return [[], [[]], [[0] * small for _ in range(small)]]
    return [None]


def _default_value(type_str: str) -> Any:
    return {
        "integer": 1, "double": 1.0, "boolean": True, "character": "a", "string": "a",
        "integer[]": [1, 2, 3], "string[]": ["a", "b"], "integer[][]": [[1, 2], [3, 4]],
    }.get(type_str)


def generate_boundary_cases(
    param_types: list[str], n_bound: int, max_len: int = 30,
) -> list[tuple[str, list[Any]]]:
    """Curated edge cases (empty, single, max-size, duplicates, zero, negative,
    ...) rather than random ones. Varies ONE parameter at a time against a
    normal default for the rest — a full cartesian product across params
    explodes combinatorially and most combinations wouldn't be informative
    anyway. Returns (label, args) pairs."""
    defaults = [_default_value(t) for t in param_types]
    cases: list[tuple[str, list[Any]]] = []
    for i, type_str in enumerate(param_types):
        for value in _boundary_values(type_str, n_bound, max_len):
            args = list(defaults)
            args[i] = value
            value_desc = f"length {len(value)}" if isinstance(value, (list, str)) and len(value) > 6 else repr(value)
            cases.append((f"param {i + 1} ({type_str}) = {value_desc}", args))
    return cases


# ---------------------------------------------------------------- determinism


def check_determinism(
    code: str, func_name: str, args: list[Any], class_name: str | None = None,
    trials: int = 5, timeout_s: float = 1.0,
) -> tuple[bool, list[str]]:
    """Run the same input multiple times — if the output differs between
    runs, the solution has hidden nondeterministic state (relying on
    set/dict iteration order, uninitialized instance state, etc.). Returns
    (deterministic, distinct_outputs_seen)."""
    outputs: list[str] = []
    for _ in range(trials):
        ok, output, error = call_capturing_output(code, func_name, args, class_name, timeout_s)
        if not ok:
            return False, [f"<run failed: {error}>"]
        outputs.append(output or "<None>")
    distinct = sorted(set(outputs))
    return len(distinct) <= 1, distinct


# ---------------------------------------------------------------- minimal failing input


def shrink_failing_input(
    code: str, func_name: str, param_types: list[str], args: list[Any],
    class_name: str | None = None, timeout_s: float = 0.3, max_checks: int = 300,
) -> list[Any]:
    """Greedy delta-debugging: repeatedly try to simplify each argument
    (shorten lists/strings one element at a time, shrink integers toward 0)
    while the failure still reproduces, stopping once nothing shrinks it
    further. Not optimally minimal (a full ddmin varies chunk sizes) but
    simple, correct, and good enough at the sizes fuzzing produces."""
    checks = 0

    def still_fails(candidate: list[Any]) -> bool:
        nonlocal checks
        checks += 1
        if checks > max_checks:
            return False
        ok, _error = safe_call(code, func_name, candidate, timeout_s=timeout_s, class_name=class_name)
        return not ok

    current = list(args)
    improved = True
    while improved and checks <= max_checks:
        improved = False
        for i, type_str in enumerate(param_types):
            shrunk = _shrink_one(current, i, still_fails)
            # Value comparison, not identity ("is not"): _shrink_one always
            # returns a freshly-built list/string, even an already-minimal
            # one, so `is not` was true forever and `improved` never went
            # False. For an already-empty list, _shrink_one's own while loop
            # never runs (nothing to remove), so `checks` stops incrementing
            # too — the max_checks safety net never fires either, since it
            # only checks a counter that has stalled. Net effect: an infinite
            # busy-loop that does no real work. Real bug, found via a hung
            # 120s+ test run.
            if shrunk != current[i]:
                current[i] = shrunk
                improved = True
    return current


def _shrink_one(args: list[Any], index: int, still_fails) -> Any:
    value = args[index]

    def trial(candidate_value: Any) -> bool:
        candidate = list(args)
        candidate[index] = candidate_value
        return still_fails(candidate)

    if isinstance(value, list):
        current = list(value)
        changed = True
        while changed and current:
            changed = False
            for i in range(len(current)):
                shorter = current[:i] + current[i + 1:]
                if trial(shorter):
                    current = shorter
                    changed = True
                    break
        return current
    if isinstance(value, str):
        current = value
        changed = True
        while changed and current:
            changed = False
            for i in range(len(current)):
                shorter = current[:i] + current[i + 1:]
                if trial(shorter):
                    current = shorter
                    changed = True
                    break
        return current
    if isinstance(value, bool):
        return value  # nothing simpler than a bool
    if isinstance(value, int):
        current = value
        if current == 0:
            return current
        if trial(0):
            return 0
        step = abs(current)
        while step > 1:
            step //= 2
            candidate = current - step if current > 0 else current + step
            if trial(candidate):
                current = candidate
            else:
                break
        return current
    return value

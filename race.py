"""Runs the user's submission and the LLM-refactored reference side by side
on the same example input, comparing real wall-clock time and real peak
memory (via tracemalloc). Plain function calls, no sys.settrace — tracing
overhead would otherwise skew the timing comparison."""

from __future__ import annotations

import copy
import time
import tracemalloc
from dataclasses import dataclass
from typing import Any

from tracer import find_entry_point, resolve_callable


@dataclass
class RunResult:
    ok: bool
    error: str | None
    elapsed_ms: float
    peak_kb: float
    output_repr: str | None


def _run_once(code: str, func_name: str, args: list[Any], class_name: str | None) -> RunResult:
    namespace: dict[str, Any] = {}
    try:
        exec(compile(code, "<solution>", "exec"), namespace)
    except Exception as exc:
        return RunResult(False, f"Could not load solution: {exc}", 0.0, 0.0, None)

    target = resolve_callable(namespace, func_name, class_name)
    if target is None or not callable(target):
        return RunResult(False, f"Could not find a callable '{func_name}'.", 0.0, 0.0, None)

    prepared = [copy.deepcopy(a) for a in args]
    tracemalloc.start()
    start = time.perf_counter()
    try:
        result = target(*prepared)
    except Exception as exc:
        tracemalloc.stop()
        return RunResult(False, f"{type(exc).__name__}: {exc}", 0.0, 0.0, None)
    elapsed_ms = (time.perf_counter() - start) * 1000
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    try:
        output_repr = repr(result)
    except Exception:
        output_repr = "<unrepresentable>"
    return RunResult(True, None, elapsed_ms, peak / 1024, output_repr)


def _best_of(code: str, args: list[Any], repeats: int, expected_name: str | None) -> RunResult:
    func_name, class_name = find_entry_point(code, expected_name)
    if not func_name:
        return RunResult(False, "Could not find a function definition.", 0.0, 0.0, None)
    results = [_run_once(code, func_name, args, class_name) for _ in range(repeats)]
    failing = next((r for r in results if not r.ok), None)
    if failing:
        return failing
    best = min(results, key=lambda r: r.elapsed_ms)
    # Timing benefits from taking the best (least noisy) run; peak memory is
    # more informative as the worst case actually observed across runs.
    best.peak_kb = max(r.peak_kb for r in results)
    return best


def race(
    user_code: str, ref_code: str, args: list[Any], repeats: int = 5, expected_name: str | None = None,
) -> tuple[RunResult, RunResult]:
    return _best_of(user_code, args, repeats, expected_name), _best_of(ref_code, args, repeats, expected_name)

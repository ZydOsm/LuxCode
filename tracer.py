"""Line-by-line execution tracer for a user's own submitted solution.

This runs the user's own code, on their own machine, against an
auto-detected example input from the LeetCode problem statement — it is not
a sandbox or a judge, it is exactly like running `python solution.py`
yourself with a trace hook attached (`sys.settrace`) plus `tracemalloc` for
real memory numbers. No new third-party dependencies.
"""

from __future__ import annotations

import ast
import copy
import sys
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import Any

MAX_STEPS = 4000
MAX_SECONDS = 4.0
MAX_COPY_ITEMS = 2000


class TraceError(RuntimeError):
    """Raised when the solution can't be loaded/run at all."""


class _StopTrace(Exception):
    """Internal: raised from the trace hook to abort a runaway trace."""


@dataclass
class Step:
    index: int
    line_no: int
    event: str  # "call" | "line" | "return"
    func_name: str
    depth: int
    locals_repr: dict[str, str]
    locals_value: dict[str, Any]  # only size-capped, deep-copied container/scalar values
    memory_bytes: int


@dataclass
class CallFrame:
    call_id: int
    parent_id: int | None
    func_name: str
    args_repr: str
    depth: int
    start_step: int
    end_step: int | None = None
    return_repr: str | None = None
    is_leaf: bool = False


@dataclass
class ExecutionTrace:
    steps: list[Step] = field(default_factory=list)
    calls: list[CallFrame] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None


def find_entry_point(code: str, expected_name: str | None = None) -> tuple[str | None, str | None]:
    """Locate the callable to invoke: a bare top-level function, or — LeetCode's
    actual submission format — a method on a `class Solution:`. Returns
    (function_name, class_name); class_name is None for a bare function.

    When `expected_name` (LeetCode's own metaData.name, e.g. "twoSum") is
    given and matches something defined in the code, that takes priority —
    solutions often define private helper methods/functions alongside the
    real entry point, and picking "the first one found" would grab a helper
    instead. Falls back to the first public function/method otherwise.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None, None

    top_level_funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]

    if expected_name:
        for node in top_level_funcs:
            if node.name == expected_name:
                return node.name, None
        for cls in classes:
            for item in cls.body:
                if isinstance(item, ast.FunctionDef) and item.name == expected_name:
                    return item.name, cls.name

    for node in top_level_funcs:
        if not node.name.startswith("_"):
            return node.name, None
    for cls in classes:
        for item in cls.body:
            if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                return item.name, cls.name

    return None, None


def resolve_callable(namespace: dict[str, Any], func_name: str, class_name: str | None):
    """Look up the entry point in an exec'd namespace — a bound method on a
    freshly-instantiated class if class_name is set, else a bare function."""
    if class_name:
        cls = namespace.get(class_name)
        if cls is None or not isinstance(cls, type):
            return None
        try:
            instance = cls()
        except Exception:
            return None
        return getattr(instance, func_name, None)
    return namespace.get(func_name)


def parse_example_args(example_testcases: str, param_names: list[str]) -> list[Any] | None:
    """Best-effort parse of LeetCode's raw example-testcase block into call args.

    `exampleTestcases` is newline-separated raw literal values, one per
    parameter of the first example. This is inherently best-effort — LeetCode
    has no public per-problem harness, so unusual input shapes may fail to
    parse; callers should treat a None return as "couldn't auto-detect".
    """
    if not example_testcases or not param_names:
        return None
    lines = [ln for ln in example_testcases.strip().splitlines() if ln.strip() != ""]
    if len(lines) < len(param_names):
        return None
    args = []
    for line in lines[: len(param_names)]:
        try:
            args.append(ast.literal_eval(line.strip()))
        except (ValueError, SyntaxError):
            return None
    return args


def _safe_copy(value: Any) -> Any:
    """Deep-copy small container/scalar values for structured rendering; else None."""
    if isinstance(value, (int, float, bool, str, type(None))):
        return value
    if isinstance(value, (list, tuple, set, dict)):
        try:
            if len(value) > MAX_COPY_ITEMS:
                return None
            return copy.deepcopy(value)
        except Exception:
            return None
    return None


def _current_memory() -> int:
    current, _peak = tracemalloc.get_traced_memory()
    return current


def trace_solution(code: str, func_name: str, args: list[Any], class_name: str | None = None) -> ExecutionTrace:
    """Execute `func_name(*args)` from `code`, recording a step-by-step trace.
    Pass `class_name` when the entry point is a method (LeetCode's actual
    submission format is `class Solution: def method(self, ...)`, not a bare
    function) — see find_entry_point()."""
    steps: list[Step] = []
    calls: list[CallFrame] = []
    call_stack: list[int] = []
    next_call_id = 0
    error: str | None = None
    truncated = False
    start_time = time.perf_counter()

    namespace: dict[str, Any] = {}
    try:
        exec(compile(code, "<solution>", "exec"), namespace)
    except Exception as exc:
        raise TraceError(f"Could not load solution: {exc}") from exc

    target = resolve_callable(namespace, func_name, class_name)
    if target is None or not callable(target):
        raise TraceError(f"Could not find a callable '{func_name}' in your code.")

    def snapshot(frame) -> tuple[dict[str, str], dict[str, Any]]:
        reprs: dict[str, str] = {}
        values: dict[str, Any] = {}
        for name, value in frame.f_locals.items():
            if name.startswith("__") or name == "self":
                continue
            try:
                reprs[name] = repr(value)
            except Exception:
                reprs[name] = "<unrepresentable>"
            copied = _safe_copy(value)
            if copied is not None:
                values[name] = copied
        return reprs, values

    def tracer(frame, event, arg):
        nonlocal truncated, next_call_id
        # Only trace frames from the user's own compiled submission — otherwise
        # calls into stdlib helpers (e.g. copy.deepcopy) pollute the trace.
        if frame.f_code.co_filename != "<solution>":
            return None
        if frame.f_code.co_name.startswith("<"):
            return tracer
        if time.perf_counter() - start_time > MAX_SECONDS or len(steps) >= MAX_STEPS:
            truncated = True
            raise _StopTrace()

        if event == "call":
            call_id = next_call_id
            next_call_id += 1
            parent = call_stack[-1] if call_stack else None
            call_stack.append(call_id)
            try:
                arg_names = frame.f_code.co_varnames[: frame.f_code.co_argcount]
                args_repr = ", ".join(f"{n}={frame.f_locals.get(n)!r}" for n in arg_names if n != "self")
            except Exception:
                args_repr = ""
            calls.append(CallFrame(
                call_id=call_id, parent_id=parent, func_name=frame.f_code.co_name,
                args_repr=args_repr, depth=len(call_stack) - 1, start_step=len(steps),
            ))
            reprs, values = snapshot(frame)
            steps.append(Step(len(steps), frame.f_lineno, "call", frame.f_code.co_name,
                               len(call_stack) - 1, reprs, values, _current_memory()))
            return tracer

        if event == "line":
            reprs, values = snapshot(frame)
            steps.append(Step(len(steps), frame.f_lineno, "line", frame.f_code.co_name,
                               max(len(call_stack) - 1, 0), reprs, values, _current_memory()))
            return tracer

        if event == "return":
            reprs, values = snapshot(frame)
            steps.append(Step(len(steps), frame.f_lineno, "return", frame.f_code.co_name,
                               max(len(call_stack) - 1, 0), reprs, values, _current_memory()))
            if call_stack:
                call_id = call_stack.pop()
                for c in calls:
                    if c.call_id == call_id:
                        c.end_step = len(steps) - 1
                        try:
                            c.return_repr = repr(arg)
                        except Exception:
                            c.return_repr = "<unrepresentable>"
                        break
            return tracer

        return tracer

    prepared_args = [copy.deepcopy(a) for a in args]

    tracemalloc.start()
    try:
        sys.settrace(tracer)
        try:
            target(*prepared_args)
        except _StopTrace:
            pass
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            sys.settrace(None)
    finally:
        tracemalloc.stop()

    child_ids = {c.parent_id for c in calls if c.parent_id is not None}
    for c in calls:
        c.is_leaf = c.call_id not in child_ids

    return ExecutionTrace(steps=steps, calls=calls, truncated=truncated, error=error)


def call_capturing_output(
    code: str, func_name: str, args: list[Any], class_name: str | None = None, timeout_s: float = 0.5,
) -> tuple[bool, str | None, str | None]:
    """Run func_name(*args) with a soft wall-clock timeout, no step recording —
    a leaner sibling of trace_solution for cases that just need to know "did
    it crash or hang" (and optionally what it returned), not the full trace.
    Returns (ok, output_repr, error). Pass `class_name` for a method entry
    point — see find_entry_point()."""
    namespace: dict[str, Any] = {}
    try:
        exec(compile(code, "<solution>", "exec"), namespace)
    except Exception as exc:
        return False, None, f"Could not load solution: {exc}"

    target = resolve_callable(namespace, func_name, class_name)
    if target is None or not callable(target):
        return False, None, f"Could not find a callable '{func_name}' in your code."

    start = time.perf_counter()

    def tracer(frame, event, arg):
        if frame.f_code.co_filename != "<solution>":
            return None
        if time.perf_counter() - start > timeout_s:
            raise _StopTrace()
        return tracer

    prepared_args = [copy.deepcopy(a) for a in args]
    sys.settrace(tracer)
    try:
        result = target(*prepared_args)
    except _StopTrace:
        return False, None, f"Timed out (> {timeout_s}s) — possible infinite loop"
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}"
    finally:
        sys.settrace(None)
    try:
        return True, repr(result), None
    except Exception:
        return True, "<unrepresentable>", None


def safe_call(
    code: str, func_name: str, args: list[Any], timeout_s: float = 0.5, class_name: str | None = None,
) -> tuple[bool, str | None]:
    """Like call_capturing_output but discards the return value — the common
    case (fuzzing, races) that only cares whether it crashed or hung."""
    ok, _output, error = call_capturing_output(code, func_name, args, class_name, timeout_s)
    return ok, error

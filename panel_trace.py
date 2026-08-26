"""Trace tab: a media-player-style execution scrubber plus three views that
all sync to the same step index — variables, a recursion tree, a DP-grid
view (when a 2D array is detected), and a memory sparkline. All backed by
tracer.py's sys.settrace-based tracer; no sandboxing, just running the
user's own code on their own machine like `python solution.py` would.
"""

from __future__ import annotations

import builtins
import queue
import threading
import tkinter as tk

import customtkinter as ctk

from analyzer import AnalyzerError, explain_exception
from code_editor import CodeEditor
from theme import (
    ACCENT, ACCENT_HOVER, ACCENT_PRESSED, BG, BLUE, BORDER, CARD_BG, CARD_BG_2, DANGER_HOVER,
    DP_TOUCHED_BG, FAINT, GREEN, GREEN_SOFT, HOVER_TINT, MUTED, RED, RED_SOFT, ROW_HOVER, TEXT,
    TEXT_DIM, TRACE_LINE_HIGHLIGHT, YELLOW, YELLOW_SOFT, Spinner, add_hover, add_press_feedback,
    animate, animate_number, flash_confirm, make_copy_button, stagger_in,
)
from tracer import (
    CallFrame, ExecutionTrace, TraceError, find_entry_point, parse_example_args, trace_solution,
)

_HIGHLIGHT_TAG = "trace_current_line"

# Restricted globals for evaluating user-facing expressions (watches,
# conditional breakpoints) against captured local variable snapshots — just
# enough read-only inspection builtins to write a normal expression (len,
# sum, sorted, ...), nothing that touches files, imports, or executes code.
_SAFE_BUILTINS = {
    name: getattr(builtins, name)
    for name in (
        "len", "sum", "min", "max", "abs", "sorted", "list", "dict", "set", "tuple",
        "str", "int", "float", "bool", "range", "enumerate", "zip", "all", "any", "round", "repr",
    )
}
_EVAL_GLOBALS = {"__builtins__": _SAFE_BUILTINS}


def _safe_eval(expr: str, locals_value: dict) -> tuple[bool, str]:
    """Returns (ok, display_text) — for display purposes (watch expressions)."""
    if not expr.strip():
        return True, ""
    try:
        result = eval(expr, _EVAL_GLOBALS, locals_value)
        return True, repr(result)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _safe_eval_truthy(expr: str, locals_value: dict) -> bool:
    """For conditional breakpoints — evaluates the actual value's truthiness,
    not a string comparison against its repr."""
    try:
        return bool(eval(expr, _EVAL_GLOBALS, locals_value))
    except Exception:
        return False


def _truncate(text: str, n: int = 40) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _mutation_summary(prev: object, curr: object) -> str | None:
    """One-line description of what changed inside a container variable
    between two consecutive steps — a generalization of the DP-grid diff to
    any list/dict/set. Returns None when there's nothing container-shaped to
    compare (unset, scalar, or a type mismatch)."""
    if prev is None or curr is None or type(prev) is not type(curr):
        return None
    try:
        if isinstance(curr, list):
            if len(prev) != len(curr):
                return f"length {len(prev)} → {len(curr)}"
            changed = [i for i in range(len(curr)) if prev[i] != curr[i]]
            if not changed:
                return None
            if len(changed) <= 3:
                return "changed index " + ", ".join(f"[{i}]={_truncate(repr(curr[i]), 20)}" for i in changed)
            return f"changed {len(changed)} indices"
        if isinstance(curr, dict):
            added = curr.keys() - prev.keys()
            removed = prev.keys() - curr.keys()
            changed_keys = {k for k in (curr.keys() & prev.keys()) if prev[k] != curr[k]}
            parts = []
            if added:
                parts.append(f"added {_truncate(', '.join(map(repr, sorted(added, key=repr))))}")
            if removed:
                parts.append(f"removed {_truncate(', '.join(map(repr, sorted(removed, key=repr))))}")
            if changed_keys:
                parts.append(f"updated {_truncate(', '.join(map(repr, sorted(changed_keys, key=repr))))}")
            return "; ".join(parts) if parts else None
        if isinstance(curr, set):
            added = curr - prev
            removed = prev - curr
            parts = []
            if added:
                parts.append(f"added {_truncate(', '.join(map(repr, sorted(added, key=repr))))}")
            if removed:
                parts.append(f"removed {_truncate(', '.join(map(repr, sorted(removed, key=repr))))}")
            return "; ".join(parts) if parts else None
    except Exception:
        return None
    return None


class TracePanel(ctk.CTkFrame):
    def __init__(self, parent, fonts, get_context, get_model=None) -> None:
        """`get_context()` -> (code: str, metadata: ProblemMetadata | None).
        `get_model()` -> currently selected model name (used only by "Explain
        Exception", the one feature here that makes an LLM call)."""
        super().__init__(parent, fg_color=BG)
        self.fonts = fonts
        self.get_context = get_context
        self.get_model = get_model
        self.trace: ExecutionTrace | None = None
        self.current_step = 0
        self.playing = False
        self._play_job: str | None = None
        # line_no -> condition expr ("" = unconditional). Persists across
        # re-runs so tweaking code and re-tracing keeps your breakpoints.
        self.breakpoints: dict[int, str] = {}
        self.watches: list[str] = []
        self._expanded_var: str | None = None
        self.explaining = False
        self._explanation_card: ctk.CTkFrame | None = None
        self._code_at_last_trace: str | None = None
        self._stale_shown = False
        # Background thread never touches Tk directly — it only pushes onto
        # this queue; the main thread polls it via .after(), same pattern as
        # the rest of the app. Calling .after()/widget methods from a worker
        # thread is not safe in Tkinter.
        self._result_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_toolbar()
        self._build_scrubber()
        self._build_body()
        self._show_placeholder()
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------ UI

    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="we", pady=(0, 12))

        self.run_button = ctk.CTkButton(
            bar, text="▶  Run Execution Trace", command=self._on_run, height=42, corner_radius=10,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, font=self.fonts.body_bold,
        )
        self.run_button.pack(side="left")
        add_press_feedback(self.run_button, ACCENT_PRESSED)

        self.spinner = Spinner(bar, size=16, color=ACCENT, bg=BG)
        self.status_label = ctk.CTkLabel(bar, text="", text_color=MUTED, font=self.fonts.small)
        self.status_label.pack(side="left", padx=(14, 0))

        # Shown when the editor's code has changed since this trace ran, so
        # stale results never masquerade as current ones.
        self.stale_label = ctk.CTkLabel(
            bar, text="⚠ Code changed — this trace is out of date. Re-run to refresh.",
            text_color=YELLOW, font=self.fonts.small,
        )
        self.retry_button = ctk.CTkButton(
            bar, text="↻ Retry", width=70, height=28, corner_radius=8, fg_color=CARD_BG_2,
            hover_color=HOVER_TINT, font=self.fonts.small_bold, command=self._on_run,
        )

    def _build_scrubber(self) -> None:
        self.scrubber_card = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
        self.scrubber_card.grid(row=1, column=0, sticky="we", pady=(0, 14))
        inner = ctk.CTkFrame(self.scrubber_card, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=(14, 4))
        inner.grid_columnconfigure(1, weight=1)

        self.play_pause_btn = ctk.CTkButton(
            inner, text="▶", width=36, height=36, corner_radius=18, fg_color=CARD_BG_2,
            hover_color=HOVER_TINT, font=self.fonts.body_bold, command=self._toggle_play,
        )
        self.play_pause_btn.grid(row=0, column=0, padx=(0, 12))

        self.slider = ctk.CTkSlider(
            inner, from_=0, to=1, number_of_steps=1, command=self._on_slider,
            fg_color=CARD_BG_2, progress_color=ACCENT, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
        )
        self.slider.grid(row=0, column=1, sticky="we")

        self.step_label = ctk.CTkLabel(inner, text="Step 0 / 0", text_color=TEXT_DIM, font=self.fonts.small, width=150)
        self.step_label.grid(row=0, column=2, padx=(12, 0))

        # Debugger-style step controls — the trace is fully pre-recorded, so
        # these navigate the recorded steps rather than re-executing anything.
        step_bar = ctk.CTkFrame(self.scrubber_card, fg_color="transparent")
        step_bar.pack(fill="x", padx=18, pady=(0, 14))
        self._step_buttons: list[ctk.CTkButton] = []

        def _mini(text: str, command, tooltip: str) -> ctk.CTkButton:
            btn = ctk.CTkButton(
                step_bar, text=text, width=34, height=28, corner_radius=8, fg_color=CARD_BG_2,
                hover_color=HOVER_TINT, font=self.fonts.small_bold, command=command, state="disabled",
            )
            btn.pack(side="left", padx=(0, 6))
            self._step_buttons.append(btn)
            return btn

        _mini("↢", self._step_back, "Step back one recorded event")
        _mini("↣", self._step_into, "Step into — advance one recorded event")
        _mini("⤵", self._step_over, "Step over — run past the next call without descending into it")
        _mini("⤴", self._step_out, "Step out — run until the current call returns")
        _mini("⏭", self._continue_to_breakpoint, "Continue — run to the next breakpoint")

        self.exception_bar = ctk.CTkFrame(step_bar, fg_color="transparent")
        # Packed on demand in _run_done() when the trace ends in an exception.
        self.jump_to_exception_btn = ctk.CTkButton(
            self.exception_bar, text="⚠ Jump to Exception", height=28, corner_radius=8,
            fg_color=RED_SOFT, hover_color=DANGER_HOVER, text_color=RED, font=self.fonts.small_bold,
            command=self._jump_to_exception,
        )
        self.jump_to_exception_btn.pack(side="left", padx=(0, 6))
        self.explain_exception_btn = ctk.CTkButton(
            self.exception_bar, text="✨ Explain Exception", height=28, corner_radius=8,
            fg_color=CARD_BG_2, hover_color=HOVER_TINT, text_color=TEXT, font=self.fonts.small_bold,
            command=self._on_explain_exception,
        )
        self.explain_exception_btn.pack(side="left")

    def _build_body(self) -> None:
        self.body = ctk.CTkScrollableFrame(self, fg_color=BG)
        self.body.grid(row=2, column=0, sticky="nswe")
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_columnconfigure(1, weight=1)

    def _show_placeholder(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        wrap = ctk.CTkFrame(self.body, fg_color="transparent")
        wrap.grid(row=0, column=0, columnspan=2, pady=100)
        ctk.CTkLabel(wrap, text="⏱", text_color=FAINT, font=ctk.CTkFont(size=30)).pack()
        ctk.CTkLabel(
            wrap,
            text="Runs your own solution, on your own machine, against the\n"
                 "problem's first example — then lets you scrub through it\n"
                 "line by line: variables, recursion tree, DP grid, memory.",
            text_color=MUTED, font=self.fonts.body, justify="center",
        ).pack(pady=(10, 0))
        self.slider.configure(state="disabled")
        self.play_pause_btn.configure(state="disabled")
        for btn in self._step_buttons:
            btn.configure(state="disabled")
        self.exception_bar.pack_forget()

    # -------------------------------------------------------------- running

    def _on_run(self) -> None:
        code, metadata = self.get_context()
        if not code.strip():
            self.status_label.configure(text="Paste a solution in the Editor tab first.", text_color=RED)
            return
        expected_name = metadata.function_name if metadata else None
        func_name, class_name = find_entry_point(code, expected_name)
        if not func_name:
            self.status_label.configure(text="Couldn't find a function definition in your code.", text_color=RED)
            return

        args = None
        if metadata is not None:
            args = parse_example_args(metadata.example_testcases, metadata.param_names)
        if args is None:
            self.status_label.configure(
                text="Couldn't auto-detect example input for this problem — trace unavailable.",
                text_color=RED,
            )
            return

        self.run_button.configure(state="disabled")
        self.spinner.pack(side="left", padx=(10, 0))
        self.spinner.start()
        self.status_label.configure(text="Tracing execution...", text_color=MUTED)
        threading.Thread(target=self._run_worker, args=(code, func_name, class_name, args), daemon=True).start()

    def _run_worker(self, code: str, func_name: str, class_name: str | None, args: list) -> None:
        try:
            trace = trace_solution(code, func_name, args, class_name)
        except TraceError as exc:
            self._result_queue.put(("failed", str(exc)))
            return
        self._result_queue.put(("done", (code, trace)))

    def _poll_queue(self) -> None:
        self._check_stale()
        try:
            kind, payload = self._result_queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_queue)
            return
        if kind == "failed":
            self._run_failed(payload)
        elif kind == "done":
            code, trace = payload
            self._run_done(code, trace)
        elif kind == "explain_done":
            self.explaining = False
            self.explain_exception_btn.configure(state="normal", text="✨ Explain Exception")
            self._render_explanation(payload, is_error=False)
        elif kind == "explain_failed":
            self.explaining = False
            self.explain_exception_btn.configure(state="normal", text="✨ Explain Exception")
            self._render_explanation(payload, is_error=True)
        self.after(100, self._poll_queue)

    def _run_failed(self, message: str) -> None:
        self.spinner.stop()
        self.spinner.pack_forget()
        self.run_button.configure(state="normal")
        self.status_label.configure(text=message, text_color=RED)
        self.retry_button.pack(side="left", padx=(10, 0))

    def _check_stale(self) -> None:
        if self._code_at_last_trace is None:
            return
        code, _metadata = self.get_context()
        is_stale = code != self._code_at_last_trace
        if is_stale != self._stale_shown:
            self._stale_shown = is_stale
            if is_stale:
                self.stale_label.pack(side="left", padx=(14, 0))
            else:
                self.stale_label.pack_forget()

    def _run_done(self, code: str, trace: ExecutionTrace) -> None:
        self.spinner.stop()
        self.spinner.pack_forget()
        self.run_button.configure(state="normal")
        self.retry_button.pack_forget()
        self._code_at_last_trace = code
        self._stale_shown = False
        self.stale_label.pack_forget()
        self.trace = trace
        self.current_step = 0

        if not trace.steps:
            self.status_label.configure(text=trace.error or "No steps recorded.", text_color=RED)
            return

        msg = f"{len(trace.steps)} steps captured."
        if trace.error:
            msg += f"  Solution raised: {trace.error}"
        if trace.truncated:
            msg += "  (trace truncated — execution ran too long)"
        self.status_label.configure(text=msg, text_color=YELLOW if trace.error or trace.truncated else GREEN)

        self.slider.configure(state="normal", from_=0, to=len(trace.steps) - 1, number_of_steps=max(len(trace.steps) - 1, 1))
        self.slider.set(0)
        self.play_pause_btn.configure(state="normal")
        for btn in self._step_buttons:
            btn.configure(state="normal")

        if trace.error:
            self.exception_bar.pack(side="left")
            self.explain_exception_btn.configure(state="normal", text="✨ Explain Exception")
        else:
            self.exception_bar.pack_forget()
        self._explanation_card = None

        self._code = code
        self._build_step_views()
        self._render_step()

    # -------------------------------------------------------------- scrub

    def _on_slider(self, value: float) -> None:
        self.current_step = int(round(value))
        self._render_step()

    def _toggle_play(self) -> None:
        if self.trace is None:
            return
        self.playing = not self.playing
        self.play_pause_btn.configure(text="⏸" if self.playing else "▶")
        if self.playing:
            self._advance()

    def _advance(self) -> None:
        if not self.playing or self.trace is None:
            return
        if self.current_step >= len(self.trace.steps) - 1:
            self.playing = False
            self.play_pause_btn.configure(text="▶")
            return
        self.current_step += 1
        self.slider.set(self.current_step)
        self._render_step()
        self._play_job = self.after(450, self._advance)

    def _goto_step(self, index: int) -> None:
        if not self.trace:
            return
        index = max(0, min(index, len(self.trace.steps) - 1))
        self.current_step = index
        self.slider.set(index)
        self._render_step()

    def _step_back(self) -> None:
        self._goto_step(self.current_step - 1)

    def _step_into(self) -> None:
        self._goto_step(self.current_step + 1)

    def _step_over(self) -> None:
        if not self.trace:
            return
        depth = self.trace.steps[self.current_step].depth
        for j in range(self.current_step + 1, len(self.trace.steps)):
            if self.trace.steps[j].depth <= depth:
                self._goto_step(j)
                return
        self._goto_step(len(self.trace.steps) - 1)

    def _step_out(self) -> None:
        if not self.trace:
            return
        depth = self.trace.steps[self.current_step].depth
        for j in range(self.current_step + 1, len(self.trace.steps)):
            if self.trace.steps[j].depth < depth:
                self._goto_step(j)
                return
        self._goto_step(len(self.trace.steps) - 1)

    def _continue_to_breakpoint(self) -> None:
        if not self.trace or not self.breakpoints:
            self.status_label.configure(text="No breakpoints set — click a line number to add one.", text_color=MUTED)
            return
        for j in range(self.current_step + 1, len(self.trace.steps)):
            step = self.trace.steps[j]
            if step.line_no not in self.breakpoints:
                continue
            condition = self.breakpoints[step.line_no]
            if not condition or _safe_eval_truthy(condition, step.locals_value):
                self._goto_step(j)
                return
        self.status_label.configure(text="No breakpoint hit for the rest of the trace.", text_color=YELLOW)
        self._goto_step(len(self.trace.steps) - 1)

    def _jump_to_exception(self) -> None:
        if not self.trace:
            return
        self._goto_step(len(self.trace.steps) - 1)

    # ------------------------------------------------------- breakpoints

    def _on_gutter_click(self, line_no: int) -> None:
        if line_no in self.breakpoints:
            del self.breakpoints[line_no]
        else:
            self.breakpoints[line_no] = ""
        self.code_view.set_breakpoint_lines(set(self.breakpoints.keys()))
        self._render_breakpoints_card()

    def _set_breakpoint_condition(self, line_no: int, expr: str) -> None:
        self.breakpoints[line_no] = expr

    def _remove_breakpoint(self, line_no: int) -> None:
        self.breakpoints.pop(line_no, None)
        self.code_view.set_breakpoint_lines(set(self.breakpoints.keys()))
        self._render_breakpoints_card()

    def _render_breakpoints_card(self) -> None:
        if not hasattr(self, "breakpoints_card"):
            return  # no trace built yet — nothing to render into
        if not self.breakpoints:
            self.breakpoints_card.grid_remove()
            return
        self.breakpoints_card.grid(row=self.breakpoints_row, column=0, columnspan=2, sticky="we", pady=(0, 14))
        for w in self.breakpoints_body.winfo_children():
            w.destroy()
        for line_no in sorted(self.breakpoints):
            row = ctk.CTkFrame(self.breakpoints_body, fg_color=CARD_BG_2, corner_radius=8)
            row.pack(fill="x", pady=3)
            add_hover(row, CARD_BG_2, ROW_HOVER)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=8)
            line_label = ctk.CTkLabel(
                inner, text=f"Line {line_no}", text_color=TEXT, font=self.fonts.small_bold, width=70, anchor="w",
            )
            line_label.pack(side="left")
            entry = ctk.CTkEntry(
                inner, placeholder_text="condition (optional) — e.g. i > 3", font=self.fonts.code_small,
                fg_color=CARD_BG, border_color=BORDER,
            )
            entry.insert(0, self.breakpoints[line_no])
            entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
            entry.bind("<KeyRelease>", lambda e, ln=line_no, ent=entry: self._set_breakpoint_condition(ln, ent.get()))
            entry.bind("<FocusOut>", lambda e, lbl=line_label, ln=line_no: flash_confirm(lbl, f"Line {ln} ✓"))
            ctk.CTkButton(
                inner, text="✕", width=28, height=28, corner_radius=8, fg_color=CARD_BG,
                hover_color=DANGER_HOVER, text_color=RED, font=self.fonts.small_bold,
                command=lambda ln=line_no: self._remove_breakpoint(ln),
            ).pack(side="left")

    # ------------------------------------------------------- watch expressions

    def _add_watch(self) -> None:
        expr = self.watch_entry.get().strip()
        if not expr or expr in self.watches:
            return
        self.watches.append(expr)
        self.watch_entry.delete(0, "end")
        self._render_watches()

    def _remove_watch(self, expr: str) -> None:
        if expr in self.watches:
            self.watches.remove(expr)
        self._render_watches()

    def _render_watches(self) -> None:
        if not hasattr(self, "watch_body"):
            return
        for w in self.watch_body.winfo_children():
            w.destroy()
        if not self.watches:
            ctk.CTkLabel(self.watch_body, text="(no watches yet)", text_color=FAINT, font=self.fonts.small).pack(anchor="w")
            return
        locals_value = self.trace.steps[self.current_step].locals_value if self.trace else {}
        for expr in self.watches:
            ok, display = _safe_eval(expr, locals_value)
            row = ctk.CTkFrame(self.watch_body, fg_color="transparent", corner_radius=6)
            row.pack(fill="x", pady=2)
            add_hover(row, "transparent", CARD_BG_2)
            ctk.CTkLabel(
                row, text=expr, text_color=TEXT_DIM, font=self.fonts.code_small, anchor="w",
            ).pack(side="left")
            ctk.CTkLabel(
                row, text=f" = {display}", text_color=TEXT if ok else RED, font=self.fonts.code_small, anchor="w",
            ).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                row, text="✕", width=22, height=22, corner_radius=6, fg_color="transparent",
                hover_color=CARD_BG_2, text_color=FAINT, font=self.fonts.small,
                command=lambda ex=expr: self._remove_watch(ex),
            ).pack(side="right")

    # ------------------------------------------------------- call stack

    def _render_call_stack(self, step) -> None:
        if not hasattr(self, "stack_body") or not self.trace:
            return
        for w in self.stack_body.winfo_children():
            w.destroy()
        active = [
            c for c in self.trace.calls
            if c.start_step <= self.current_step <= (c.end_step if c.end_step is not None else len(self.trace.steps))
        ]
        active.sort(key=lambda c: c.depth, reverse=True)  # innermost frame first, like a real debugger
        if not active:
            ctk.CTkLabel(self.stack_body, text="(no active call)", text_color=FAINT, font=self.fonts.small).pack(anchor="w")
            return
        max_depth = active[0].depth
        for c in active:
            row = ctk.CTkFrame(self.stack_body, fg_color=CARD_BG_2, corner_radius=8)
            row.pack(fill="x", pady=2)
            add_hover(row, CARD_BG_2, ROW_HOVER)
            is_innermost = c.depth == max_depth
            label = f"{c.func_name}({c.args_repr})" if c.depth > 0 else f"{c.func_name}({c.args_repr})  ← entry point"
            inner = ctk.CTkFrame(row, fg_color="transparent")
            # Indent by call depth so the stack's shape mirrors the recursion
            # tree instead of reading as a flat list.
            inner.pack(anchor="w", fill="x", padx=(10 + (max_depth - c.depth) * 16, 10), pady=5)
            ctk.CTkLabel(
                inner, text=label, text_color=ACCENT if is_innermost else TEXT_DIM,
                font=self.fonts.code_small, anchor="w",
            ).pack(anchor="w", fill="x")

    # ------------------------------------------------------- explain exception

    def _on_explain_exception(self) -> None:
        if self.explaining or not self.trace or not self.trace.error or self.get_model is None:
            return
        code, _metadata = self.get_context()
        last_step = self.trace.steps[-1]
        self.explaining = True
        self.explain_exception_btn.configure(state="disabled", text="Explaining...")
        model = self.get_model()
        threading.Thread(
            target=self._explain_worker, args=(code, self.trace.error, last_step.locals_repr, model), daemon=True,
        ).start()

    def _explain_worker(self, code: str, error: str, locals_repr: dict, model: str) -> None:
        try:
            explanation = explain_exception(code, error, locals_repr, model)
        except AnalyzerError as exc:
            self._result_queue.put(("explain_failed", str(exc)))
            return
        self._result_queue.put(("explain_done", explanation))

    def _render_explanation(self, text: str, is_error: bool) -> None:
        if self._explanation_card is not None:
            self._explanation_card.destroy()
        card = ctk.CTkFrame(self.scrubber_card, fg_color=CARD_BG_2, corner_radius=8)
        card.pack(fill="x", padx=18, pady=(0, 14))
        label = ctk.CTkLabel(
            card, text=text, text_color=RED if is_error else TEXT, font=self.fonts.small,
            justify="left", anchor="w", wraplength=900,
        )
        label.pack(anchor="w", fill="x", padx=14, pady=10)
        self._explanation_card = card

    # -------------------------------------------------------------- views

    def _build_step_views(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()

        # Code preview with current-line highlight
        code_card = ctk.CTkFrame(self.body, fg_color="transparent")
        code_card.grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 14))
        code_title_row = ctk.CTkFrame(code_card, fg_color="transparent")
        code_title_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(code_title_row, text="Execution Position", font=self.fonts.card_title, text_color=TEXT).pack(
            side="left"
        )
        make_copy_button(code_title_row, lambda: self._code, self.fonts).pack(side="left", padx=(10, 0))
        self.code_view = CodeEditor(code_card, code_font=self.fonts.code_small, ui_font=self.fonts.small, read_only=True, height=220)
        self.code_view.pack(fill="both", expand=True)
        self.code_view.set_text(self._code)
        self.code_view.on_gutter_click(self._on_gutter_click)
        self.code_view.set_breakpoint_lines(set(self.breakpoints.keys()))
        breakpoint_hint = ctk.CTkLabel(
            code_card, text="Click a line number to set a breakpoint.", text_color=FAINT, font=self.fonts.small,
        )
        breakpoint_hint.pack(anchor="w", pady=(4, 0))

        row = 1

        # Variables
        self.vars_card = ctk.CTkFrame(self.body, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
        self.vars_card.grid(row=row, column=0, sticky="nwe", padx=(0, 7), pady=(0, 14))
        ctk.CTkLabel(self.vars_card, text="Variables", font=self.fonts.card_title, text_color=TEXT).pack(
            anchor="w", padx=18, pady=(16, 4)
        )
        ctk.CTkLabel(
            self.vars_card, text="Click a name for its value history.", text_color=FAINT, font=self.fonts.small,
        ).pack(anchor="w", padx=18, pady=(0, 8))
        self.vars_body = ctk.CTkFrame(self.vars_card, fg_color="transparent")
        self.vars_body.pack(fill="x", padx=18, pady=(0, 16))

        # Memory gauge
        self.mem_card = ctk.CTkFrame(self.body, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
        self.mem_card.grid(row=row, column=1, sticky="nwe", padx=(7, 0), pady=(0, 14))
        ctk.CTkLabel(self.mem_card, text="Memory Allocated", font=self.fonts.card_title, text_color=TEXT).pack(
            anchor="w", padx=18, pady=(16, 10)
        )
        self.mem_canvas = tk.Canvas(self.mem_card, height=110, bg=CARD_BG, highlightthickness=0)
        self.mem_canvas.pack(fill="x", padx=18, pady=(0, 8))
        self.mem_label = ctk.CTkLabel(self.mem_card, text="", text_color=MUTED, font=self.fonts.small)
        self.mem_label.pack(anchor="w", padx=18, pady=(0, 16))
        row += 1

        # Call stack
        self.stack_card = ctk.CTkFrame(self.body, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
        self.stack_card.grid(row=row, column=0, sticky="nwe", padx=(0, 7), pady=(0, 14))
        ctk.CTkLabel(self.stack_card, text="Call Stack", font=self.fonts.card_title, text_color=TEXT).pack(
            anchor="w", padx=18, pady=(16, 10)
        )
        self.stack_body = ctk.CTkFrame(self.stack_card, fg_color="transparent")
        self.stack_body.pack(fill="x", padx=18, pady=(0, 16))

        # Watch expressions
        self.watch_card = ctk.CTkFrame(self.body, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
        self.watch_card.grid(row=row, column=1, sticky="nwe", padx=(7, 0), pady=(0, 14))
        ctk.CTkLabel(self.watch_card, text="Watch Expressions", font=self.fonts.card_title, text_color=TEXT).pack(
            anchor="w", padx=18, pady=(16, 10)
        )
        add_row = ctk.CTkFrame(self.watch_card, fg_color="transparent")
        add_row.pack(fill="x", padx=18)
        self.watch_entry = ctk.CTkEntry(
            add_row, placeholder_text="e.g. len(seen), nums[i]", font=self.fonts.code_small,
            fg_color=CARD_BG_2, border_color=BORDER,
        )
        self.watch_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.watch_entry.bind("<Return>", lambda e: self._add_watch())
        ctk.CTkButton(
            add_row, text="Add", width=50, height=28, corner_radius=8, fg_color=CARD_BG_2,
            hover_color=HOVER_TINT, font=self.fonts.small_bold, command=self._add_watch,
        ).pack(side="left")
        self.watch_body = ctk.CTkFrame(self.watch_card, fg_color="transparent")
        self.watch_body.pack(fill="x", padx=18, pady=(10, 16))
        row += 1

        # Breakpoints — always built, shown only once at least one exists
        self.breakpoints_row = row
        self.breakpoints_card = ctk.CTkFrame(self.body, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
        ctk.CTkLabel(self.breakpoints_card, text="Breakpoints", font=self.fonts.card_title, text_color=TEXT).pack(
            anchor="w", padx=18, pady=(16, 10)
        )
        self.breakpoints_body = ctk.CTkFrame(self.breakpoints_card, fg_color="transparent")
        self.breakpoints_body.pack(fill="x", padx=18, pady=(0, 16))
        row += 1
        self._render_breakpoints_card()

        # DP grid (conditional — built lazily once we know a 2D var exists)
        self.dp_card = None
        self.dp_canvas = None
        self.dp_var_name = self._detect_grid_variable()
        self._dp_initial_grid = None
        if self.dp_var_name:
            for s in self.trace.steps:
                v = s.locals_value.get(self.dp_var_name)
                if v:
                    self._dp_initial_grid = v
                    break
        if self.dp_var_name:
            self.dp_card = ctk.CTkFrame(self.body, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
            self.dp_card.grid(row=row, column=0, columnspan=2, sticky="we", pady=(0, 14))
            ctk.CTkLabel(
                self.dp_card, text=f"DP Grid — {self.dp_var_name}", font=self.fonts.card_title, text_color=TEXT,
            ).pack(anchor="w", padx=18, pady=(16, 10))
            self.dp_canvas = tk.Canvas(self.dp_card, height=260, bg=CARD_BG, highlightthickness=0)
            self.dp_canvas.pack(fill="x", padx=18, pady=(0, 16))
            row += 1

        # Recursion tree (conditional)
        self.tree_card = None
        self.tree_canvas = None
        if self.trace and len(self.trace.calls) > 1:
            self.tree_card = ctk.CTkFrame(self.body, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
            self.tree_card.grid(row=row, column=0, columnspan=2, sticky="we", pady=(0, 14))
            ctk.CTkLabel(self.tree_card, text="Recursion Tree", font=self.fonts.card_title, text_color=TEXT).pack(
                anchor="w", padx=18, pady=(16, 10)
            )
            depth = max(c.depth for c in self.trace.calls) + 1
            canvas_height = max(120, depth * 70 + 40)
            self.tree_canvas = tk.Canvas(self.tree_card, height=canvas_height, bg=CARD_BG, highlightthickness=0)
            self.tree_canvas.pack(fill="both", expand=True, padx=18, pady=(0, 16))
            self._draw_recursion_tree()
            row += 1

        stagger_in([
            c for c in (
                self.vars_card, self.mem_card, self.stack_card, self.watch_card,
                self.dp_card, self.tree_card,
            ) if c is not None
        ])

    def _detect_grid_variable(self) -> str | None:
        if not self.trace:
            return None
        for step in reversed(self.trace.steps):
            for name, value in step.locals_value.items():
                if isinstance(value, list) and value and all(isinstance(row, list) for row in value):
                    return name
        return None

    # -------------------------------------------------------------- render

    def _render_step(self) -> None:
        if not self.trace:
            return
        step = self.trace.steps[self.current_step]
        self.step_label.configure(text=f"Step {self.current_step + 1} / {len(self.trace.steps)}  ·  line {step.line_no}")
        self.code_view.highlight_line(step.line_no, _HIGHLIGHT_TAG, TRACE_LINE_HIGHLIGHT)

        self._render_variables(step)
        self._render_memory()
        self._render_call_stack(step)
        self._render_watches()
        if self.dp_var_name:
            self._render_dp_grid(step)
        if self.tree_canvas:
            self._draw_recursion_tree()

    def _render_variables(self, step) -> None:
        for w in self.vars_body.winfo_children():
            w.destroy()
        prev_repr = self.trace.steps[self.current_step - 1].locals_repr if self.current_step > 0 else {}
        prev_value = self.trace.steps[self.current_step - 1].locals_value if self.current_step > 0 else {}
        if not step.locals_repr:
            ctk.CTkLabel(self.vars_body, text="(no local variables yet)", text_color=FAINT, font=self.fonts.small).pack(anchor="w")
            return
        for name, value in step.locals_repr.items():
            changed = prev_repr.get(name) != value
            row = ctk.CTkFrame(self.vars_body, fg_color="transparent", corner_radius=6, cursor="hand2")
            row.pack(fill="x", pady=1)
            add_hover(row, "transparent", CARD_BG_2)
            row.bind("<Button-1>", lambda e, n=name: self._toggle_var_history(n))
            top = ctk.CTkFrame(row, fg_color="transparent", cursor="hand2")
            top.pack(fill="x")
            top.bind("<Button-1>", lambda e, n=name: self._toggle_var_history(n))
            name_label = ctk.CTkLabel(
                top, text=name, text_color=ACCENT if self._expanded_var == name else TEXT_DIM,
                font=self.fonts.small_bold, width=90, anchor="w", cursor="hand2",
            )
            name_label.pack(side="left")
            name_label.bind("<Button-1>", lambda e, n=name: self._toggle_var_history(n))
            display = value if len(value) <= 60 else value[:57] + "..."
            value_label = ctk.CTkLabel(
                top, text=display, text_color=ACCENT if changed else TEXT, font=self.fonts.code_small,
                anchor="w", cursor="hand2",
            )
            value_label.pack(side="left", fill="x", expand=True)
            value_label.bind("<Button-1>", lambda e, n=name: self._toggle_var_history(n))

            mutation = _mutation_summary(prev_value.get(name), step.locals_value.get(name))
            if mutation:
                ctk.CTkLabel(
                    row, text=mutation, text_color=YELLOW, font=self.fonts.small, anchor="w",
                ).pack(anchor="w", padx=(90, 0), pady=(2, 0))

            if self._expanded_var == name:
                self._render_var_history(row, name)

    def _toggle_var_history(self, name: str) -> None:
        self._expanded_var = None if self._expanded_var == name else name
        self._render_variables(self.trace.steps[self.current_step])

    def _render_var_history(self, parent, name: str) -> None:
        history = []
        last_repr = None
        for s in self.trace.steps:
            if name not in s.locals_repr:
                continue
            r = s.locals_repr[name]
            if r != last_repr:
                history.append((s.index, s.line_no, r))
                last_repr = r
        panel = ctk.CTkFrame(parent, fg_color=CARD_BG_2, corner_radius=8)
        panel.pack(fill="x", padx=(90, 0), pady=(6, 0))
        shown = history[-12:]
        if len(history) > 12:
            ctk.CTkLabel(
                panel, text=f"({len(history) - 12} earlier change{'s' if len(history) - 12 != 1 else ''} not shown)",
                text_color=FAINT, font=self.fonts.small,
            ).pack(anchor="w", padx=10, pady=(8, 0))
        for step_index, line_no, r in shown:
            display = r if len(r) <= 50 else r[:47] + "..."
            is_current = step_index == self.current_step
            line = ctk.CTkLabel(
                panel, text=f"step {step_index + 1} (line {line_no}):  {display}",
                text_color=ACCENT if is_current else MUTED, font=self.fonts.code_small, anchor="w",
            )
            line.pack(anchor="w", padx=10, pady=2, fill="x")

    def _render_memory(self) -> None:
        canvas = self.mem_canvas
        canvas.delete("all")
        canvas.update_idletasks()  # winfo_width() is stale/1px until a layout pass has run
        w = canvas.winfo_width()
        if w <= 1:
            self.after(30, self._render_memory)
            return
        h = int(canvas.cget("height"))
        mem_values = [s.memory_bytes for s in self.trace.steps]
        lo, hi = min(mem_values), max(mem_values)
        span = max(hi - lo, 1)
        pad = 6

        # Faint horizontal gridlines + KB markers so the line isn't floating
        # in a void — reads as a real chart, not a decorative squiggle.
        for frac in (0.0, 0.5, 1.0):
            gy = pad + (h - 2 * pad) * frac
            canvas.create_line(pad, gy, w - pad, gy, fill=CARD_BG_2, width=1)
            kb_at_line = (hi - (hi - lo) * frac) / 1024
            canvas.create_text(
                w - pad, gy - 7, anchor="ne", text=f"{kb_at_line:.0f} KB", fill=FAINT,
                font=(self.fonts.small.cget("family"), 9),
            )

        points = []
        n = len(mem_values)
        for i, v in enumerate(mem_values):
            x = pad + (w - 2 * pad) * (i / max(n - 1, 1))
            y = h - pad - (h - 2 * pad) * ((v - lo) / span)
            points.append((x, y))
        if len(points) > 1:
            flat = [c for p in points for c in p]
            canvas.create_line(*flat, fill=ACCENT, width=2, smooth=True)
        cx, cy = points[self.current_step]
        canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=ACCENT, outline="")

        self._mem_points = points
        self._mem_values = mem_values
        canvas.bind("<Motion>", self._on_mem_hover)
        canvas.bind("<Leave>", lambda e: self._hide_mem_tooltip())

        current_kb = self.trace.steps[self.current_step].memory_bytes / 1024
        peak_kb = hi / 1024
        prev_kb = getattr(self, "_last_mem_kb", current_kb)
        self._last_mem_kb = current_kb
        if abs(prev_kb - current_kb) > 0.05:
            animate_number(self.mem_label, prev_kb, current_kb, duration_ms=250,
                            fmt=lambda v: f"{v:.1f} KB now   ·   peak {peak_kb:.1f} KB")
        else:
            self.mem_label.configure(text=f"{current_kb:.1f} KB now   ·   peak {peak_kb:.1f} KB")

    def _on_mem_hover(self, event) -> None:
        if not getattr(self, "_mem_points", None):
            return
        nearest = min(range(len(self._mem_points)), key=lambda i: abs(self._mem_points[i][0] - event.x))
        canvas = self.mem_canvas
        canvas.delete("mem_tooltip")
        x, y = self._mem_points[nearest]
        kb = self._mem_values[nearest] / 1024
        canvas.create_line(x, 0, x, canvas.winfo_height(), fill=CARD_BG_2, width=1, tags="mem_tooltip")
        label_y = max(12, y - 14)
        canvas.create_text(
            x, label_y, text=f"step {nearest + 1}: {kb:.1f} KB", fill=TEXT,
            font=(self.fonts.small.cget("family"), 10, "bold"), tags="mem_tooltip",
            anchor="s" if label_y > 12 else "n",
        )

    def _hide_mem_tooltip(self) -> None:
        if self.mem_canvas.winfo_exists():
            self.mem_canvas.delete("mem_tooltip")

    def _render_dp_grid(self, step) -> None:
        grid = step.locals_value.get(self.dp_var_name)
        prev_grid = None
        if self.current_step > 0:
            prev_grid = self.trace.steps[self.current_step - 1].locals_value.get(self.dp_var_name)

        canvas = self.dp_canvas
        canvas.delete("all")
        if not grid:
            return
        rows = len(grid)
        cols = max((len(r) for r in grid if isinstance(r, list)), default=0)
        if rows == 0 or cols == 0 or rows > 20 or cols > 20:
            canvas.create_text(10, 10, anchor="nw", text="(grid too large to render)", fill=MUTED)
            return

        canvas.update_idletasks()  # winfo_width() is stale/1px until a layout pass has run
        w = canvas.winfo_width()
        if w <= 1:
            self.after(30, lambda: self._render_dp_grid(step))
            return
        h = int(canvas.cget("height"))
        cell_w = min((w - 20) / cols, 60)
        cell_h = min((h - 20) / rows, 60)
        ox, oy = 10, 10
        for r in range(rows):
            row_vals = grid[r] if r < len(grid) else []
            for c in range(cols):
                val = row_vals[c] if c < len(row_vals) else ""
                x0, y0 = ox + c * cell_w, oy + r * cell_h
                x1, y1 = x0 + cell_w - 2, y0 + cell_h - 2
                changed = (
                    prev_grid is not None and r < len(prev_grid) and c < len(prev_grid[r])
                    and r < len(grid) and c < len(grid[r]) and prev_grid[r][c] != grid[r][c]
                )
                # A cell that differs from its very first recorded value has
                # been computed at some point, even if it isn't changing
                # *right now* — fading it distinctly from never-touched cells
                # makes the active computation frontier pop.
                touched = (
                    not changed and self._dp_initial_grid is not None
                    and r < len(self._dp_initial_grid) and c < len(self._dp_initial_grid[r])
                    and r < len(grid) and c < len(grid[r])
                    and self._dp_initial_grid[r][c] != grid[r][c]
                )
                if changed:
                    fill, text_color = ACCENT, "#ffffff"
                elif touched:
                    fill, text_color = DP_TOUCHED_BG, TEXT_DIM
                else:
                    fill, text_color = CARD_BG_2, FAINT
                canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline=BORDER)
                canvas.create_text(
                    (x0 + x1) / 2, (y0 + y1) / 2, text=str(val), fill=text_color,
                    font=(self.fonts.code_small.cget("family"), 11),
                )

    def _draw_recursion_tree(self) -> None:
        canvas = self.tree_canvas
        canvas.delete("all")
        calls = self.trace.calls
        by_id = {c.call_id: c for c in calls}
        children: dict[int, list[int]] = {c.call_id: [] for c in calls}
        roots = []
        for c in calls:
            if c.parent_id is not None:
                children[c.parent_id].append(c.call_id)
            else:
                roots.append(c.call_id)

        x_pos: dict[int, float] = {}
        next_x = [0]

        def assign(call_id: int) -> None:
            kids = children[call_id]
            if not kids:
                x_pos[call_id] = next_x[0]
                next_x[0] += 1
            else:
                for k in kids:
                    assign(k)
                x_pos[call_id] = sum(x_pos[k] for k in kids) / len(kids)

        for r in roots:
            assign(r)

        canvas.update_idletasks()  # winfo_width() is stale/1px until a layout pass has run
        w = canvas.winfo_width()
        if w <= 1:
            self.after(30, self._draw_recursion_tree)
            return
        col_width = max(70, min(120, (w - 40) / max(next_x[0], 1)))
        row_height = 64
        active_ids = {
            c.call_id for c in calls
            if c.start_step <= self.current_step <= (c.end_step if c.end_step is not None else len(self.trace.steps))
        }

        def node_center(call_id: int) -> tuple[float, float]:
            c = by_id[call_id]
            return (20 + x_pos[call_id] * col_width + col_width / 2, 20 + c.depth * row_height + 18)

        for c in calls:
            if c.parent_id is not None:
                x0, y0 = node_center(c.parent_id)
                x1, y1 = node_center(c.call_id)
                is_active_edge = c.call_id in active_ids and c.parent_id in active_ids
                edge_color = ACCENT if is_active_edge else BORDER
                # A gentle S-curve (bezier-via-smooth-line) instead of a
                # straight rung reads less like a flowchart and more like an
                # actual call tree.
                mid_y = (y0 + 16 + y1 - 16) / 2
                canvas.create_line(
                    x0, y0 + 16, x0, mid_y, x1, mid_y, x1, y1 - 16,
                    fill=edge_color, width=2, smooth=True,
                )

        for c in calls:
            cx, cy = node_center(c.call_id)
            active = c.call_id in active_ids
            if c.is_leaf:
                fill, outline = (GREEN_SOFT, GREEN)
            else:
                fill, outline = (CARD_BG_2, BORDER)
            if active:
                fill, outline = (ACCENT, ACCENT)
            canvas.create_oval(cx - 26, cy - 16, cx + 26, cy + 16, fill=fill, outline=outline, width=2)
            label = c.args_repr if len(c.args_repr) <= 14 else c.args_repr[:12] + "…"
            canvas.create_text(
                cx, cy, text=label or c.func_name, fill="#ffffff" if active else TEXT_DIM,
                font=(self.fonts.code_small.cget("family"), 10),
            )

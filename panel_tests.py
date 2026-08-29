"""Tests tab: runs every official example (not just the one the Trace tab
uses), a curated set of boundary cases, and a determinism check — all in one
pass. Any crash can be shrunk to its minimal reproducing input with one click.
"""

from __future__ import annotations

import queue
import threading

import customtkinter as ctk

from fuzzer import can_fuzz, check_determinism, generate_boundary_cases, shrink_failing_input
from regression import ExampleResult, parse_all_examples, run_regression
from theme import (
    ACCENT, ACCENT_HOVER, ACCENT_PRESSED, BG, BORDER, CARD_BG, CARD_BG_2, FAINT, GREEN, GREEN_SOFT,
    HOVER_TINT, MUTED, RED, RED_SOFT, ROW_HOVER, SCROLLBAR_THUMB, SCROLLBAR_THUMB_HOVER, TEXT,
    TEXT_DIM, YELLOW, YELLOW_SOFT, Spinner, Toast, add_hover, add_press_feedback,
    bind_responsive_wraplength, stagger_in,
)
from tracer import find_entry_point, safe_call


class TestsPanel(ctk.CTkFrame):
    def __init__(self, parent, fonts, get_context) -> None:
        """`get_context()` -> (code: str, metadata: ProblemMetadata | None)."""
        super().__init__(parent, fg_color=BG)
        self.fonts = fonts
        self.get_context = get_context
        self.running = False
        self.show_only_failures = False
        self._last_results = None
        self._finished_while_hidden = False
        self._result_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_toolbar()
        self.toast = Toast(self, self.fonts)
        self.toast.grid_at(row=1, column=0, sticky="we")
        self._build_body()
        self._show_placeholder()
        # A completion that finished while this tab wasn't the active one
        # would otherwise go unnoticed — surface it the moment the tab is
        # actually shown again, instead of relying on a timer that might
        # elapse before anyone's looking.
        self.bind("<Map>", self._on_mapped)
        self.after(100, self._poll_queue)

    def _on_mapped(self, event=None) -> None:
        if self._finished_while_hidden:
            self._finished_while_hidden = False
            self.toast.show("Test run finished while you were on another tab.", color=ACCENT, hold_ms=4000)

    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="we", pady=(0, 12))
        self.run_button = ctk.CTkButton(
            bar, text="▶  Run All Tests", command=self._on_run, height=42, corner_radius=10,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, font=self.fonts.body_bold,
        )
        self.run_button.pack(side="left")
        add_press_feedback(self.run_button, ACCENT_PRESSED)
        self.spinner = Spinner(bar, size=16, color=ACCENT, bg=BG)
        self.status_label = ctk.CTkLabel(bar, text="", text_color=MUTED, font=self.fonts.small)
        self.status_label.pack(side="left", padx=(14, 0))

        self.filter_switch = ctk.CTkSwitch(
            bar, text="Show only failures", font=self.fonts.small, text_color=TEXT_DIM,
            progress_color=ACCENT, command=self._on_toggle_filter,
        )
        # Packed on demand once there are results to filter.

    def _build_body(self) -> None:
        self.body = ctk.CTkScrollableFrame(
            self, fg_color=BG, scrollbar_button_color=SCROLLBAR_THUMB, scrollbar_button_hover_color=SCROLLBAR_THUMB_HOVER,
        )
        self.body.grid(row=2, column=0, sticky="nswe")
        self.body.grid_columnconfigure(0, weight=1)

    def _show_placeholder(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        wrap = ctk.CTkFrame(self.body, fg_color="transparent")
        wrap.grid(row=0, column=0, pady=100)
        ctk.CTkLabel(wrap, text="✓", text_color=FAINT, font=ctk.CTkFont(size=30)).pack()
        ctk.CTkLabel(
            wrap,
            text="Reruns every official example (not just one), a set of curated\n"
                 "boundary cases, and a determinism check — all against your\n"
                 "own solution, on your own machine.",
            text_color=MUTED, font=self.fonts.body, justify="center",
        ).pack(pady=(10, 0))

    # -------------------------------------------------------------- running

    def _on_run(self) -> None:
        if self.running:
            return
        code, metadata = self.get_context()
        if not code.strip():
            self.status_label.configure(text="Paste a solution in the Editor tab first.", text_color=RED)
            return
        if metadata is None:
            self.status_label.configure(text="Still loading problem details — try again in a moment.", text_color=RED)
            return
        expected_name = metadata.function_name
        func_name, class_name = find_entry_point(code, expected_name)
        if not func_name:
            self.status_label.configure(text="Couldn't find a function definition in your code.", text_color=RED)
            return

        cases = parse_all_examples(metadata.example_testcases, metadata.param_names, metadata.content_text)
        if not cases:
            self.status_label.configure(text="Couldn't auto-detect example input for this problem.", text_color=RED)
            return

        self.running = True
        self.run_button.configure(state="disabled", text="Running...")
        self.spinner.pack(side="left", padx=(10, 0))
        self.spinner.start()
        self.status_label.configure(text="Running examples, boundary cases, and a determinism check...", text_color=MUTED)

        param_types = metadata.param_types
        threading.Thread(
            target=self._worker, args=(code, func_name, class_name, cases, param_types), daemon=True,
        ).start()

    def _worker(self, code, func_name, class_name, cases, param_types) -> None:
        regression_results = run_regression(code, func_name, cases, class_name)

        boundary_results: list[tuple[str, list, bool, str | None]] = []
        if can_fuzz(param_types):
            n_bound = max((len(a) for c in cases for a in c.args if isinstance(a, (list, str))), default=20)
            for label, args in generate_boundary_cases(param_types, max(n_bound, 20)):
                ok, error = safe_call(code, func_name, args, timeout_s=0.4, class_name=class_name)
                boundary_results.append((label, args, ok, error))

        det_ok, det_outputs = check_determinism(code, func_name, cases[0].args, class_name)

        self._result_queue.put(("done", (regression_results, boundary_results, det_ok, det_outputs)))

    def _poll_queue(self) -> None:
        try:
            kind, payload = self._result_queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_queue)
            return
        if kind == "done":
            self.running = False
            self.run_button.configure(state="normal", text="▶  Run All Tests")
            self.spinner.stop()
            self.spinner.pack_forget()
            self._last_results = payload
            self.filter_switch.pack(side="right", padx=(0, 4))
            self._render_results(*payload)
            if not self.winfo_ismapped():
                self._finished_while_hidden = True
        elif kind == "shrink_done":
            label, shrunk_args = payload
            self._shrink_result_labels[label].configure(text=f"Minimal failing input: {shrunk_args!r}")
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------ render

    def _on_toggle_filter(self) -> None:
        self.show_only_failures = bool(self.filter_switch.get())
        if self._last_results:
            self._render_results(*self._last_results)

    def _render_results(self, regression_results, boundary_results, det_ok, det_outputs) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        self._shrink_result_labels: dict[str, ctk.CTkLabel] = {}

        n_pass = sum(1 for r in regression_results if r.passed)
        n_fail = sum(1 for r in regression_results if r.passed is False)
        n_crash = sum(1 for r in regression_results if not r.ok)
        n_unverified = sum(1 for r in regression_results if r.ok and r.passed is None)
        summary_color = RED if (n_fail or n_crash) else GREEN
        self.status_label.configure(
            text=f"{n_pass} passed, {n_fail} wrong, {n_crash} crashed, {n_unverified} unverified.",
            text_color=summary_color,
        )

        row = 0
        examples_card = self._card(row)
        row += 1
        ctk.CTkLabel(examples_card, text="Official Examples", font=self.fonts.card_title, text_color=TEXT).pack(
            anchor="w", padx=20, pady=(18, 10)
        )
        shown_examples = [r for r in regression_results if not self.show_only_failures or not r.ok or r.passed is False]
        if not shown_examples:
            ctk.CTkLabel(
                examples_card, text="No failures — nice.", text_color=FAINT, font=self.fonts.small,
            ).pack(anchor="w", padx=20, pady=(0, 16))
        for r in shown_examples:
            self._example_row(examples_card, r)
        ctk.CTkLabel(examples_card, text="", height=8).pack()

        det_card = self._card(row)
        row += 1
        ctk.CTkLabel(det_card, text="Determinism Check", font=self.fonts.card_title, text_color=TEXT).pack(
            anchor="w", padx=20, pady=(18, 6)
        )
        if det_ok:
            ctk.CTkLabel(
                det_card, text=f"✓ Same input produced the same output across 5 runs: {det_outputs[0]}",
                text_color=GREEN, font=self.fonts.small,
            ).pack(anchor="w", padx=20, pady=(0, 16))
        else:
            outputs_text = ", ".join(det_outputs[:5])
            label = ctk.CTkLabel(
                det_card, text=f"⚠ Same input produced different outputs across runs: {outputs_text}",
                text_color=YELLOW, font=self.fonts.small, justify="left",
            )
            label.pack(anchor="w", padx=20, pady=(0, 16))
            bind_responsive_wraplength(label, extra_padding=40)

        boundary_card = None
        if boundary_results:
            boundary_card = self._card(row)
            row += 1
            ctk.CTkLabel(boundary_card, text="Boundary Cases", font=self.fonts.card_title, text_color=TEXT).pack(
                anchor="w", padx=20, pady=(18, 10)
            )
            crashes = [b for b in boundary_results if not b[2]]
            if not crashes:
                ctk.CTkLabel(
                    boundary_card, text=f"✓ All {len(boundary_results)} boundary cases ran without crashing.",
                    text_color=GREEN, font=self.fonts.small,
                ).pack(anchor="w", padx=20, pady=(0, 16))
            else:
                i = 0
                for label, args, ok, error in boundary_results:
                    if not ok:
                        self._boundary_row(boundary_card, label, args, error, i)
                        i += 1
                ctk.CTkLabel(boundary_card, text="", height=8).pack()

        stagger_in([c for c in (examples_card, det_card, boundary_card) if c is not None])

    def _card(self, row: int) -> ctk.CTkFrame:
        card = ctk.CTkFrame(self.body, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
        card.grid(row=row, column=0, sticky="we", pady=(0, 16))
        return card

    def _example_row(self, parent, r: ExampleResult) -> None:
        row = ctk.CTkFrame(parent, fg_color=CARD_BG_2, corner_radius=8)
        row.pack(fill="x", padx=20, pady=3)
        add_hover(row, CARD_BG_2, ROW_HOVER)
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=8)

        if not r.ok:
            badge_text, bg, fg = "CRASH", RED_SOFT, RED
        elif r.passed is True:
            badge_text, bg, fg = "PASS", GREEN_SOFT, GREEN
        elif r.passed is False:
            badge_text, bg, fg = "WRONG", RED_SOFT, RED
        else:
            badge_text, bg, fg = "RAN", YELLOW_SOFT, YELLOW

        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")
        badge = ctk.CTkFrame(top, fg_color=bg, corner_radius=999)
        badge.pack(side="left")
        ctk.CTkLabel(badge, text=badge_text, text_color=fg, font=self.fonts.pill, fg_color="transparent").pack(
            padx=10, pady=2
        )
        ctk.CTkLabel(
            top, text=f"Example {r.case.index}: {r.case.args!r}", text_color=TEXT_DIM, font=self.fonts.code_small,
        ).pack(side="left", padx=(10, 0))
        if r.order_independent_match:
            ctk.CTkLabel(
                top, text="different order, same elements", text_color=MUTED, font=self.fonts.small,
            ).pack(side="left", padx=(10, 0))

        if not r.ok:
            detail_text = f"Error: {r.error}"
        elif r.passed is False:
            detail_text = f"Got {r.actual_repr}, expected {r.case.expected_repr}"
        elif r.passed is None:
            detail_text = f"Ran successfully: {r.actual_repr} (couldn't confirm expected output)"
        else:
            detail_text = None

        if detail_text:
            ctk.CTkLabel(
                inner, text=detail_text, text_color=MUTED, font=self.fonts.small, justify="left", anchor="w",
            ).pack(anchor="w", pady=(4, 0), fill="x")

        if not r.ok:
            shrink_key = f"example-{r.case.index}"
            result_label = ctk.CTkLabel(inner, text="", text_color=ACCENT, font=self.fonts.small, anchor="w")
            result_label.pack(anchor="w", fill="x")
            self._shrink_result_labels[shrink_key] = result_label
            ctk.CTkButton(
                inner, text="Shrink to Minimal Failing Input", height=24, corner_radius=6, font=self.fonts.small,
                fg_color=CARD_BG, hover_color=HOVER_TINT, text_color=TEXT_DIM,
                command=lambda: self._on_shrink(shrink_key, r.case.args),
            ).pack(anchor="w", pady=(4, 0))

    def _boundary_row(self, parent, label: str, args: list, error: str, index: int) -> None:
        row = ctk.CTkFrame(parent, fg_color=CARD_BG_2, corner_radius=8)
        row.pack(fill="x", padx=20, pady=3)
        add_hover(row, CARD_BG_2, ROW_HOVER)
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=8)
        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")
        badge = ctk.CTkFrame(top, fg_color=RED_SOFT, corner_radius=999)
        badge.pack(side="left")
        ctk.CTkLabel(badge, text="CRASH", text_color=RED, font=self.fonts.pill, fg_color="transparent").pack(
            padx=10, pady=2
        )
        ctk.CTkLabel(top, text=label, text_color=TEXT_DIM, font=self.fonts.small).pack(side="left", padx=(10, 0))
        ctk.CTkLabel(
            inner, text=f"Error: {error}", text_color=MUTED, font=self.fonts.small, anchor="w",
        ).pack(anchor="w", pady=(4, 0), fill="x")

        shrink_key = f"boundary-{index}"
        result_label = ctk.CTkLabel(inner, text="", text_color=ACCENT, font=self.fonts.small, anchor="w")
        result_label.pack(anchor="w", fill="x")
        self._shrink_result_labels[shrink_key] = result_label
        ctk.CTkButton(
            inner, text="Shrink to Minimal Failing Input", height=24, corner_radius=6, font=self.fonts.small,
            fg_color=CARD_BG, hover_color=HOVER_TINT, text_color=TEXT_DIM,
            command=lambda: self._on_shrink(shrink_key, args),
        ).pack(anchor="w", pady=(4, 0))

    def _on_shrink(self, key: str, args: list) -> None:
        code, metadata = self.get_context()
        if metadata is None:
            return
        func_name, class_name = find_entry_point(code, metadata.function_name)
        if not func_name:
            return
        self._shrink_result_labels[key].configure(text="Shrinking...")
        threading.Thread(
            target=self._shrink_worker, args=(key, code, func_name, class_name, metadata.param_types, args),
            daemon=True,
        ).start()

    def _shrink_worker(self, key, code, func_name, class_name, param_types, args) -> None:
        shrunk = shrink_failing_input(code, func_name, param_types, args, class_name)
        self._result_queue.put(("shrink_done", (key, shrunk)))

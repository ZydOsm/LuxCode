"""Desktop GUI for the LeetCode submission analyzer, built with CustomTkinter."""

from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk

import customtkinter as ctk

from analyzer import (
    AnalyzerError, PlaygroundResult, ReviewResult, analyze_playground, analyze_submission,
    generate_hints, suggest_alternatives, transpile,
)
from api_keys import PROVIDERS, any_key_configured, get_key, has_key, write_key
from ast_lint import lint
from code_editor import CodeEditor
from constraints import estimate, extract_n, recommendation
from fuzzer import can_fuzz, fuzz, generate_case
import history
from history import record_analysis
import profiles
from panel_skills import SkillsPanel
from floating_timer import FloatingTimer
from panel_whiteboard import WhiteboardPanel
from race import race
from tracer import find_entry_point, parse_example_args
from leetcode_api import LeetCodeAPIError, LeetCodeClient, ProblemMetadata, ProblemSummary
from codeforces_api import CodeforcesAPIError, CodeforcesClient
from panel_tests import TestsPanel
from panel_trace import TracePanel
from settings import load_settings, save_settings, update_settings
from stencils import STENCILS
from theme import (
    ACCENT, ACCENT_HOVER, APP_NAME, APP_TAGLINE, BG, BLUE, BODY_FAMILY, BORDER, BRAND_GOLD, CARD_BG,
    CARD_BG_2, CODE_FAMILY, DANGER_HOVER, DIFFICULTY_COLOR, DIFFICULTY_SOFT, DISABLED_BG, DISABLED_ICON,
    EDITOR_CHROME, FAINT, FONT_SCALE, GREEN, HEADING_FAMILY_SEMIBOLD, HOVER_TINT, LIST_BG,
    LIST_HOVER_BG, MUTED, RED, REDUCED_MOTION, SCROLLBAR_THUMB, SCROLLBAR_THUMB_HOVER, SIDEBAR_BG,
    TEXT, TEXT_DIM, THEME_MODE, YELLOW, YELLOW_SOFT, GREEN_SOFT, Fonts, Spinner,
    bind_responsive_wraplength, _draw_score_gauge, _format_math, _lerp, _lerp_color,
    _normalize_big_o, _pill, _truncate_to_width, animate, ease_in_out_sine, set_reduced_motion,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Question providers. "LeetCode" and "Codeforces" are both real, working
# clients — not a stand-in for a literal "every judge" promise. Codeforces
# problems are stdin/stdout, not "implement this function", so they carry no
# function signature/example testcases; see codeforces_api.py's header for
# what that does and doesn't disable. "Playground" isn't backed by a client
# at all — it's the no-problem-attached, LLM-infers-the-purpose mode, listed
# as a provider in its own right rather than a hidden fallback for "you
# didn't pick a problem".
PROVIDER_CLIENTS = {"LeetCode": LeetCodeClient, "Codeforces": CodeforcesClient}
PLAYGROUND_PROVIDER = "Playground"
PROVIDER_NAMES = list(PROVIDER_CLIENTS.keys()) + [PLAYGROUND_PROVIDER]

DEFAULT_MODEL = "gemini-3.5-flash-lite"
MODEL_OPTIONS = [
    "gemini-3.5-flash-lite",  # cheapest / lowest token usage — default
    "gemini-3.5-flash",
    "gemini-3-pro",
    "gpt-4o-mini",
    "gpt-4o",
    "claude-3-5-sonnet-latest",
]

# Every language LeetCode's own submission dropdown offers for general
# algorithm problems (its DB-only languages — MySQL, PostgreSQL, MS SQL,
# Oracle, Pandas — are a different problem type and out of scope here).
LEETCODE_LANGUAGES = [
    "Python3", "Python", "C++", "Java", "C", "C#", "JavaScript", "TypeScript",
    "PHP", "Swift", "Kotlin", "Dart", "Go", "Ruby", "Scala", "Rust", "Racket", "Erlang", "Elixir",
]

MAX_SEARCH_RESULTS = 30

CHANGELOG: list[tuple[str, list[str]]] = [
    ("Rebrand", [
        "LeetCode Analyzer is now LuxCode, LeetCode Premium, on steroids",
        "New API key setup flow: pick a provider and paste a key on first launch, or anytime from Settings",
    ]),
    ("Debugger & test suite", [
        "Trace tab: breakpoints, conditional breakpoints, watch expressions, call-stack inspector",
        "Trace tab: step into/over/out/back, jump-to-exception, LLM exception explanations",
        "Trace tab: variable value history and mutation tracking for lists/dicts/sets",
        "New Tests tab: reruns every official example, boundary cases, determinism check, input shrinking",
    ]),
    ("Design polish", [
        "Matching-bracket highlighting and indent guides in the code editor",
        "Hover states, staggered card animations, and a memory-usage tooltip in the Trace tab",
        "Settings panel: theme (dark/light/high-contrast), reduced motion, font scale",
    ]),
]


def _make_window_icon(size: int = 32) -> tk.PhotoImage:
    """A gold "L" monogram on a rounded black square — the LuxCode window/
    taskbar icon, drawn with pure Tkinter (no Pillow dependency) so it
    matches the sidebar's brand mark instead of the generic Tk feather."""
    img = tk.PhotoImage(width=size, height=size)
    margin = max(1, size // 8)
    corner = max(2, size // 5)
    # The "L" glyph, expressed as fractions of the icon's inner size so it
    # scales cleanly if `size` ever changes: a vertical stroke down the left
    # third, plus a horizontal foot extending right along the bottom.
    stroke = max(2, size // 7)
    l_left = margin + size // 6
    l_top = margin + size // 6
    l_bottom = size - margin - size // 6
    l_right = size - margin - size // 6

    for y in range(size):
        for x in range(size):
            inside = margin <= x < size - margin and margin <= y < size - margin
            if not inside:
                img.put(BG, (x, y))
                continue
            # Round the four corners by clipping a small triangle out of each.
            near_corner = (
                (x < margin + corner and y < margin + corner and (x - margin) + (y - margin) < corner)
                or (x >= size - margin - corner and y < margin + corner and (size - margin - x) + (y - margin) < corner)
                or (x < margin + corner and y >= size - margin - corner and (x - margin) + (size - margin - y) < corner)
                or (x >= size - margin - corner and y >= size - margin - corner and (size - margin - x) + (size - margin - y) < corner)
            )
            if near_corner:
                img.put(BG, (x, y))
                continue
            on_vertical_stroke = l_left <= x < l_left + stroke and l_top <= y < l_bottom
            on_horizontal_foot = l_left <= x < l_right and l_bottom - stroke <= y < l_bottom
            img.put(BRAND_GOLD if (on_vertical_stroke or on_horizontal_foot) else BG, (x, y))
    return img


# ---------------------------------------------------------------- play button


class PlayButton(ctk.CTkFrame):
    """An animated call-to-action: a play icon that lights up when ready, spins while busy."""

    def __init__(self, parent, text: str, command, font: ctk.CTkFont, height: int = 48) -> None:
        super().__init__(parent, corner_radius=height // 2, fg_color=DISABLED_BG, height=height)
        self.grid_propagate(False)
        self.command = command
        self.base_text = text
        self.enabled = False
        self.busy = False
        self._bg_color = DISABLED_BG
        self._icon_color = DISABLED_ICON
        self._text_color = TEXT_DIM
        self._spin_angle = 0.0

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.place(relx=0.5, rely=0.5, anchor="center")

        self.icon = tk.Canvas(inner, width=20, height=20, bg=DISABLED_BG, highlightthickness=0)
        self.icon.pack(side="left", padx=(0, 8))
        self.label = ctk.CTkLabel(inner, text=text, font=font, text_color=self._text_color, fg_color="transparent")
        self.label.pack(side="left")

        self._draw_play(DISABLED_ICON)

        for widget in (self, inner, self.icon, self.label):
            widget.bind("<Button-1>", self._on_click)
            widget.configure(cursor="hand2") if hasattr(widget, "configure") else None

    # -- drawing ----------------------------------------------------------

    def _draw_play(self, color: str) -> None:
        self.icon.delete("all")
        self.icon.create_polygon(5, 3, 5, 17, 17, 10, fill=color, outline="")

    def _draw_spinner_frame(self) -> None:
        self.icon.delete("all")
        self.icon.create_arc(
            2, 2, 18, 18, start=self._spin_angle, extent=100, style="arc",
            outline=self._icon_color, width=2,
        )

    def _apply_current_colors(self) -> None:
        if not self.winfo_exists():
            return
        self.configure(fg_color=self._bg_color)
        self.icon.configure(bg=self._bg_color)
        if not self.busy:
            self._draw_play(self._icon_color)
        self.label.configure(text_color=self._text_color)

    # -- state --------------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        if self.busy:
            self.enabled = enabled
            return
        if enabled == self.enabled:
            return
        self.enabled = enabled
        start_bg, start_icon, start_text = self._bg_color, self._icon_color, self._text_color
        target_bg = ACCENT if enabled else DISABLED_BG
        target_icon = "#ffffff" if enabled else DISABLED_ICON
        target_text = "#ffffff" if enabled else TEXT_DIM

        def on_update(t: float) -> None:
            self._bg_color = _lerp_color(start_bg, target_bg, t)
            self._icon_color = _lerp_color(start_icon, target_icon, t)
            self._text_color = _lerp_color(start_text, target_text, t)
            self._apply_current_colors()

        def on_done() -> None:
            if self.enabled and not self.busy:
                self._pulse_forward()

        animate(self, 260, on_update, on_done=on_done)

    def _pulse_forward(self) -> None:
        # REDUCED_MOTION makes animate() call on_done() immediately/
        # synchronously instead of deferring via .after() — since
        # _pulse_forward/_pulse_backward call each other as on_done, that
        # combination is unbounded recursion with no base case. An idle
        # glow-pulse is exactly the kind of motion Reduced Motion should
        # suppress anyway, so just skip it entirely in that mode.
        if self.busy or not self.enabled or not self.winfo_exists() or REDUCED_MOTION:
            return
        start = self._bg_color
        animate(
            self, 1400, lambda t: (setattr(self, "_bg_color", _lerp_color(start, ACCENT_HOVER, t)), self._apply_current_colors()),
            on_done=self._pulse_backward, easing=ease_in_out_sine,
        )

    def _pulse_backward(self) -> None:
        if self.busy or not self.enabled or not self.winfo_exists() or REDUCED_MOTION:
            return
        start = self._bg_color
        animate(
            self, 1400, lambda t: (setattr(self, "_bg_color", _lerp_color(start, ACCENT, t)), self._apply_current_colors()),
            on_done=self._pulse_forward, easing=ease_in_out_sine,
        )

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        if busy:
            self.label.configure(text="Analyzing...")
            self._spin_angle = 0.0
            self._spin()
        else:
            self.label.configure(text=self.base_text)
            self._apply_current_colors()
            if self.enabled:
                self._pulse_forward()

    def _spin(self) -> None:
        if not self.busy or not self.winfo_exists():
            return
        self._draw_spinner_frame()
        self._spin_angle = (self._spin_angle - 26) % 360
        self.after(30, self._spin)

    def flash(self, ok: bool) -> None:
        color = GREEN if ok else RED
        start_bg = self._bg_color

        def to_flash(t: float) -> None:
            self._bg_color = _lerp_color(start_bg, color, t)
            self._apply_current_colors()

        def hold_then_revert() -> None:
            self.after(260, revert)

        def revert() -> None:
            if not self.winfo_exists():
                return
            target_bg = ACCENT if self.enabled else DISABLED_BG
            start = self._bg_color

            def to_normal(t: float) -> None:
                self._bg_color = _lerp_color(start, target_bg, t)
                self._apply_current_colors()

            animate(self, 260, to_normal, on_done=self._pulse_forward if self.enabled else None)

        animate(self, 180, to_flash, on_done=hold_then_revert)

    def _on_click(self, event=None) -> None:
        if not self.enabled or self.busy:
            return
        self.command()


# ---------------------------------------------------------------- problem row


class ProblemRow(ctk.CTkFrame):
    def __init__(self, parent, problem: ProblemSummary, on_select, font: ctk.CTkFont) -> None:
        super().__init__(parent, fg_color=LIST_BG, corner_radius=8)
        self.problem = problem
        self._on_select = on_select
        self._current_bg = LIST_BG
        self.grid_columnconfigure(1, weight=1)

        self._dot_color = DIFFICULTY_COLOR.get(problem.difficulty, MUTED)
        self.dot = tk.Canvas(self, width=10, height=10, bg=LIST_BG, highlightthickness=0)
        self._dot_id = self.dot.create_oval(1, 1, 9, 9, fill=self._dot_color, outline="")
        self.dot.grid(row=0, column=0, padx=(12, 8), pady=7)

        prefix = f"{problem.frontend_id}.  "
        title = _truncate_to_width(problem.title, font, max(195 - font.measure(prefix), 40))
        self.label = ctk.CTkLabel(
            self, text=f"{prefix}{title}", font=font,
            text_color=TEXT, anchor="w", fg_color="transparent",
        )
        self.label.grid(row=0, column=1, sticky="we", pady=7, padx=(0, 12))

        for widget in (self, self.dot, self.label):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            widget.bind("<Button-1>", self._on_click)

    def reveal(self, delay_ms: int = 0) -> None:
        self.label.configure(text_color=LIST_BG)
        self.dot.itemconfig(self._dot_id, fill=LIST_BG)

        def start() -> None:
            if not self.winfo_exists():
                return

            def on_update(t: float) -> None:
                if not self.winfo_exists():
                    return
                self.label.configure(text_color=_lerp_color(LIST_BG, TEXT, t))
                self.dot.itemconfig(self._dot_id, fill=_lerp_color(LIST_BG, self._dot_color, t))

            animate(self, 220, on_update)

        self.after(delay_ms, start)

    def _animate_bg(self, target: str) -> None:
        start = self._current_bg

        def on_update(t: float) -> None:
            if not self.winfo_exists():
                return
            color = _lerp_color(start, target, t)
            self._current_bg = color
            self.configure(fg_color=color)
            self.dot.configure(bg=color)

        animate(self, 120, on_update)

    def _on_enter(self, event=None) -> None:
        self._animate_bg(LIST_HOVER_BG)

    def _on_leave(self, event=None) -> None:
        self._animate_bg(LIST_BG)

    def _on_click(self, event=None) -> None:
        self._on_select(self.problem)


# ---------------------------------------------------------------- main app


class AnalyzerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} - {APP_TAGLINE}")
        self.settings = load_settings()

        saved_window = self.settings.get("window")
        if saved_window:
            win_w, win_h, win_x, win_y = saved_window["w"], saved_window["h"], saved_window["x"], saved_window["y"]
        else:
            win_w, win_h = 1480, 940
            win_x = (self.winfo_screenwidth() - win_w) // 2
            win_y = (self.winfo_screenheight() - win_h) // 2
        self.geometry(f"{win_w}x{win_h}+{win_x}+{win_y}")
        # winfo_width()/winfo_rootx() report a placeholder (~200x200) for a
        # window that's never been mapped — which this one won't be until a
        # profile is picked (see withdraw() below) — so the startup profile
        # picker centers itself against these known-good numbers instead.
        self._initial_geometry = (win_w, win_h, win_x, win_y)
        self.minsize(1140, 740)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Stay hidden until a profile is actually picked — the picker modal
        # (below) is a transient child of this window, which still displays
        # fine on Windows while its master is withdrawn. Revealed for real
        # in _on_profile_selected() once the choice is made.
        self.withdraw()

        self._window_icon = _make_window_icon()
        try:
            self.iconphoto(True, self._window_icon)
        except tk.TclError:
            pass  # not every platform/window-manager supports iconphoto — non-fatal

        self._build_fonts()
        self._bind_shortcuts()

        self.active_profile_id = history.DEFAULT_PROFILE_ID
        self.active_provider = "LeetCode"
        self._provider_clients = {name: cls() for name, cls in PROVIDER_CLIENTS.items()}
        self.all_problems: list[ProblemSummary] = []
        self.filtered_problems: list[ProblemSummary] = []
        self.selected_problem: ProblemSummary | None = None
        self.current_metadata: ProblemMetadata | None = None
        self._problems_loaded = False
        self._result_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._listbox_rows: list[ProblemRow] = []

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_area()
        self._show_report_placeholder()

        self._set_status("Loading problem list...", MUTED, busy=True)
        threading.Thread(target=self._load_problem_list, args=(self.active_provider,), daemon=True).start()
        self.after(100, self._poll_queue)

        # Netflix-style profile picker shows every launch, not just first run
        # — "who's coding" the same way "who's watching" gates every session
        # there. The API-key setup modal (if still needed) follows it, once
        # a profile is actually chosen — see _on_profile_selected().
        self.after(50, lambda: self._show_profile_picker(allow_cancel=False))

    def _build_fonts(self) -> None:
        self.fonts = Fonts()  # canonical font set, shared with feature panels
        self.f_title = self.fonts.title
        self.f_subtitle = self.fonts.subtitle
        self.f_subtitle_bold = self.fonts.subtitle_bold
        self.f_section = self.fonts.section
        self.f_body = self.fonts.body
        self.f_body_bold = self.fonts.body_bold
        self.f_small = self.fonts.small
        self.f_small_bold = self.fonts.small_bold
        self.f_card_title = self.fonts.card_title
        self.f_score = self.fonts.score
        self.f_button = self.fonts.button
        self.f_code = self.fonts.code
        self.f_pill = self.fonts.pill
        # A dedicated, larger size for icon-only buttons (settings, changelog,
        # help) — self.f_body reads fine as text but is too small to register
        # clearly as a clickable glyph on its own.
        self.f_icon = ctk.CTkFont(family=BODY_FAMILY, size=int(self.fonts.card_title.cget("size") * 0.8))

    def _save_window_geometry(self) -> None:
        # Tk geometry strings use +/- for BOTH the delimiter and negative
        # offsets (e.g. "1480x940-50+80" on a monitor left of the primary),
        # so a naive split("+") breaks — parse with an explicit sign group.
        match = re.match(r"(\d+)x(\d+)([+-]\d+)([+-]\d+)", self.geometry())
        if match:
            w, h, x, y = match.groups()
            update_settings(window={"w": int(w), "h": int(h), "x": int(x), "y": int(y)})

    @property
    def problem_client(self):
        return self._provider_clients[self.active_provider]

    def _on_close(self) -> None:
        self._save_window_geometry()
        for client in self._provider_clients.values():
            client.close()
        self.destroy()

    def _relaunch_app(self) -> None:
        """Theme/font-scale changes are resolved once at import time (see
        theme.py) — there is no live hook left to re-paint an already-built
        widget tree. Rather than making the user close and manually reopen
        the app to see a Settings change take effect, do it for them: save
        window geometry, spawn a fresh process, then exit this one."""
        self._save_window_geometry()
        for client in self._provider_clients.values():
            client.close()
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable])
        else:
            subprocess.Popen([sys.executable, os.path.abspath(sys.argv[0])])
        self.destroy()
        sys.exit(0)

    def _bind_shortcuts(self) -> None:
        """Space/arrow-key trace controls — scoped to when the Trace tab is
        active AND focus isn't inside a text-entry widget, so normal typing
        elsewhere is never intercepted."""
        def _typing_in_entry() -> bool:
            focused = self.focus_get()
            return isinstance(focused, (tk.Entry, tk.Text)) or focused.__class__.__name__ in (
                "CTkEntry", "CTkTextbox",
            )

        def _guarded(handler, tab: str = "Trace"):
            def wrapped(event=None):
                if self.tabview.get() != tab or _typing_in_entry():
                    return
                handler()
                return "break"
            return wrapped

        self.bind("<space>", _guarded(lambda: self.trace_panel._toggle_play()))
        self.bind("<Right>", _guarded(lambda: self.trace_panel._step_into()))
        self.bind("<Left>", _guarded(lambda: self.trace_panel._step_back()))
        self.bind("<Shift-Right>", _guarded(lambda: self.trace_panel._step_over()))
        self.bind("<Shift-Left>", _guarded(lambda: self.trace_panel._step_out()))

        self.bind("<Control-z>", _guarded(lambda: self.whiteboard_panel.undo(), tab="Whiteboard"))
        self.bind("<Control-y>", _guarded(lambda: self.whiteboard_panel.redo(), tab="Whiteboard"))

    def _show_confetti(self) -> None:
        """A short celebratory burst for a genuine 10/10 — earned, not a
        cheat code. Bounded to its own small popup rather than a real
        full-screen overlay (no reliance on platform-specific transparent-
        window tricks), auto-closes itself after ~2 seconds."""
        import random

        popup = ctk.CTkToplevel(self)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        w, h = 420, 260
        self.update_idletasks()
        x = self.winfo_rootx() + self.winfo_width() // 2 - w // 2
        y = self.winfo_rooty() + self.winfo_height() // 2 - h // 2
        popup.geometry(f"{w}x{h}+{x}+{y}")

        card = ctk.CTkFrame(popup, fg_color=CARD_BG, corner_radius=16, border_width=2, border_color=ACCENT)
        card.pack(fill="both", expand=True)
        ctk.CTkLabel(card, text="🎉 Perfect score!", font=self.f_card_title, text_color=TEXT).pack(pady=(16, 0))
        ctk.CTkLabel(card, text="10 / 10 · structure & clarity", font=self.f_small, text_color=MUTED).pack()

        canvas = tk.Canvas(card, bg=CARD_BG, highlightthickness=0)
        canvas.pack(fill="both", expand=True, padx=4, pady=(4, 4))
        canvas.update_idletasks()
        cw = max(canvas.winfo_width(), w - 8)

        colors = [ACCENT, GREEN, YELLOW, RED, BRAND_GOLD, BLUE]
        particles = []  # [item_id, x, y, vx, vy]
        for _ in range(70):
            x0 = random.uniform(0, cw)
            y0 = random.uniform(-h, 0)
            size = random.uniform(4, 9)
            item = canvas.create_rectangle(
                x0, y0, x0 + size, y0 + size, fill=random.choice(colors), outline="",
            )
            particles.append([item, x0, y0, random.uniform(-1.5, 1.5), random.uniform(3, 7)])

        def tick(frame: int = 0) -> None:
            if not popup.winfo_exists():
                return
            if frame > 70:
                popup.destroy()
                return
            for p in particles:
                item, x0, y0, vx, vy = p
                x0 += vx
                y0 += vy
                p[1], p[2] = x0, y0
                canvas.coords(item, x0, y0, x0 + 6, y0 + 6)
            popup.after(30, lambda: tick(frame + 1))

        tick()

    def _section_label(self, parent, text: str) -> ctk.CTkLabel:
        label = ctk.CTkLabel(parent, text=text.upper(), text_color=MUTED, font=self.f_section)
        label.pack(anchor="w", padx=24, pady=(0, 6))
        return label

    def _set_status(self, text: str, color: str, busy: bool = False) -> None:
        self.status_label.configure(text=text, text_color=color)
        if busy:
            self.load_spinner.start()
            self.load_spinner.pack(side="left", padx=(0, 6))
        else:
            self.load_spinner.stop()
            self.load_spinner.pack_forget()

    # ------------------------------------------------------------------ UI

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, width=420, fg_color=SIDEBAR_BG, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nswe")
        sidebar.grid_propagate(False)

        divider = ctk.CTkFrame(self, width=1, fg_color=BORDER, corner_radius=0)
        divider.place(in_=sidebar, relx=1.0, rely=0, relheight=1.0, x=-1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.pack(anchor="w", padx=24, pady=(28, 4), fill="x")
        # A small gold/silver duotone mark nods to the LuxCode logo without
        # touching ACCENT (purple) anywhere else in the app's functional UI.
        mark = ctk.CTkFrame(brand, width=10, height=10, fg_color=BRAND_GOLD, corner_radius=3)
        mark.pack(side="left", pady=4)
        ctk.CTkLabel(brand, text=f"  {APP_NAME}", font=self.f_title, text_color=TEXT).pack(side="left")
        ctk.CTkButton(
            brand, text="⚙", width=36, height=36, corner_radius=9, fg_color=CARD_BG,
            hover_color=CARD_BG_2, text_color=TEXT_DIM, font=self.f_icon, command=self._show_settings_modal,
        ).pack(side="right")
        ctk.CTkButton(
            brand, text="✨", width=36, height=36, corner_radius=9, fg_color=CARD_BG,
            hover_color=CARD_BG_2, text_color=TEXT_DIM, font=self.f_icon, command=self._show_changelog_modal,
        ).pack(side="right", padx=(6, 6))
        ctk.CTkButton(
            brand, text="?", width=36, height=36, corner_radius=9, fg_color=CARD_BG,
            hover_color=CARD_BG_2, text_color=TEXT_DIM, font=self.f_icon, command=self._show_help_modal,
        ).pack(side="right")
        ctk.CTkLabel(
            sidebar, text="Developed by Zyad", text_color=FAINT, font=self.f_small,
        ).pack(anchor="w", padx=24, pady=(0, 6))
        ctk.CTkLabel(
            sidebar, text=APP_TAGLINE, text_color=BRAND_GOLD, font=self.f_subtitle_bold,
        ).pack(anchor="w", padx=24, pady=(0, 2))
        ctk.CTkLabel(
            sidebar, text="Complexity & code review",
            text_color=MUTED, font=self.f_small,
        ).pack(anchor="w", padx=24, pady=(0, 24))

        if not self.settings.get("onboarded", False):
            self._show_onboarding_banner(sidebar)

        self._section_label(sidebar, "Provider")
        self.provider_menu = ctk.CTkOptionMenu(
            sidebar, values=PROVIDER_NAMES, command=self._on_provider_changed,
            font=self.f_body, dropdown_font=self.f_body,
            fg_color=CARD_BG, button_color=CARD_BG_2, button_hover_color=HOVER_TINT,
            dropdown_fg_color=CARD_BG_2, dropdown_hover_color=LIST_HOVER_BG,
            dropdown_text_color=TEXT, text_color=TEXT, corner_radius=10, height=46,
        )
        self.provider_menu.set(self.active_provider)
        self.provider_menu.pack(fill="x", padx=24, pady=(0, 6))
        self.provider_note = ctk.CTkLabel(
            sidebar, text="", text_color=MUTED, font=self.f_small, justify="left", anchor="w", wraplength=330,
        )
        self.provider_note.pack(anchor="w", padx=24, pady=(0, 20))
        self._update_provider_note()

        # Everything problem-search-related lives in its own container so
        # Playground mode (which has no problem catalog at all) can hide the
        # whole thing in one call — see _on_provider_changed.
        self.problem_section = ctk.CTkFrame(sidebar, fg_color="transparent")
        self.problem_section.pack(fill="x")

        self._section_label(self.problem_section, "Problem")
        entry_wrap = ctk.CTkFrame(self.problem_section, fg_color="transparent")
        entry_wrap.pack(fill="x", padx=24)
        self.problem_entry = ctk.CTkEntry(
            entry_wrap, placeholder_text="Loading problem list...", state="disabled",
            font=self.f_body, fg_color=CARD_BG, border_color=BORDER, border_width=1,
            corner_radius=10, height=46, text_color=TEXT,
        )
        self.problem_entry.pack(fill="x")
        self.problem_entry.bind("<KeyRelease>", self._on_search_keyrelease)
        self.problem_entry.bind("<FocusIn>", self._on_search_focus_in)
        self.problem_entry.bind("<Return>", self._on_search_return)
        self.problem_entry.bind("<Escape>", lambda e: self._hide_listbox())
        self.problem_entry.bind("<FocusOut>", self._on_search_focus_out)

        self.problem_listbox = ctk.CTkScrollableFrame(
            self.problem_section, fg_color=LIST_BG, corner_radius=10, height=190,
            scrollbar_button_color=SCROLLBAR_THUMB, scrollbar_button_hover_color=SCROLLBAR_THUMB_HOVER,
        )

        self.selected_badge_frame = ctk.CTkFrame(self.problem_section, fg_color="transparent")
        self.selected_badge_frame.pack(fill="x", padx=24, pady=(8, 10))
        self._render_selected_badge()

        self.constraint_card = ctk.CTkFrame(
            self.problem_section, fg_color=CARD_BG, corner_radius=10, border_width=1, border_color=BORDER,
        )
        self.constraint_label = ctk.CTkLabel(
            self.constraint_card, text="", text_color=TEXT_DIM, font=self.f_small,
            wraplength=330, justify="left", anchor="w",
        )
        self.constraint_label.pack(padx=14, pady=10, anchor="w")

        self.playground_note = ctk.CTkLabel(
            sidebar,
            text="Playground mode: no problem needed. Paste any code in the\n"
                 "Editor tab and click Analyze; the LLM figures out what it does.",
            text_color=MUTED, font=self.f_small, justify="left",
        )

        # Kept as an anchor so problem_section/playground_note can be
        # re-inserted at the right spot after being hidden (pack() with no
        # position args always appends at the end, which would otherwise
        # reorder the sidebar) — see _on_provider_changed.
        self._language_section_label = self._section_label(sidebar, "Language")
        self.language_menu = ctk.CTkOptionMenu(
            sidebar, values=LEETCODE_LANGUAGES, command=self._on_language_changed,
            font=self.f_body, dropdown_font=self.f_body,
            fg_color=CARD_BG, button_color=CARD_BG_2, button_hover_color=HOVER_TINT,
            dropdown_fg_color=CARD_BG_2, dropdown_hover_color=LIST_HOVER_BG,
            dropdown_text_color=TEXT, text_color=TEXT, corner_radius=10, height=46,
        )
        self.language_menu.set("Python3")
        self.language_menu.pack(fill="x", padx=24, pady=(0, 6))
        self.language_note = ctk.CTkLabel(
            sidebar,
            text="Execution Trace, Tests, Fuzz, and the Performance Race run real Python;\n"
                 "they stay Python-only. Other languages get full LLM analysis on the Report tab.",
            text_color=MUTED, font=self.f_small, justify="left",
        )
        self.language_note.pack(anchor="w", padx=24, pady=(0, 20))

        self._section_label(sidebar, "Model")
        self.model_menu = ctk.CTkOptionMenu(
            sidebar, values=MODEL_OPTIONS, font=self.f_body, dropdown_font=self.f_body,
            fg_color=CARD_BG, button_color=CARD_BG_2, button_hover_color=HOVER_TINT,
            dropdown_fg_color=CARD_BG_2, dropdown_hover_color=LIST_HOVER_BG,
            dropdown_text_color=TEXT, text_color=TEXT, corner_radius=10, height=46,
        )
        self.model_menu.set(DEFAULT_MODEL)
        self.model_menu.pack(fill="x", padx=24, pady=(0, 6))
        ctk.CTkLabel(
            sidebar,
            text="gemini-3.5-flash-lite is the cheapest option:\nminimal thinking, lowest token usage.",
            text_color=MUTED, font=self.f_small, justify="left",
        ).pack(anchor="w", padx=24, pady=(0, 20))

        self.analyze_button = PlayButton(
            sidebar, text="Analyze Submission", command=self._on_analyze, font=self.f_button, height=56,
        )
        self.analyze_button.pack(fill="x", padx=24, pady=(4, 10))

        status_row = ctk.CTkFrame(sidebar, fg_color="transparent")
        status_row.pack(fill="x", padx=24, pady=(0, 20))
        self.load_spinner = Spinner(status_row, size=13, color=ACCENT, bg=SIDEBAR_BG)
        self.status_label = ctk.CTkLabel(
            status_row, text="", text_color=MUTED, font=self.f_small, wraplength=330, justify="left", anchor="w",
        )
        self.status_label.pack(side="left", fill="x", expand=True)

    def _update_constraint_widget(self, metadata: ProblemMetadata) -> None:
        n = extract_n(metadata.content_text)
        if n is None:
            self.constraint_card.pack_forget()
            return
        safe = [e.label for e in estimate(n) if e.safe]
        text = f"Constraints suggest n ≤ {n:,}.  {recommendation(n)}"
        self.constraint_label.configure(text=text)
        # after= pins it right below the badge regardless of pack call order —
        # a plain pack() would instead re-append it below whatever was packed
        # most recently (Model section, Analyze button, ...).
        self.constraint_card.pack(fill="x", padx=24, pady=(0, 22), after=self.selected_badge_frame)

    def _render_selected_badge(self) -> None:
        for widget in self.selected_badge_frame.winfo_children():
            widget.destroy()
        if self.selected_problem is None:
            ctk.CTkLabel(
                self.selected_badge_frame,
                text="No problem selected, search above.",
                text_color=FAINT, font=self.f_small, wraplength=330, justify="left", anchor="w",
            ).pack(anchor="w", fill="x")
            return
        p = self.selected_problem
        row = ctk.CTkFrame(self.selected_badge_frame, fg_color="transparent")
        row.pack(anchor="w", fill="x")
        check = ctk.CTkLabel(row, text="✓", text_color=LIST_BG, font=self.f_small_bold)
        check.pack(side="left")
        title_label = ctk.CTkLabel(
            row, text=f" {p.frontend_id}. {p.title}", text_color=LIST_BG, font=self.f_small,
        )
        title_label.pack(side="left")
        badge_row2 = ctk.CTkFrame(self.selected_badge_frame, fg_color="transparent")
        badge_row2.pack(anchor="w", fill="x", pady=(6, 0))
        pill = _pill(
            badge_row2, p.difficulty,
            LIST_BG, LIST_BG,
            self.f_pill,
        )
        pill.pack(side="left")
        view_btn = ctk.CTkButton(
            badge_row2, text="View Problem", width=100, height=22, corner_radius=6, font=self.f_small,
            fg_color=LIST_BG, hover_color=HOVER_TINT, text_color=LIST_BG, command=self._show_problem_modal,
        )
        view_btn.pack(side="left", padx=(8, 0))

        diff_color = DIFFICULTY_COLOR.get(p.difficulty, MUTED)
        diff_soft = DIFFICULTY_SOFT.get(p.difficulty, CARD_BG_2)
        pill_label = pill.winfo_children()[0]

        def on_update(t: float) -> None:
            check.configure(text_color=_lerp_color(LIST_BG, GREEN, t))
            title_label.configure(text_color=_lerp_color(LIST_BG, TEXT_DIM, t))
            pill.configure(fg_color=_lerp_color(LIST_BG, diff_soft, t))
            pill_label.configure(text_color=_lerp_color(LIST_BG, diff_color, t))
            view_btn.configure(
                fg_color=_lerp_color(LIST_BG, CARD_BG_2, t), text_color=_lerp_color(LIST_BG, TEXT_DIM, t),
            )

        animate(self.selected_badge_frame, 260, on_update)

    def _show_problem_modal(self) -> None:
        if self.selected_problem is None:
            return
        p = self.selected_problem
        modal = ctk.CTkToplevel(self)
        modal.title(f"{p.frontend_id}. {p.title}")
        modal.geometry("640x640")
        modal.configure(fg_color=BG)
        modal.transient(self)

        header = ctk.CTkFrame(modal, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(20, 10))
        ctk.CTkLabel(
            header, text=f"{p.frontend_id}. {p.title}", font=self.f_card_title, text_color=TEXT,
        ).pack(side="left")
        _pill(
            header, p.difficulty, DIFFICULTY_SOFT.get(p.difficulty, CARD_BG_2),
            DIFFICULTY_COLOR.get(p.difficulty, MUTED), self.f_pill,
        ).pack(side="left", padx=(10, 0))

        scroll = ctk.CTkScrollableFrame(modal, fg_color=BG)
        scroll.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        metadata = self.current_metadata
        if metadata is None or metadata.title_slug != p.title_slug:
            ctk.CTkLabel(
                scroll, text="Still loading the full problem statement, try again in a moment.",
                text_color=MUTED, font=self.f_body,
            ).pack(anchor="w", pady=20)
            return

        if metadata.topic_tags:
            ctk.CTkLabel(
                scroll, text=f"Topics: {', '.join(metadata.topic_tags)}", text_color=MUTED, font=self.f_small,
            ).pack(anchor="w", pady=(0, 14))

        # LeetCode's prose keeps blank-line paragraph breaks even after HTML
        # stripping — render each as its own wrapping label instead of one
        # giant block, so long statements stay readable instead of a wall of text.
        for paragraph in metadata.content_text.split("\n\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            label = ctk.CTkLabel(
                scroll, text=_format_math(paragraph), text_color=TEXT_DIM, font=self.f_body,
                justify="left", anchor="w",
            )
            label.pack(anchor="w", fill="x", pady=(0, 12))
            bind_responsive_wraplength(label, extra_padding=40)

    def _show_onboarding_banner(self, sidebar) -> None:
        banner = ctk.CTkFrame(sidebar, fg_color=ACCENT, corner_radius=10)
        banner.pack(fill="x", padx=24, pady=(0, 20))
        inner = ctk.CTkFrame(banner, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(
            inner, text="New here? The Trace tab lets you step through your own code's "
                        "execution line by line: breakpoints, watches, the works. "
                        "The Tests tab reruns every official example automatically.",
            text_color="#ffffff", font=self.f_small, justify="left", anchor="w", wraplength=330,
        ).pack(anchor="w")
        ctk.CTkButton(
            inner, text="Got it", height=26, width=70, corner_radius=6, fg_color=CARD_BG,
            hover_color=HOVER_TINT, font=self.f_small_bold, text_color=ACCENT,
            command=lambda: self._dismiss_onboarding(banner),
        ).pack(anchor="e", pady=(8, 0))

    def _dismiss_onboarding(self, banner) -> None:
        banner.destroy()
        self.settings = update_settings(onboarded=True)

    def _show_changelog_modal(self) -> None:
        modal = ctk.CTkToplevel(self)
        modal.title("What's New")
        modal.geometry("520x480")
        modal.configure(fg_color=BG)
        modal.transient(self)
        scroll = ctk.CTkScrollableFrame(modal, fg_color=BG)
        scroll.pack(fill="both", expand=True, padx=20, pady=20)
        for section_title, items in CHANGELOG:
            ctk.CTkLabel(scroll, text=section_title, font=self.f_card_title, text_color=TEXT).pack(
                anchor="w", pady=(10, 6)
            )
            for item in items:
                row = ctk.CTkFrame(scroll, fg_color="transparent")
                row.pack(fill="x", pady=2)
                ctk.CTkLabel(row, text="•", text_color=ACCENT, font=self.f_body_bold, width=16).pack(side="left")
                label = ctk.CTkLabel(
                    row, text=item, text_color=TEXT_DIM, font=self.f_small, justify="left", anchor="w",
                )
                label.pack(side="left", fill="x", expand=True)
                bind_responsive_wraplength(label, extra_padding=40)

    _HELP_SECTIONS: list[tuple[str, list[str]]] = [
        ("Tabs", [
            "Editor: paste a solution; live anti-pattern hints, stencils, Socratic hint slider.",
            "Trace: steps your own code line by line: breakpoints, watches, call stack, DP grid.",
            "Tests: reruns every official example plus curated boundary cases and a determinism check.",
            "Report: the full LLM review: complexity, clarity score, redundancies, a refactor, a race.",
            "Skills: a spaced-repetition warmup queue and a topic-by-topic skill map.",
            "Whiteboard: a freehand scratchpad (shapes, text, eraser) plus the floating timer.",
        ]),
        ("Keyboard shortcuts", [
            "Trace tab: Space: play/pause · ←/→: step · Shift+←/→: step out/over",
            "Whiteboard tab: Ctrl+Z: undo · Ctrl+Y: redo",
        ]),
    ]

    def _show_help_modal(self) -> None:
        modal = ctk.CTkToplevel(self)
        modal.title("Help")
        modal.geometry("520x480")
        modal.configure(fg_color=BG)
        modal.transient(self)
        scroll = ctk.CTkScrollableFrame(modal, fg_color=BG)
        scroll.pack(fill="both", expand=True, padx=20, pady=20)
        ctk.CTkLabel(scroll, text=f"How {APP_NAME} works", font=self.f_card_title, text_color=TEXT).pack(
            anchor="w", pady=(0, 10)
        )
        for section_title, items in self._HELP_SECTIONS:
            ctk.CTkLabel(scroll, text=section_title, font=self.f_body_bold, text_color=TEXT).pack(
                anchor="w", pady=(10, 6)
            )
            for item in items:
                row = ctk.CTkFrame(scroll, fg_color="transparent")
                row.pack(fill="x", pady=2)
                ctk.CTkLabel(row, text="•", text_color=ACCENT, font=self.f_body_bold, width=16).pack(side="left")
                label = ctk.CTkLabel(
                    row, text=item, text_color=TEXT_DIM, font=self.f_small, justify="left", anchor="w",
                )
                label.pack(side="left", fill="x", expand=True)
                bind_responsive_wraplength(label, extra_padding=40)

    # --------------------------------------------------------- profiles

    def _current_profile_name(self) -> str:
        if self.active_profile_id == history.GUEST_ID:
            return "Guest"
        match = next((p for p in profiles.load_profiles() if p.id == self.active_profile_id), None)
        return match.name if match else "Unknown"

    def _on_switch_profile_clicked(self) -> None:
        self._show_profile_picker(allow_cancel=True)

    def _on_profile_selected(self, first_launch: bool) -> None:
        self.skills_panel.refresh()
        if first_launch:
            # The window was withdrawn at startup specifically so it stays
            # hidden until a profile is chosen — reveal it now that one has.
            self.deiconify()
            self.lift()
            self.focus_force()
        if first_launch and not self.settings.get("api_key_prompted", False) and not any_key_configured():
            # Delayed so the main window is fully painted first — popping a
            # modal before anything is visible reads as a crash, not a setup step.
            self.after(400, self._show_api_key_setup_modal)

    def _show_profile_picker(self, allow_cancel: bool) -> None:
        """Netflix-style "who's coding" picker. Shown on every launch (not
        just first run — see __init__) and re-openable via the Skills tab's
        Switch Profile button. Profiles are just named pointers to separate
        history.json files (profiles.py); Guest runs entirely in memory, so
        its skill history never touches disk and vanishes when you leave it."""
        profile_list = profiles.load_profiles()
        state = {"mode": "select", "editing_id": None}

        modal = ctk.CTkToplevel(self)
        modal.title("Who's coding?")
        w, h = 780, 560
        self.update_idletasks()
        if self.winfo_viewable():
            origin_x, origin_y = self.winfo_rootx(), self.winfo_rooty()
            origin_w, origin_h = self.winfo_width(), self.winfo_height()
        else:
            # Main window is still withdrawn (startup, before any profile has
            # been picked) — winfo_rootx()/winfo_width() would report a
            # meaningless placeholder size for a never-mapped window.
            origin_w, origin_h, origin_x, origin_y = self._initial_geometry
        x = origin_x + origin_w // 2 - w // 2
        y = origin_y + origin_h // 2 - h // 2
        modal.geometry(f"{w}x{h}+{x}+{y}")
        modal.configure(fg_color=BG)
        modal.transient(self)
        modal.resizable(False, False)
        modal.grab_set()
        if not allow_cancel:
            modal.protocol("WM_DELETE_WINDOW", lambda: None)  # must pick someone to continue

        body = ctk.CTkFrame(modal, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=32, pady=28)
        ctk.CTkLabel(body, text="Who's coding?", font=self.f_title, text_color=TEXT).pack(pady=(4, 6))
        subtitle_label = ctk.CTkLabel(body, text="", text_color=MUTED, font=self.f_small)
        subtitle_label.pack(pady=(0, 22))

        grid_wrap = ctk.CTkFrame(body, fg_color="transparent")
        grid_wrap.pack(expand=True)

        bottom_row = ctk.CTkFrame(body, fg_color="transparent")
        bottom_row.pack(pady=(18, 0))

        def make_avatar(parent, color: str, letter: str, dashed: bool = False, size: int = 84, bg: str = BG) -> tk.Canvas:
            canvas = tk.Canvas(parent, width=size, height=size, bg=bg, highlightthickness=0)
            if dashed:
                canvas.create_oval(2, 2, size - 2, size - 2, outline=color, width=2, dash=(4, 3))
            else:
                canvas.create_oval(2, 2, size - 2, size - 2, fill=color, outline="")
            canvas.create_text(
                size / 2, size / 2, text=letter, fill=(color if dashed else "#0c0d11"),
                font=(HEADING_FAMILY_SEMIBOLD, int(size * 0.38)),
            )
            return canvas

        def select_profile(profile_id: str) -> None:
            history.set_active_profile(profile_id)
            was_first_launch = not getattr(self, "_profile_picked_once", False)
            self._profile_picked_once = True
            self.active_profile_id = profile_id
            modal.grab_release()
            modal.destroy()
            self._on_profile_selected(was_first_launch)

        def cancel_picker() -> None:
            modal.grab_release()
            modal.destroy()

        def refresh_profiles() -> None:
            profile_list[:] = profiles.load_profiles()

        def render() -> None:
            for child in grid_wrap.winfo_children():
                child.destroy()
            manage_btn.configure(text="Done" if state["mode"] == "manage" else "Manage Profiles")
            subtitle_label.configure(text={
                "select": "Click a profile to continue.",
                "manage": "Rename or remove a profile.",
                "add": "", "rename": "",
            }[state["mode"]])

            row = ctk.CTkFrame(grid_wrap, fg_color="transparent")
            row.pack()

            if state["mode"] in ("add", "rename"):
                editing = state["mode"] == "rename"
                p = next((p for p in profile_list if p.id == state["editing_id"]), None) if editing else None
                if editing and p is None:
                    state["mode"] = "manage"
                    render()
                    return
                form = ctk.CTkFrame(row, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
                form.pack(padx=10, pady=10)
                inner = ctk.CTkFrame(form, fg_color="transparent")
                inner.pack(padx=28, pady=28)
                avatar_color = p.color if p else ACCENT
                avatar_letter = (p.name[:1].upper() if p and p.name else "?") if editing else "+"
                make_avatar(inner, avatar_color, avatar_letter, bg=CARD_BG).pack(pady=(0, 14))
                entry = ctk.CTkEntry(
                    inner, width=220, height=34, font=self.f_body, fg_color=CARD_BG_2, border_color=BORDER,
                    text_color=TEXT, placeholder_text="" if editing else "Profile name",
                )
                if editing:
                    entry.insert(0, p.name)
                    entry.select_range(0, "end")
                entry.pack(pady=(0, 12))
                entry.focus_set()

                def submit(_e=None, entry=entry, editing=editing, pid=(p.id if p else None)) -> None:
                    name = entry.get().strip()[:24]
                    if not name:
                        return
                    if editing:
                        profiles.rename_profile(pid, name)
                        state["mode"] = "manage"
                        state["editing_id"] = None
                    else:
                        profiles.create_profile(name)
                        state["mode"] = "select"
                    refresh_profiles()
                    render()

                def do_cancel_form() -> None:
                    state["mode"] = "manage" if editing else "select"
                    state["editing_id"] = None
                    render()

                entry.bind("<Return>", submit)
                btn_row = ctk.CTkFrame(inner, fg_color="transparent")
                btn_row.pack()
                ctk.CTkButton(
                    btn_row, text="Save" if editing else "Create", width=90, height=32, corner_radius=8,
                    fg_color=ACCENT, hover_color=ACCENT_HOVER, font=self.f_small_bold, command=submit,
                ).pack(side="left", padx=(0, 8))
                ctk.CTkButton(
                    btn_row, text="Cancel", width=90, height=32, corner_radius=8, fg_color=CARD_BG_2,
                    hover_color=HOVER_TINT, text_color=TEXT_DIM, font=self.f_small, command=do_cancel_form,
                ).pack(side="left")
                return

            for p in profile_list:
                tile = ctk.CTkFrame(row, fg_color="transparent", width=150)
                tile.pack(side="left", padx=10, pady=6)
                avatar = make_avatar(tile, p.color, (p.name[:1].upper() if p.name else "?"))
                avatar.pack()
                name_label = ctk.CTkLabel(tile, text=p.name, text_color=TEXT_DIM, font=self.f_small, width=150)
                name_label.pack(pady=(8, 0))
                if state["mode"] == "select":
                    for w_ in (tile, avatar, name_label):
                        w_.bind("<Button-1>", lambda e, pid=p.id: select_profile(pid))
                    avatar.configure(cursor="hand2")
                else:
                    icon_row = ctk.CTkFrame(tile, fg_color="transparent")
                    icon_row.pack(pady=(6, 0))
                    ctk.CTkButton(
                        icon_row, text="✎", width=32, height=26, corner_radius=6, fg_color=CARD_BG_2,
                        hover_color=HOVER_TINT, text_color=TEXT_DIM, font=self.f_small,
                        command=lambda pid=p.id: (state.update(mode="rename", editing_id=pid), render()),
                    ).pack(side="left", padx=(0, 6))
                    can_delete = len(profile_list) > 1
                    ctk.CTkButton(
                        icon_row, text="🗑", width=32, height=26, corner_radius=6, fg_color=CARD_BG_2,
                        hover_color=DANGER_HOVER if can_delete else CARD_BG_2,
                        text_color=TEXT_DIM if can_delete else FAINT, font=self.f_small,
                        state="normal" if can_delete else "disabled",
                        command=(lambda pid=p.id: (profiles.delete_profile(pid), refresh_profiles(), render()))
                        if can_delete else None,
                    ).pack(side="left")

            if state["mode"] == "select":
                add_tile = ctk.CTkFrame(row, fg_color="transparent", width=150)
                add_tile.pack(side="left", padx=10, pady=6)
                add_avatar = make_avatar(add_tile, MUTED, "+", dashed=True)
                add_avatar.pack()
                add_avatar.configure(cursor="hand2")
                add_label = ctk.CTkLabel(add_tile, text="Add Profile", text_color=MUTED, font=self.f_small)
                add_label.pack(pady=(8, 0))
                for w_ in (add_avatar, add_label):
                    w_.bind("<Button-1>", lambda e: (state.update(mode="add"), render()))

                # Not a tile like the others on purpose — Guest isn't a
                # profile you create, just small text below the row of
                # profile icons rather than another icon alongside them.
                guest_row = ctk.CTkFrame(grid_wrap, fg_color="transparent")
                guest_row.pack(pady=(18, 0))
                guest_label = ctk.CTkLabel(
                    guest_row, text="Continue as Guest", text_color=TEXT_DIM, font=self.f_small, cursor="hand2",
                )
                guest_label.pack()
                guest_sub = ctk.CTkLabel(guest_row, text="Skills not saved", text_color=FAINT, font=self.f_small)
                guest_sub.pack()
                for w_ in (guest_row, guest_label, guest_sub):
                    w_.bind("<Button-1>", lambda e: select_profile(history.GUEST_ID))

        def toggle_manage() -> None:
            state["mode"] = "select" if state["mode"] == "manage" else "manage"
            render()

        manage_btn = ctk.CTkButton(
            bottom_row, text="Manage Profiles", width=170, height=34, corner_radius=8, fg_color="transparent",
            border_width=1, border_color=BORDER, hover_color=CARD_BG_2, text_color=TEXT_DIM, font=self.f_small,
            command=toggle_manage,
        )
        manage_btn.pack(side="left", padx=(0, 10) if allow_cancel else 0)
        if allow_cancel:
            ctk.CTkButton(
                bottom_row, text="Cancel", width=100, height=34, corner_radius=8, fg_color="transparent",
                border_width=1, border_color=BORDER, hover_color=CARD_BG_2, text_color=TEXT_DIM,
                font=self.f_small, command=cancel_picker,
            ).pack(side="left")

        render()

    def _show_api_key_setup_modal(self) -> None:
        modal = ctk.CTkToplevel(self)
        modal.title("Connect an API Key")
        modal.geometry("460x420")
        modal.configure(fg_color=BG)
        modal.transient(self)
        modal.grab_set()  # first-run setup — hold focus until the user picks Continue or Skip

        body = ctk.CTkFrame(modal, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=24)

        ctk.CTkLabel(body, text="Connect an API key", font=self.f_card_title, text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(
            body, text="This app uses an LLM to review your submissions. Pick a provider and paste "
                       "your key: it's saved locally in a .env file next to the app and sent only "
                       "to that provider's own API, nowhere else.",
            text_color=MUTED, font=self.f_small, justify="left", anchor="w", wraplength=410,
        ).pack(anchor="w", pady=(6, 18))

        ctk.CTkLabel(body, text="Provider", font=self.f_small_bold, text_color=TEXT).pack(anchor="w")
        provider_menu = ctk.CTkOptionMenu(
            body, values=list(PROVIDERS.keys()), font=self.f_body,
            fg_color=CARD_BG, button_color=CARD_BG_2, button_hover_color=HOVER_TINT,
            dropdown_fg_color=CARD_BG_2, dropdown_text_color=TEXT, text_color=TEXT,
        )
        provider_menu.set("Gemini")
        provider_menu.pack(fill="x", pady=(6, 14))

        ctk.CTkLabel(body, text="API Key", font=self.f_small_bold, text_color=TEXT).pack(anchor="w")
        key_row = ctk.CTkFrame(body, fg_color="transparent")
        key_row.pack(fill="x", pady=(6, 4))
        key_entry = ctk.CTkEntry(
            key_row, placeholder_text="Paste your key here", show="•", font=self.f_body,
            fg_color=CARD_BG, border_color=BORDER, text_color=TEXT,
        )
        key_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        reveal_btn = ctk.CTkButton(
            key_row, text="👁", width=36, height=36, corner_radius=8, fg_color=CARD_BG_2,
            hover_color=HOVER_TINT, font=self.f_small,
            command=lambda: key_entry.configure(show="" if key_entry.cget("show") == "•" else "•"),
        )
        reveal_btn.pack(side="left")

        link_label = ctk.CTkLabel(
            body, text="", text_color=ACCENT, font=self.f_small, cursor="hand2", anchor="w",
        )
        link_label.pack(anchor="w", pady=(2, 0))

        def _update_provider_link(*_args) -> None:
            url = PROVIDERS[provider_menu.get()]["signup_url"]
            link_label.configure(text=f"Get a key from {provider_menu.get()} →")
            link_label.unbind("<Button-1>")
            link_label.bind("<Button-1>", lambda e, u=url: self._open_url(u))

        provider_menu.configure(command=_update_provider_link)
        _update_provider_link()

        status_label = ctk.CTkLabel(body, text="", font=self.f_small, anchor="w")
        status_label.pack(anchor="w", pady=(14, 0))

        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.pack(fill="x", side="bottom", pady=(16, 0))

        def _skip() -> None:
            self.settings = update_settings(api_key_prompted=True)
            modal.destroy()

        def _save() -> None:
            key = key_entry.get().strip()
            if not key:
                status_label.configure(text="Enter a key first, or Skip for now.", text_color=RED)
                return
            env_var = PROVIDERS[provider_menu.get()]["env_var"]
            write_key(env_var, key)
            self.settings = update_settings(api_key_prompted=True)
            status_label.configure(text=f"✓ Saved: {provider_menu.get()} is ready to use.", text_color=GREEN)
            modal.after(700, modal.destroy)

        ctk.CTkButton(
            btn_row, text="Skip for now", height=38, corner_radius=8, fg_color="transparent",
            hover_color=CARD_BG_2, text_color=TEXT_DIM, font=self.f_body, command=_skip,
        ).pack(side="left")
        ctk.CTkButton(
            btn_row, text="Save & Continue", height=38, corner_radius=8, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, font=self.f_body_bold, command=_save,
        ).pack(side="right")

        modal.protocol("WM_DELETE_WINDOW", _skip)

    def _open_url(self, url: str) -> None:
        import webbrowser
        webbrowser.open(url)

    def _show_settings_modal(self) -> None:
        modal = ctk.CTkToplevel(self)
        modal.title("Settings")
        modal.geometry("460x680")
        modal.configure(fg_color=BG)
        modal.transient(self)
        modal.grid_columnconfigure(0, weight=1)
        modal.grid_rowconfigure(0, weight=1)

        body = ctk.CTkScrollableFrame(modal, fg_color="transparent")
        body.grid(row=0, column=0, sticky="nswe", padx=24, pady=(24, 0))

        # -- API Keys ---------------------------------------------------------
        ctk.CTkLabel(body, text="API Keys", font=self.f_card_title, text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(
            body, text="Stored locally in a .env file next to the app, never sent\n"
                       "anywhere except that provider's own API.",
            text_color=MUTED, font=self.f_small, justify="left", anchor="w", wraplength=380,
        ).pack(anchor="w", pady=(2, 12))

        key_entries: dict[str, ctk.CTkEntry] = {}
        key_originals: dict[str, str] = {}
        for provider_name, info in PROVIDERS.items():
            env_var = info["env_var"]
            existing = get_key(env_var)
            key_originals[env_var] = existing

            row = ctk.CTkFrame(body, fg_color=CARD_BG_2, corner_radius=8)
            row.pack(fill="x", pady=4)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=10)
            top = ctk.CTkFrame(inner, fg_color="transparent")
            top.pack(fill="x")
            ctk.CTkLabel(top, text=provider_name, text_color=TEXT, font=self.f_small_bold).pack(side="left")
            status_dot_color = GREEN if existing else FAINT
            status_text = "configured" if existing else "not set"
            ctk.CTkLabel(top, text=f"● {status_text}", text_color=status_dot_color, font=self.f_small).pack(
                side="right"
            )

            entry_row = ctk.CTkFrame(inner, fg_color="transparent")
            entry_row.pack(fill="x", pady=(8, 0))
            entry = ctk.CTkEntry(
                entry_row, placeholder_text="Paste key here", show="•", font=self.f_small,
                fg_color=CARD_BG, border_color=BORDER, text_color=TEXT,
            )
            if existing:
                entry.insert(0, existing)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
            ctk.CTkButton(
                entry_row, text="👁", width=32, height=28, corner_radius=6, fg_color=CARD_BG,
                hover_color=HOVER_TINT, font=self.f_small,
                command=lambda e=entry: e.configure(show="" if e.cget("show") == "•" else "•"),
            ).pack(side="left")
            key_entries[env_var] = entry

        api_key_status = ctk.CTkLabel(body, text="", font=self.f_small, anchor="w")
        api_key_status.pack(anchor="w", pady=(6, 20))

        ctk.CTkLabel(body, text="Theme", font=self.f_body_bold, text_color=TEXT).pack(anchor="w")
        theme_menu = ctk.CTkOptionMenu(
            body, values=["Dark", "Light", "High Contrast"], font=self.f_body,
            fg_color=CARD_BG, button_color=CARD_BG_2, button_hover_color=HOVER_TINT,
            dropdown_fg_color=CARD_BG_2, dropdown_text_color=TEXT, text_color=TEXT,
        )
        theme_menu.set({"dark": "Dark", "light": "Light", "high_contrast": "High Contrast"}.get(THEME_MODE, "Dark"))
        theme_menu.pack(fill="x", pady=(6, 4))
        ctk.CTkLabel(
            body, text="Saving a theme change restarts the app automatically to\n"
                       "apply it. Window size/position are kept, but anything\n"
                       "unsaved in the editor is not.",
            text_color=FAINT, font=self.f_small, justify="left", anchor="w",
        ).pack(anchor="w", pady=(0, 16))

        ctk.CTkLabel(body, text="Font Size", font=self.f_body_bold, text_color=TEXT).pack(anchor="w")
        font_scale_var = ctk.DoubleVar(value=FONT_SCALE)
        font_label = ctk.CTkLabel(body, text=f"{int(FONT_SCALE * 100)}%", text_color=MUTED, font=self.f_small)

        def _on_font_slide(v):
            font_label.configure(text=f"{int(float(v) * 100)}%")

        font_slider = ctk.CTkSlider(
            body, from_=0.8, to=1.4, number_of_steps=6, variable=font_scale_var, command=_on_font_slide,
            fg_color=CARD_BG_2, progress_color=ACCENT, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
        )
        font_slider.pack(fill="x", pady=(6, 2))
        font_label.pack(anchor="w")
        ctk.CTkLabel(
            body, text="Also restarts the app to apply.", text_color=FAINT, font=self.f_small, anchor="w",
        ).pack(anchor="w", pady=(0, 16))

        ctk.CTkLabel(body, text="Motion", font=self.f_body_bold, text_color=TEXT).pack(anchor="w", pady=(0, 4))
        reduced_motion_var = ctk.BooleanVar(value=REDUCED_MOTION)

        def _on_toggle_reduced_motion():
            set_reduced_motion(reduced_motion_var.get())  # live — no restart needed

        ctk.CTkSwitch(
            body, text="Reduce motion", variable=reduced_motion_var, command=_on_toggle_reduced_motion,
            font=self.f_small, progress_color=ACCENT, button_color=CARD_BG_2,
        ).pack(anchor="w", pady=(0, 20))

        footer = ctk.CTkFrame(modal, fg_color="transparent")
        footer.grid(row=1, column=0, sticky="we", padx=24, pady=16)

        def _save_and_close():
            changed_keys = []
            for env_var, entry in key_entries.items():
                new_value = entry.get().strip()
                if new_value != key_originals[env_var]:
                    write_key(env_var, new_value)
                    changed_keys.append(env_var)

            theme_key = {"Dark": "dark", "Light": "light", "High Contrast": "high_contrast"}[theme_menu.get()]
            new_font_scale = round(font_scale_var.get(), 2)
            # Theme/font resolve once at process start (see theme.py) — the
            # only way to make a change actually visible is a fresh process.
            needs_restart = theme_key != THEME_MODE or abs(new_font_scale - FONT_SCALE) > 0.001
            update_settings(
                theme=theme_key, font_scale=new_font_scale, reduced_motion=reduced_motion_var.get(),
            )
            if needs_restart:
                api_key_status.configure(text="Restarting to apply your changes...", text_color=ACCENT)
                modal.after(500, self._relaunch_app)
                return
            if changed_keys:
                api_key_status.configure(text=f"✓ Updated: {', '.join(changed_keys)}", text_color=GREEN)
                modal.after(500, modal.destroy)
            else:
                modal.destroy()

        ctk.CTkButton(
            footer, text="Save", height=38, corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=self.f_body_bold, command=_save_and_close,
        ).pack(fill="x")

    def _build_main_area(self) -> None:
        self.tabview = ctk.CTkTabview(
            self, fg_color=BG, corner_radius=12,
            segmented_button_fg_color=CARD_BG, segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_HOVER,
            segmented_button_unselected_color=CARD_BG,
            segmented_button_unselected_hover_color=CARD_BG_2,
            segmented_button_font=self.f_body_bold, text_color=TEXT, command=self._on_tab_changed,
        )
        self.tabview.grid(row=0, column=1, sticky="nswe", padx=22, pady=22)
        # Patch the instance's .set() so the race workaround applies to every
        # caller, not just ones that remember to go through a wrapper —
        # command= (above) only fires for user clicks via the segmented
        # button, never for a programmatic .set() call.
        self._patch_tabview_set()
        editor_tab = self.tabview.add("Editor")
        trace_tab = self.tabview.add("Trace")
        tests_tab = self.tabview.add("Tests")
        report_tab = self.tabview.add("Report")
        skills_tab = self.tabview.add("Skills")
        whiteboard_tab = self.tabview.add("Whiteboard")
        editor_tab.grid_columnconfigure(0, weight=1)
        editor_tab.grid_rowconfigure(1, weight=1)
        trace_tab.grid_columnconfigure(0, weight=1)
        trace_tab.grid_rowconfigure(0, weight=1)
        tests_tab.grid_columnconfigure(0, weight=1)
        tests_tab.grid_rowconfigure(0, weight=1)
        report_tab.grid_columnconfigure(0, weight=1)
        report_tab.grid_rowconfigure(0, weight=1)
        skills_tab.grid_columnconfigure(0, weight=1)
        skills_tab.grid_rowconfigure(0, weight=1)
        whiteboard_tab.grid_columnconfigure(0, weight=1)
        whiteboard_tab.grid_rowconfigure(0, weight=1)

        toolbar = ctk.CTkFrame(editor_tab, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="we", pady=(2, 10))
        self.editor_toolbar_label = ctk.CTkLabel(
            toolbar, text="Paste your Python3 solution.",
            text_color=MUTED, font=self.f_subtitle,
        )
        self.editor_toolbar_label.pack(side="left")

        self.blindfold_var = ctk.BooleanVar(value=False)
        blindfold_switch = ctk.CTkSwitch(
            toolbar, text="Blindfold mode", variable=self.blindfold_var, command=self._on_toggle_blindfold,
            font=self.f_small, progress_color=ACCENT, button_color=CARD_BG_2,
        )
        blindfold_switch.pack(side="right")

        self.stencil_menu = ctk.CTkOptionMenu(
            toolbar, values=["Insert stencil..."] + list(STENCILS.keys()), command=self._on_insert_stencil,
            font=self.f_small, dropdown_font=self.f_small, width=180, height=30,
            fg_color=CARD_BG, button_color=CARD_BG_2, button_hover_color=HOVER_TINT,
            dropdown_fg_color=CARD_BG_2, dropdown_hover_color=LIST_HOVER_BG, dropdown_text_color=TEXT,
            text_color=TEXT_DIM,
        )
        self.stencil_menu.pack(side="right", padx=(0, 14))

        self.hints_button = ctk.CTkButton(
            toolbar, text="Hints", width=70, height=30, corner_radius=8, font=self.f_small,
            fg_color=CARD_BG, hover_color=CARD_BG_2, text_color=TEXT_DIM, command=self._on_toggle_hints,
        )
        self.hints_button.pack(side="right", padx=(0, 8))

        self.refactor_button = ctk.CTkButton(
            toolbar, text="Refactor Selection", width=140, height=30, corner_radius=8, font=self.f_small,
            fg_color=CARD_BG, hover_color=CARD_BG_2, text_color=TEXT_DIM, state="disabled",
            command=self._on_refactor_selection,
        )
        self.refactor_button.pack(side="right", padx=(0, 8))

        self.fuzz_button = ctk.CTkButton(
            toolbar, text="Find Counter-Examples", width=170, height=30, corner_radius=8, font=self.f_small,
            fg_color=CARD_BG, hover_color=CARD_BG_2, text_color=TEXT_DIM, command=self._on_fuzz,
        )
        self.fuzz_button.pack(side="right", padx=(0, 8))

        self.editor = CodeEditor(
            editor_tab, code_font=self.f_code, ui_font=self.f_small,
            on_change=self._on_editor_change, on_selection_change=self._update_refactor_button,
        )
        self.editor.grid(row=1, column=0, sticky="nswe")

        self.lint_panel = ctk.CTkFrame(editor_tab, fg_color=CARD_BG, corner_radius=10, border_width=1, border_color=BORDER)
        self.lint_body = ctk.CTkFrame(self.lint_panel, fg_color="transparent")
        self.lint_body.pack(fill="x", padx=14, pady=10)

        self.hints_panel = ctk.CTkFrame(editor_tab, fg_color=CARD_BG, corner_radius=10, border_width=1, border_color=BORDER)
        hints_inner = ctk.CTkFrame(self.hints_panel, fg_color="transparent")
        hints_inner.pack(fill="x", padx=14, pady=12)
        hints_header = ctk.CTkFrame(hints_inner, fg_color="transparent")
        hints_header.pack(fill="x")
        ctk.CTkLabel(hints_header, text="Socratic Hints", font=self.f_small_bold, text_color=TEXT_DIM).pack(side="left")
        self.hints_tier_label = ctk.CTkLabel(hints_header, text="", font=self.f_small, text_color=MUTED)
        self.hints_tier_label.pack(side="right")
        self.hints_slider = ctk.CTkSlider(
            hints_inner, from_=0, to=4, number_of_steps=4, command=self._on_hints_slider,
            fg_color=CARD_BG_2, progress_color=ACCENT, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
        )
        self.hints_slider.set(0)
        self.hints_slider.pack(fill="x", pady=(10, 10))
        self.hints_text = ctk.CTkLabel(
            hints_inner, text="Move the slider to reveal one hint tier at a time, from a conceptual "
                              "nudge to a near-solution, so you only see as much as you need.",
            font=self.f_small, text_color=TEXT_DIM, justify="left", anchor="w",
        )
        self.hints_text.pack(fill="x", anchor="w")
        bind_responsive_wraplength(self.hints_text)
        self.hints_cache: dict[str, list[str]] = {}
        self.hints_loading = False

        self.fuzz_panel = ctk.CTkFrame(editor_tab, fg_color=CARD_BG, corner_radius=10, border_width=1, border_color=BORDER)
        self.fuzz_body = ctk.CTkFrame(self.fuzz_panel, fg_color="transparent")
        self.fuzz_body.pack(fill="x", padx=14, pady=10)
        self.fuzzing = False

        self.trace_panel = TracePanel(
            trace_tab, self.fonts, self._get_trace_context,
            get_model=self.model_menu.get, get_language=self.language_menu.get,
        )
        self.trace_panel.grid(row=0, column=0, sticky="nswe")

        self.tests_panel = TestsPanel(tests_tab, self.fonts, self._get_trace_context, get_language=self.language_menu.get)
        self.tests_panel.grid(row=0, column=0, sticky="nswe")

        self.results_scroll = ctk.CTkScrollableFrame(
            report_tab, fg_color=BG,
            scrollbar_button_color=SCROLLBAR_THUMB, scrollbar_button_hover_color=SCROLLBAR_THUMB_HOVER,
        )
        self.results_scroll.grid(row=0, column=0, sticky="nswe")
        self.results_scroll.grid_columnconfigure(0, weight=1)

        self.skills_panel = SkillsPanel(
            skills_tab, self.fonts, self._select_problem_and_go,
            on_switch_profile=self._on_switch_profile_clicked, get_profile_name=self._current_profile_name,
        )
        self.skills_panel.grid(row=0, column=0, sticky="nswe")

        self.whiteboard_panel = WhiteboardPanel(whiteboard_tab, self.fonts)
        self.whiteboard_panel.grid(row=0, column=0, sticky="nswe")

        # Floating, not gridded into any tab — a sibling of the tabview,
        # placed on top of it and left there across every tab switch (see
        # floating_timer.py's docstring for why that actually works).
        self.floating_timer = FloatingTimer(self, self.fonts)
        self.floating_timer.place(relx=1.0, rely=1.0, x=-32, y=-32, anchor="se")
        self.floating_timer.lift()

    def _get_trace_context(self) -> tuple[str, ProblemMetadata | None]:
        return self.editor.get_text(), self.current_metadata

    def _on_language_changed(self, language: str) -> None:
        self.editor_toolbar_label.configure(text=f"Paste your {language} solution.")
        is_python = language in ("Python3", "Python")
        # race_button only exists once the Report tab has rendered at least
        # one real (non-Playground) result (it lives inside the dynamically-
        # built results cards, and Playground mode doesn't build one at all).
        buttons = [(self.fuzz_button, "Fuzzing...", "Find Counter-Examples")]
        if hasattr(self, "race_button") and self.race_button.winfo_exists():
            buttons.append((self.race_button, "Racing...", "Run Race"))
        for btn, busy_text, base_text in buttons:
            if btn.cget("text") in (busy_text,):
                continue  # a run is already in flight — let it finish rather than yanking the button
            btn.configure(state="normal" if is_python else "disabled")
            btn.configure(text=base_text if is_python else f"{base_text} (Python only)")

    def _update_provider_note(self) -> None:
        if self.active_provider == "Codeforces":
            self.provider_note.configure(
                text="Codeforces problems are stdin/stdout, not a function to implement. "
                     "Execution Trace, Tests, Fuzz, and the Performance Race won't find a "
                     "matching signature to run. Codeforces also doesn't expose full problem "
                     "statements through its public API, so Report analysis and the problem "
                     "viewer only see the name, rating, and tags, not the full text."
            )
        else:
            self.provider_note.configure(text="")

    def _on_provider_changed(self, provider: str) -> None:
        self.active_provider = provider
        self._update_provider_note()

        self.all_problems = []
        self.filtered_problems = []
        self.selected_problem = None
        self.current_metadata = None
        self._hide_listbox()
        self._render_selected_badge()
        self.constraint_card.pack_forget()
        self.hints_panel.grid_remove()
        self.fuzz_panel.grid_remove()
        self._show_report_placeholder()

        if provider == PLAYGROUND_PROVIDER:
            self._problems_loaded = False
            self.problem_section.pack_forget()
            self.playground_note.pack(anchor="w", padx=24, pady=(0, 20), before=self._language_section_label)
            self._set_status("Playground mode: paste any code and click Analyze.", MUTED)
        else:
            self.playground_note.pack_forget()
            self.problem_section.pack(fill="x", before=self._language_section_label)
            self.problem_entry.configure(state="normal")
            self.problem_entry.delete(0, "end")
            self.problem_entry.configure(state="disabled", placeholder_text="Loading problem list...")
            self._problems_loaded = False
            self._set_status(f"Loading problems from {provider}...", MUTED, busy=True)
            threading.Thread(target=self._load_problem_list, args=(provider,), daemon=True).start()

        self._update_analyze_state()

    def _patch_tabview_set(self) -> None:
        original_set = self.tabview.set

        def patched_set(name: str) -> None:
            original_set(name)
            self._on_tab_changed()

        self.tabview.set = patched_set

    def _on_tab_changed(self) -> None:
        # Work around a CustomTkinter bug: CTkTabview.set() schedules a
        # delayed (100ms) grid_forget of the previously-shown tab. Two set()
        # calls within that window — e.g. this app auto-switching to Report
        # right after a manual switch elsewhere — let a stale forget wipe out
        # whichever tab is actually current by the time it fires, leaving it
        # permanently blank until the user switches away and back. Re-assert
        # the current tab's grid placement just after that window closes.
        self.after(150, self.tabview._set_grid_current_tab)

    def _show_report_placeholder(self) -> None:
        for widget in self.results_scroll.winfo_children():
            widget.destroy()
        wrap = ctk.CTkFrame(self.results_scroll, fg_color="transparent")
        wrap.grid(row=0, column=0, pady=140)
        ctk.CTkLabel(wrap, text="◇", text_color=FAINT, font=ctk.CTkFont(size=34)).pack()
        if self.active_provider == PLAYGROUND_PROVIDER:
            ctk.CTkLabel(
                wrap, text="Paste any code in the Editor tab and click Analyze.\n"
                           "The LLM infers what it does on its own, no problem needed.",
                text_color=MUTED, font=self.f_body, justify="center",
            ).pack(pady=(10, 0))
        else:
            ctk.CTkLabel(
                wrap, text="Pick a problem, paste your solution in the Editor tab,\nand click Analyze Submission.",
                text_color=MUTED, font=self.f_body, justify="center",
            ).pack(pady=(10, 0))
            ctk.CTkLabel(
                wrap, text="Or switch the Provider to Playground to analyze code\nwithout picking a problem.",
                text_color=FAINT, font=self.f_small, justify="center",
            ).pack(pady=(8, 0))

    # ------------------------------------------------------- problem list

    def _load_problem_list(self, provider: str) -> None:
        try:
            problems = self._provider_clients[provider].list_problems()
        except (LeetCodeAPIError, CodeforcesAPIError) as exc:
            self._result_queue.put(("problem_list_error", (provider, str(exc))))
            return
        self._result_queue.put(("problem_list_ready", (provider, problems)))

    def _on_search_keyrelease(self, event=None) -> None:
        self._update_filtered(self.problem_entry.get().strip())

    def _on_search_focus_in(self, event=None) -> None:
        if not self._problems_loaded:
            return
        self.problem_entry.select_range(0, "end")
        self._update_filtered(self.problem_entry.get().strip())

    def _on_search_focus_out(self, event=None) -> None:
        self.after(150, self._restore_entry_if_needed)

    def _on_search_return(self, event=None) -> None:
        if self.filtered_problems:
            self._select_problem(self.filtered_problems[0])

    def _restore_entry_if_needed(self) -> None:
        if self.selected_problem:
            expected = f"{self.selected_problem.frontend_id}. {self.selected_problem.title}"
            if self.problem_entry.get().strip() != expected:
                self.problem_entry.delete(0, "end")
                self.problem_entry.insert(0, expected)
        self._hide_listbox()

    def _update_filtered(self, query: str) -> None:
        if not self._problems_loaded:
            return
        q = query.lower()
        matches: list[ProblemSummary] = []
        if not q:
            matches = self.all_problems[:MAX_SEARCH_RESULTS]
        else:
            digits = q if q.isdigit() else None
            for p in self.all_problems:
                if (digits and p.frontend_id.startswith(digits)) or q in p.title.lower():
                    matches.append(p)
                if len(matches) >= MAX_SEARCH_RESULTS:
                    break
        self.filtered_problems = matches
        self._refresh_listbox()

    def _refresh_listbox(self) -> None:
        for row in self._listbox_rows:
            row.destroy()
        self._listbox_rows = []

        if not self.filtered_problems:
            self._hide_listbox()
            return

        for i, problem in enumerate(self.filtered_problems):
            row = ProblemRow(self.problem_listbox, problem, self._select_problem, self.f_body)
            row.pack(fill="x", pady=2, padx=2)
            row.reveal(delay_ms=min(i, 7) * 22)
            self._listbox_rows.append(row)

        self.problem_listbox.pack(fill="x", padx=24, pady=(8, 0))

    def _hide_listbox(self) -> None:
        self.problem_listbox.pack_forget()

    def _select_problem(self, problem: ProblemSummary) -> None:
        self.selected_problem = problem
        self.current_metadata = None
        self.problem_entry.delete(0, "end")
        self.problem_entry.insert(0, f"{problem.frontend_id}. {problem.title}")
        self._hide_listbox()
        self._render_selected_badge()
        self.constraint_card.pack_forget()
        self.hints_panel.grid_remove()
        self.hints_slider.set(0)
        self.fuzz_panel.grid_remove()
        self.focus_set()
        self._update_analyze_state()
        # Fetch full metadata (incl. example inputs) up front — powers the Trace
        # tab immediately and saves a redundant fetch when Analyze is clicked.
        threading.Thread(
            target=self._fetch_metadata_worker, args=(problem.title_slug, self.problem_client), daemon=True
        ).start()

    def _select_problem_and_go(self, problem: ProblemSummary) -> None:
        """Used by the Skills tab's warmup queue — select a problem and jump to the Editor."""
        self._select_problem(problem)
        self.editor.set_text("")
        self.tabview.set("Editor")

    def _fetch_metadata_worker(self, slug: str, client) -> None:
        try:
            metadata = client.get_problem(slug)
        except (LeetCodeAPIError, CodeforcesAPIError):
            return
        self._result_queue.put(("metadata_ready", metadata))

    # -------------------------------------------------------- editor extras

    def _on_editor_change(self) -> None:
        self._update_analyze_state()
        self._update_lint()

    def _update_lint(self) -> None:
        findings = lint(self.editor.get_text())
        self.editor.set_warning_lines({f.line for f in findings})

        for w in self.lint_body.winfo_children():
            w.destroy()

        if not findings:
            self.lint_panel.grid_remove()
            return

        self.lint_panel.grid(row=2, column=0, sticky="we", pady=(10, 0))
        ctk.CTkLabel(
            self.lint_body, text=f"⚠ {len(findings)} potential anti-pattern{'s' if len(findings) != 1 else ''}",
            text_color=YELLOW, font=self.f_small_bold,
        ).pack(anchor="w")
        for f in findings[:4]:
            row = ctk.CTkFrame(self.lint_body, fg_color="transparent")
            row.pack(fill="x", pady=(4, 0))
            btn = ctk.CTkButton(
                row, text=f"Ln {f.line}", width=54, height=22, corner_radius=6,
                fg_color=CARD_BG_2, hover_color=HOVER_TINT, font=self.f_small,
                command=lambda ln=f.line: self.editor.text.see(f"{ln}.0"),
            )
            btn.pack(side="left", padx=(0, 8))
            ctk.CTkLabel(
                row, text=f"{f.message}  {f.suggestion}", text_color=TEXT_DIM, font=self.f_small,
                anchor="w", justify="left",
            ).pack(side="left", fill="x", expand=True)

    def _on_toggle_blindfold(self) -> None:
        self.editor.set_highlighting_enabled(not self.blindfold_var.get())

    def _on_insert_stencil(self, name: str) -> None:
        if name not in STENCILS:
            return
        self.editor.text.insert("insert", STENCILS[name])
        self.editor._on_key_release()
        self.stencil_menu.set("Insert stencil...")

    # ------------------------------------------------------------- hints

    def _on_toggle_hints(self) -> None:
        if self.hints_panel.winfo_ismapped():
            self.hints_panel.grid_remove()
            return
        if not self.selected_problem:
            self._set_status("Select a problem first to get hints.", RED)
            return
        self.hints_panel.grid(row=3, column=0, sticky="we", pady=(10, 0))
        slug = self.selected_problem.title_slug
        if slug in self.hints_cache:
            self._show_hint_tier(int(self.hints_slider.get()))
            return
        if self.hints_loading:
            return
        metadata = self.current_metadata
        if metadata is None:
            self.hints_text.configure(text="Still loading problem details, try again in a moment.")
            return
        self.hints_loading = True
        self.hints_text.configure(text="Fetching hints...")
        model = self.model_menu.get()
        threading.Thread(target=self._hints_worker, args=(metadata, model), daemon=True).start()

    def _hints_worker(self, metadata: ProblemMetadata, model: str) -> None:
        try:
            hints = generate_hints(metadata, model)
        except AnalyzerError as exc:
            self._result_queue.put(("hints_error", str(exc)))
            return
        self._result_queue.put(("hints_ready", (metadata.title_slug, hints)))

    def _on_hints_slider(self, value: float) -> None:
        self._show_hint_tier(int(round(value)))

    def _show_hint_tier(self, tier: int) -> None:
        slug = self.selected_problem.title_slug if self.selected_problem else None
        hints = self.hints_cache.get(slug) if slug else None
        if hints and tier > 0:
            self.hints_tier_label.configure(text=f"Tier {tier} / 4")
            self.hints_text.configure(text=hints[tier - 1])
            return

        self.hints_tier_label.configure(text="")
        if hints and tier == 0:
            # Bug fix: hints can finish loading while the slider is still at 0 —
            # without this branch the text stayed stuck on "Fetching hints..."
            # forever, only updating once the user happened to move the slider.
            self.hints_text.configure(text="Hints are ready, move the slider to reveal the first one.")
        elif not hints and not self.hints_loading:
            self.hints_text.configure(
                text="Move the slider to reveal one hint tier at a time, from a conceptual\n"
                     "nudge to a near-solution, so you only see as much as you need."
            )

    # --------------------------------------------------------- refactor

    def _update_refactor_button(self) -> None:
        selection = self.editor.get_selection()
        ready = bool(selection and selection.strip()) and self.selected_problem is not None
        self.refactor_button.configure(state="normal" if ready else "disabled")

    def _on_refactor_selection(self) -> None:
        selection = self.editor.get_selection()
        if not selection or not selection.strip():
            return
        full_code = self.editor.get_text()
        model = self.model_menu.get()
        language = self.language_menu.get()
        self.refactor_button.configure(state="disabled", text="Thinking...")
        threading.Thread(
            target=self._refactor_worker, args=(selection, full_code, model, language), daemon=True
        ).start()

    def _refactor_worker(self, selection: str, full_code: str, model: str, language: str) -> None:
        try:
            alternatives = suggest_alternatives(selection, full_code, model, language)
        except AnalyzerError as exc:
            self._result_queue.put(("refactor_error", str(exc)))
            return
        self._result_queue.put(("refactor_ready", (selection, alternatives)))

    def _show_refactor_modal(self, selection: str, alternatives: list[dict]) -> None:
        modal = ctk.CTkToplevel(self)
        modal.title("Refactor Selection")
        modal.geometry("1180x560")
        modal.configure(fg_color=BG)
        modal.transient(self)
        modal.grid_columnconfigure(tuple(range(len(alternatives))), weight=1)
        modal.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            modal, text="Pick a replacement for the selected snippet", font=self.f_card_title, text_color=TEXT,
        ).grid(row=0, column=0, columnspan=max(len(alternatives), 1), sticky="w", padx=20, pady=(18, 10))

        for i, alt in enumerate(alternatives):
            card = ctk.CTkFrame(modal, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
            card.grid(row=1, column=i, sticky="nswe", padx=(20 if i == 0 else 10, 20 if i == len(alternatives) - 1 else 10), pady=(0, 12))
            card.grid_rowconfigure(2, weight=1)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=alt.get("label", f"Option {i+1}"), font=self.f_body_bold, text_color=TEXT).grid(
                row=0, column=0, sticky="w", padx=16, pady=(14, 2)
            )
            ctk.CTkLabel(
                card, text=alt.get("why", ""), font=self.f_small, text_color=MUTED, wraplength=340, justify="left",
            ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 10))
            preview = CodeEditor(card, code_font=self.fonts.code_small, ui_font=self.f_small, read_only=True)
            preview.grid(row=2, column=0, sticky="nswe", padx=16)
            preview.set_text(alt.get("code", ""))
            ctk.CTkButton(
                card, text="Use This", height=34, corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                font=self.f_small_bold, command=lambda code=alt.get("code", ""): self._apply_refactor(code, modal),
            ).grid(row=3, column=0, sticky="we", padx=16, pady=14)

    # ------------------------------------------------------------- fuzz

    def _on_fuzz(self) -> None:
        if self.fuzzing:
            return
        code = self.editor.get_text().strip()
        if not code:
            self._set_status("Paste a solution first.", RED)
            return
        if not self.selected_problem:
            self._set_status("Select a problem first to find counter-examples.", RED)
            return
        if self.current_metadata is None:
            self._set_status("Still loading problem details, try again in a moment.", RED)
            return
        expected_name = self.current_metadata.function_name
        func_name, class_name = find_entry_point(code, expected_name)
        if not func_name:
            self._set_status("Couldn't find a function definition in your code.", RED)
            return

        self.fuzz_panel.grid(row=4, column=0, sticky="we", pady=(10, 0))
        if not can_fuzz(self.current_metadata.param_types):
            self._render_fuzz_result(None, unsupported=True)
            return

        n = extract_n(self.current_metadata.content_text) or 20
        self.fuzzing = True
        self.fuzz_button.configure(text="Fuzzing...", state="disabled")
        for w in self.fuzz_body.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.fuzz_body, text="Searching for crashing / timing-out inputs...",
            text_color=MUTED, font=self.f_small,
        ).pack(anchor="w")
        param_types = self.current_metadata.param_types
        threading.Thread(
            target=self._fuzz_worker, args=(code, func_name, class_name, param_types, n), daemon=True
        ).start()

    def _fuzz_worker(self, code: str, func_name: str, class_name: str | None, param_types: list[str], n: int) -> None:
        result = fuzz(code, func_name, param_types, n_bound=min(n, 200), class_name=class_name)
        self._result_queue.put(("fuzz_done", result))

    def _render_fuzz_result(self, result, unsupported: bool = False) -> None:
        for w in self.fuzz_body.winfo_children():
            w.destroy()
        if unsupported:
            label = ctk.CTkLabel(
                self.fuzz_body, text="This problem's input shape isn't supported for auto-fuzzing yet "
                                     "(only integer/string/boolean/array/2D-array parameters are).",
                text_color=MUTED, font=self.f_small, justify="left", anchor="w",
            )
            label.pack(anchor="w")
            bind_responsive_wraplength(label)
            return
        if result.failure:
            ctk.CTkLabel(
                self.fuzz_body, text=f"⚠ Found a failing input after {result.tested} tries",
                text_color=YELLOW, font=self.f_small_bold,
            ).pack(anchor="w")
            args_repr = ", ".join(repr(a) for a in result.failure.args)
            input_label = ctk.CTkLabel(
                self.fuzz_body, text=f"Input: {args_repr}", text_color=TEXT, font=self.fonts.code_small,
                justify="left", anchor="w",
            )
            input_label.pack(anchor="w", pady=(4, 0))
            bind_responsive_wraplength(input_label)
            error_label = ctk.CTkLabel(
                self.fuzz_body, text=result.failure.error, text_color=RED, font=self.f_small,
                justify="left", anchor="w",
            )
            error_label.pack(anchor="w", pady=(2, 0))
            bind_responsive_wraplength(error_label)
        else:
            note = " (stopped early, time budget reached)" if result.truncated else ""
            ctk.CTkLabel(
                self.fuzz_body, text=f"✓ No crashes or timeouts found in {result.tested} random inputs{note}.",
                text_color=GREEN, font=self.f_small,
            ).pack(anchor="w")

    def _apply_refactor(self, replacement: str, modal) -> None:
        try:
            # Capture the start position before deleting — "sel.*" marks stop
            # resolving the instant the selection is cleared, and the "insert"
            # cursor mark isn't guaranteed to sit at the selection boundary.
            start = self.editor.text.index("sel.first")
            self.editor.text.delete("sel.first", "sel.last")
            self.editor.text.insert(start, replacement)
        except tk.TclError:
            pass
        self.editor._on_key_release()
        modal.destroy()

    # -------------------------------------------------------------- race

    def _on_run_race(self) -> None:
        if self.current_metadata is None:
            self._set_status("Still loading problem details.", RED)
            return
        for w in self.race_body.winfo_children():
            w.destroy()

        # The official example input is tiny (LeetCode keeps examples readable,
        # not perf-representative) — both solutions finish in ~0ms on it, which
        # makes the race meaningless. Generate a larger synthetic input at the
        # problem's own constraint scale instead, when the shape supports it.
        n = min(extract_n(self.current_metadata.content_text) or 1000, 3000)
        param_types = self.current_metadata.param_types
        if can_fuzz(param_types):
            args = generate_case(param_types, n, max_len=n, exact_size=True)
        else:
            args = parse_example_args(self.current_metadata.example_testcases, self.current_metadata.param_names)
        if args is None:
            ctk.CTkLabel(
                self.race_body, text="Couldn't auto-detect example input for this problem.",
                text_color=RED, font=self.f_small,
            ).pack(anchor="w")
            return

        user_code = self.editor.get_text()
        ref_code = self._refactored_code
        expected_name = self.current_metadata.function_name
        self.race_button.configure(state="disabled", text="Racing...")
        ctk.CTkLabel(self.race_body, text="Running both solutions...", text_color=MUTED, font=self.f_small).pack(anchor="w")
        threading.Thread(
            target=self._race_worker, args=(user_code, ref_code, args, expected_name), daemon=True
        ).start()

    def _race_worker(self, user_code: str, ref_code: str, args: list, expected_name: str | None) -> None:
        user_result, ref_result = race(user_code, ref_code, args, expected_name=expected_name)
        self._result_queue.put(("race_done", (user_result, ref_result)))

    def _render_race_result(self, user_result, ref_result) -> None:
        self.race_button.configure(state="normal", text="Run Race")
        for w in self.race_body.winfo_children():
            w.destroy()
        if not user_result.ok:
            label = ctk.CTkLabel(
                self.race_body, text=f"Your code failed to run: {user_result.error}",
                text_color=RED, font=self.f_small, justify="left", anchor="w",
            )
            label.pack(anchor="w")
            bind_responsive_wraplength(label)
            return
        if not ref_result.ok:
            label = ctk.CTkLabel(
                self.race_body, text=f"Refactored code failed to run: {ref_result.error}",
                text_color=RED, font=self.f_small, justify="left", anchor="w",
            )
            label.pack(anchor="w")
            bind_responsive_wraplength(label)
            return

        max_time = max(user_result.elapsed_ms, ref_result.elapsed_ms, 0.001)
        max_mem = max(user_result.peak_kb, ref_result.peak_kb, 0.001)

        def bar_row(label: str, value: float, max_value: float, unit: str, color: str) -> None:
            row = ctk.CTkFrame(self.race_body, fg_color="transparent")
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=label, text_color=TEXT_DIM, font=self.f_small, width=110, anchor="w").pack(side="left")
            bar_bg = ctk.CTkFrame(row, fg_color=CARD_BG_2, height=16, corner_radius=8)
            bar_bg.pack(side="left", fill="x", expand=True, padx=(0, 10))
            frac = max(min(value / max_value, 1.0), 0.02)
            bar_fg = ctk.CTkFrame(bar_bg, fg_color=color, height=16, corner_radius=8)
            bar_fg.place(relx=0, rely=0, relwidth=frac, relheight=1)
            ctk.CTkLabel(row, text=f"{value:.2f} {unit}", text_color=TEXT, font=self.f_small_bold, width=90, anchor="e").pack(side="left")

        ctk.CTkLabel(self.race_body, text="Time", text_color=MUTED, font=self.f_small_bold).pack(anchor="w", pady=(4, 0))
        bar_row("Your code", user_result.elapsed_ms, max_time, "ms", GREEN if user_result.elapsed_ms <= ref_result.elapsed_ms else YELLOW)
        bar_row("Refactored", ref_result.elapsed_ms, max_time, "ms", GREEN if ref_result.elapsed_ms <= user_result.elapsed_ms else YELLOW)
        ctk.CTkLabel(self.race_body, text="Peak Memory", text_color=MUTED, font=self.f_small_bold).pack(anchor="w", pady=(10, 0))
        bar_row("Your code", user_result.peak_kb, max_mem, "KB", GREEN if user_result.peak_kb <= ref_result.peak_kb else YELLOW)
        bar_row("Refactored", ref_result.peak_kb, max_mem, "KB", GREEN if ref_result.peak_kb <= user_result.peak_kb else YELLOW)

    # --------------------------------------------------------- transpile

    def _on_transpile(self) -> None:
        language = self.transpile_lang_menu.get()
        code = self._refactored_code
        source_language = self._refactored_code_language
        model = self.model_menu.get()
        self.transpile_button.configure(state="disabled", text="Translating...")
        for w in self.transpile_body.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.transpile_body, text=f"Translating to {language}...", text_color=MUTED, font=self.f_small).pack(anchor="w")
        threading.Thread(
            target=self._transpile_worker, args=(code, language, model, source_language), daemon=True
        ).start()

    def _transpile_worker(self, code: str, language: str, model: str, source_language: str) -> None:
        try:
            data = transpile(code, language, model, source_language)
        except AnalyzerError as exc:
            self._result_queue.put(("transpile_error", str(exc)))
            return
        self._result_queue.put(("transpile_ready", (language, data)))

    def _render_transpile_result(self, language: str, data: dict) -> None:
        self.transpile_button.configure(state="normal", text="Transpile")
        for w in self.transpile_body.winfo_children():
            w.destroy()
        translated = CodeEditor(self.transpile_body, code_font=self.fonts.code_small, ui_font=self.f_small, read_only=True, height=240)
        translated.pack(fill="both", expand=True, pady=(0, 10))
        translated.set_text(data.get("code", ""), highlight=False)
        notes = data.get("notes", "")
        if notes:
            label = ctk.CTkLabel(
                self.transpile_body, text=notes, text_color=TEXT_DIM, font=self.f_small, justify="left", anchor="w",
            )
            label.pack(anchor="w")
            bind_responsive_wraplength(label)

    # ------------------------------------------------------------ analysis

    def _update_analyze_state(self) -> None:
        code = self.editor.get_text().strip()
        # Playground mode analyzes any code on its own, no problem needed —
        # the other providers still need an actual problem picked first.
        is_playground = self.active_provider == PLAYGROUND_PROVIDER
        ready = bool(code) and (is_playground or self.selected_problem is not None)
        self.analyze_button.set_enabled(ready)

    def _on_analyze(self) -> None:
        code = self.editor.get_text().strip()
        if not code:
            return
        model = self.model_menu.get()
        language = self.language_menu.get()

        self.analyze_button.set_busy(True)
        if self.active_provider != PLAYGROUND_PROVIDER and self.selected_problem:
            self._set_status("Fetching problem statement...", MUTED)
            threading.Thread(
                target=self._worker,
                args=(self.selected_problem.title_slug, code, model, language, self.problem_client),
                daemon=True,
            ).start()
        else:
            self._set_status(f"Analyzing with {model} (Playground mode)...", MUTED)
            threading.Thread(target=self._playground_worker, args=(code, model, language), daemon=True).start()

    def _playground_worker(self, code: str, model: str, language: str) -> None:
        try:
            result = analyze_playground(code, model, language)
        except AnalyzerError as exc:
            self._result_queue.put(("error", str(exc)))
            return
        self._result_queue.put(("playground_done", (result, language)))

    def _worker(self, slug: str, code: str, model: str, language: str, client) -> None:
        metadata = self.current_metadata if self.current_metadata and self.current_metadata.title_slug == slug else None
        if metadata is None:
            try:
                metadata = client.get_problem(slug)
            except (LeetCodeAPIError, CodeforcesAPIError) as exc:
                self._result_queue.put(("error", str(exc)))
                return

        self._result_queue.put(("status", f"Analyzing with {model}..."))

        try:
            result = analyze_submission(metadata, code, model, language)
        except AnalyzerError as exc:
            self._result_queue.put(("error", str(exc)))
            return

        self._result_queue.put(("done", (metadata, result, language)))

    def _poll_queue(self) -> None:
        try:
            kind, payload = self._result_queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_queue)
            return

        if kind == "problem_list_ready":
            provider, problems = payload
            if provider != self.active_provider:
                pass  # a stale response from a provider the user already switched away from
            else:
                self.all_problems = list(problems)
                self._problems_loaded = True
                self.problem_entry.configure(
                    state="normal", placeholder_text="Search by number or title (e.g. 1, Two Sum)..."
                )
                self._set_status(f"Loaded {len(self.all_problems)} problems from {provider}.", MUTED)
                self._update_analyze_state()
        elif kind == "problem_list_error":
            provider, message = payload
            if provider == self.active_provider:
                self._set_status(f"Could not load problem list: {message}", RED)
        elif kind == "metadata_ready":
            if self.selected_problem and payload.title_slug == self.selected_problem.title_slug:
                self.current_metadata = payload
                self._update_constraint_widget(payload)
        elif kind == "status":
            self._set_status(str(payload), MUTED)
        elif kind == "error":
            self._set_status(f"Error: {payload}", RED)
            self.analyze_button.set_busy(False)
            self.analyze_button.flash(False)
        elif kind == "done":
            metadata, result, language = payload
            self._set_status("Done.", GREEN)
            self.analyze_button.set_busy(False)
            self.analyze_button.flash(True)
            self._render_report(metadata, result, language)
            self.tabview.set("Report")
            record_analysis(
                metadata.title_slug, metadata.frontend_id, metadata.title, metadata.difficulty,
                metadata.topic_tags, result.structure_and_clarity_score,
            )
            self.skills_panel.refresh()
            if result.structure_and_clarity_score == 10:
                self.after(600, self._show_confetti)
        elif kind == "playground_done":
            result, language = payload
            self._set_status("Done.", GREEN)
            self.analyze_button.set_busy(False)
            self.analyze_button.flash(True)
            self._render_playground_report(result, language)
            self.tabview.set("Report")
            if result.structure_and_clarity_score == 10:
                self.after(600, self._show_confetti)
        elif kind == "hints_ready":
            slug, hints = payload
            self.hints_cache[slug] = hints
            self.hints_loading = False
            if self.selected_problem and self.selected_problem.title_slug == slug:
                # Asking for hints was already an intentional request for help —
                # jump straight to tier 1 instead of leaving the slider at 0
                # (which used to just sit on "Fetching hints..." forever).
                tier = int(self.hints_slider.get()) or 1
                self.hints_slider.set(tier)
                self._show_hint_tier(tier)
        elif kind == "hints_error":
            self.hints_loading = False
            self.hints_text.configure(text=f"Could not fetch hints: {payload}")
        elif kind == "refactor_ready":
            selection, alternatives = payload
            self.refactor_button.configure(text="Refactor Selection")
            self._update_refactor_button()
            self._show_refactor_modal(selection, alternatives)
        elif kind == "refactor_error":
            self.refactor_button.configure(text="Refactor Selection")
            self._update_refactor_button()
            self._set_status(f"Refactor suggestion failed: {payload}", RED)
        elif kind == "fuzz_done":
            self.fuzzing = False
            self.fuzz_button.configure(text="Find Counter-Examples", state="normal")
            self._render_fuzz_result(payload)
        elif kind == "race_done":
            user_result, ref_result = payload
            self._render_race_result(user_result, ref_result)
        elif kind == "transpile_ready":
            language, data = payload
            self._render_transpile_result(language, data)
        elif kind == "transpile_error":
            self.transpile_button.configure(state="normal", text="Transpile")
            for w in self.transpile_body.winfo_children():
                w.destroy()
            label = ctk.CTkLabel(
                self.transpile_body, text=f"Translation failed: {payload}", text_color=RED, font=self.f_small,
                justify="left", anchor="w",
            )
            label.pack(anchor="w")
            bind_responsive_wraplength(label)

        self.after(100, self._poll_queue)

    # ------------------------------------------------------------ render

    def _card(self, parent, delay_ms: int = 0) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=BG, corner_radius=12, border_width=1, border_color=BG)
        card.grid(sticky="we", pady=(14, 16))
        self._reveal_frame(card, delay_ms, target_fg=CARD_BG, target_border=BORDER)
        return card

    def _reveal_frame(
        self, frame: ctk.CTkFrame, delay_ms: int = 0, target_fg: str = CARD_BG, target_border: str = BORDER,
    ) -> None:
        # NOTE: only ever reconfigure padding via the SAME geometry manager the
        # widget is already placed with — calling grid_configure on a pack-managed
        # widget silently switches its manager and can unmap it (and vice versa).
        manager = frame.winfo_manager()

        def start() -> None:
            if not frame.winfo_exists():
                return

            def on_update(t: float) -> None:
                if not frame.winfo_exists():
                    return
                frame.configure(fg_color=_lerp_color(BG, target_fg, t), border_color=_lerp_color(BG, target_border, t))
                pad_top = round(_lerp(14, 0, t))
                if manager == "grid":
                    frame.grid_configure(pady=(pad_top, 16))
                elif manager == "pack":
                    frame.pack_configure(pady=(pad_top, 16))

            animate(frame, 320, on_update)

        self.after(delay_ms, start)

    def _render_report(self, problem: ProblemMetadata, result: ReviewResult, language: str = "Python3") -> None:
        for widget in self.results_scroll.winfo_children():
            widget.destroy()

        row = 0
        header = self._card(self.results_scroll, 0)
        header.grid(row=row, column=0)
        top = ctk.CTkFrame(header, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(18, 4))
        ctk.CTkLabel(
            top, text=f"{problem.frontend_id}. {problem.title}", font=self.f_card_title, text_color=TEXT,
        ).pack(side="left")
        _pill(
            top, problem.difficulty, DIFFICULTY_SOFT.get(problem.difficulty, CARD_BG_2),
            DIFFICULTY_COLOR.get(problem.difficulty, MUTED), self.f_pill,
        ).pack(side="left", padx=(10, 0))
        ctk.CTkLabel(
            header, text=f"Topics: {', '.join(problem.topic_tags) or 'n/a'}", text_color=MUTED, font=self.f_small,
        ).pack(anchor="w", padx=20, pady=(0, 18))
        row += 1

        complexity_card = self._card(self.results_scroll, 70)
        complexity_card.grid(row=row, column=0)
        complexity_card.grid_columnconfigure((0, 1, 2), weight=1)
        ctk.CTkLabel(
            complexity_card, text="Complexity Analysis", font=self.f_card_title, text_color=TEXT,
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=20, pady=(18, 12))
        ctk.CTkLabel(complexity_card, text="", text_color=MUTED, font=self.f_small).grid(
            row=1, column=0, sticky="w", padx=20
        )
        ctk.CTkLabel(complexity_card, text="Your submission", text_color=MUTED, font=self.f_small).grid(
            row=1, column=1, sticky="w", padx=8
        )
        ctk.CTkLabel(complexity_card, text="Optimal", text_color=MUTED, font=self.f_small).grid(
            row=1, column=2, sticky="w", padx=8
        )
        self._complexity_row(complexity_card, 2, "Time", result.user_time_complexity, result.optimal_time_complexity)
        self._complexity_row(complexity_card, 3, "Space", result.user_space_complexity, result.optimal_space_complexity)
        ctk.CTkLabel(complexity_card, text="", height=10).grid(row=4, column=0)
        row += 1

        score = result.structure_and_clarity_score
        score_color = GREEN if score >= 8 else YELLOW if score >= 5 else RED
        clarity_card = self._card(self.results_scroll, 140)
        clarity_card.grid(row=row, column=0)
        clarity_inner = ctk.CTkFrame(clarity_card, fg_color="transparent")
        clarity_inner.pack(fill="x", padx=20, pady=18)
        gauge = tk.Canvas(clarity_inner, width=92, height=92, bg=CARD_BG, highlightthickness=0)
        gauge.pack(side="left", padx=(0, 20))
        _draw_score_gauge(gauge, 0, score_color, self.f_score, self.f_small)
        self.after(220, lambda: animate(
            gauge, 700, lambda t: _draw_score_gauge(gauge, score * t, score_color, self.f_score, self.f_small)
        ))
        text_wrap = ctk.CTkFrame(clarity_inner, fg_color="transparent")
        text_wrap.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(text_wrap, text="Structure & Clarity", font=self.f_card_title, text_color=TEXT).pack(anchor="w")
        clarity_label = ctk.CTkLabel(
            text_wrap, text=_format_math(result.structure_and_clarity_commentary), text_color=TEXT_DIM,
            font=self.f_body, justify="left", anchor="w",
        )
        clarity_label.pack(anchor="w", pady=(6, 0), fill="x")
        bind_responsive_wraplength(clarity_label)
        row += 1

        redundancy_card = self._card(self.results_scroll, 210)
        redundancy_card.grid(row=row, column=0)
        ctk.CTkLabel(
            redundancy_card, text="Redundancies & Suboptimal Choices", font=self.f_card_title, text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(18, 10))
        if result.redundancies:
            for item in result.redundancies:
                bullet = ctk.CTkFrame(redundancy_card, fg_color="transparent")
                bullet.pack(fill="x", padx=20, pady=3)
                ctk.CTkLabel(bullet, text="•", text_color=YELLOW, font=self.f_body_bold, width=16).pack(side="left")
                item_label = ctk.CTkLabel(
                    bullet, text=_format_math(item), text_color=TEXT_DIM, font=self.f_body, justify="left", anchor="w",
                )
                item_label.pack(side="left", fill="x", expand=True)
                bind_responsive_wraplength(item_label, extra_padding=40)
        else:
            ctk.CTkLabel(redundancy_card, text="No redundancies detected.", text_color=GREEN, font=self.f_body).pack(
                anchor="w", padx=20
            )
        ctk.CTkLabel(redundancy_card, text="", height=8).pack()
        row += 1

        code_card = ctk.CTkFrame(self.results_scroll, fg_color="transparent")
        code_card.grid(row=row, column=0, sticky="we", pady=(0, 16))
        ctk.CTkLabel(code_card, text="Refactored Solution", font=self.f_card_title, text_color=TEXT).pack(
            anchor="w", pady=(0, 10)
        )
        refactored_editor = CodeEditor(
            code_card, code_font=self.f_code, ui_font=self.f_small, read_only=True, height=320,
        )
        refactored_editor.pack(fill="both", expand=True)
        refactored_editor.set_text(result.refactored_code)
        self._reveal_frame(refactored_editor, 280, target_fg=EDITOR_CHROME, target_border=BORDER)
        row += 1

        self._refactored_code = result.refactored_code
        self._refactored_code_language = language
        self.race_card = self._card(self.results_scroll, 340)
        self.race_card.grid(row=row, column=0)
        race_header = ctk.CTkFrame(self.race_card, fg_color="transparent")
        race_header.pack(fill="x", padx=20, pady=(18, 4))
        ctk.CTkLabel(race_header, text="Performance Race", font=self.f_card_title, text_color=TEXT).pack(side="left")
        self.race_button = ctk.CTkButton(
            race_header, text="Run Race", height=32, corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=self.f_small_bold, command=self._on_run_race,
        )
        self.race_button.pack(side="right")
        ctk.CTkLabel(
            self.race_card, text="Runs your current editor code and the refactored suggestion on a large "
                                  "synthetic input at the problem's own scale, timing both for real.",
            text_color=MUTED, font=self.f_small,
        ).pack(anchor="w", padx=20, pady=(0, 10))
        self.race_body = ctk.CTkFrame(self.race_card, fg_color="transparent")
        self.race_body.pack(fill="x", padx=20, pady=(0, 18))
        row += 1

        self._build_transpile_card(row, language)

        # race_button was just (re)created above — apply the current
        # language's Python-only gating to it immediately, rather than
        # waiting for the next time the user touches the language menu.
        self._on_language_changed(self.language_menu.get())

    def _build_transpile_card(self, row: int, language: str) -> None:
        self.transpile_card = self._card(self.results_scroll, 400)
        self.transpile_card.grid(row=row, column=0)
        transpile_header = ctk.CTkFrame(self.transpile_card, fg_color="transparent")
        transpile_header.pack(fill="x", padx=20, pady=(18, 4))
        ctk.CTkLabel(transpile_header, text="Transpilation Inspector", font=self.f_card_title, text_color=TEXT).pack(side="left")
        transpile_targets = [l for l in LEETCODE_LANGUAGES if l not in (language, "Python3", "Python")]
        self.transpile_lang_menu = ctk.CTkOptionMenu(
            transpile_header, values=transpile_targets, width=120, height=30,
            font=self.f_small, dropdown_font=self.f_small, fg_color=CARD_BG_2, button_color=CARD_BG_2,
            button_hover_color=HOVER_TINT, dropdown_fg_color=CARD_BG_2, dropdown_hover_color=LIST_HOVER_BG,
            dropdown_text_color=TEXT, text_color=TEXT,
        )
        self.transpile_lang_menu.set(transpile_targets[0] if transpile_targets else "")
        self.transpile_lang_menu.pack(side="right", padx=(0, 8))
        self.transpile_button = ctk.CTkButton(
            transpile_header, text="Transpile", height=32, corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=self.f_small_bold, command=self._on_transpile,
        )
        self.transpile_button.pack(side="right", padx=(0, 8))
        ctk.CTkLabel(
            self.transpile_card, text="LLM-translated for comparison, not compiled or benchmarked, "
                                       "so treat it as a reference, not verified output.",
            text_color=MUTED, font=self.f_small,
        ).pack(anchor="w", padx=20, pady=(0, 10))
        self.transpile_body = ctk.CTkFrame(self.transpile_card, fg_color="transparent")
        self.transpile_body.pack(fill="both", expand=True, padx=20, pady=(0, 18))

    def _render_playground_report(self, result: PlaygroundResult, language: str = "Python3") -> None:
        """Same report layout as _render_report, minus anything that needs a
        known LeetCode problem: no title/difficulty/topics header, no
        "optimal" complexity column (there's no known-optimal target without
        a problem statement), and no Performance Race (needs a known
        function signature and problem-scale input to generate)."""
        for widget in self.results_scroll.winfo_children():
            widget.destroy()

        row = 0
        header = self._card(self.results_scroll, 0)
        header.grid(row=row, column=0)
        ctk.CTkLabel(header, text="Playground Analysis", font=self.f_card_title, text_color=TEXT).pack(
            anchor="w", padx=20, pady=(18, 4)
        )
        ctk.CTkLabel(
            header, text=f"No LeetCode problem selected, analyzed as standalone {language} code.",
            text_color=MUTED, font=self.f_small,
        ).pack(anchor="w", padx=20)
        purpose_label = ctk.CTkLabel(
            header, text=_format_math(result.inferred_purpose), text_color=TEXT_DIM, font=self.f_body,
            justify="left", anchor="w",
        )
        purpose_label.pack(anchor="w", padx=20, pady=(8, 18), fill="x")
        bind_responsive_wraplength(purpose_label)
        row += 1

        complexity_card = self._card(self.results_scroll, 70)
        complexity_card.grid(row=row, column=0)
        ctk.CTkLabel(
            complexity_card, text="Complexity Analysis", font=self.f_card_title, text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(18, 12))
        for label, assessment in (("Time", result.time_complexity), ("Space", result.space_complexity)):
            row_frame = ctk.CTkFrame(complexity_card, fg_color="transparent")
            row_frame.pack(fill="x", padx=20, pady=6)
            ctk.CTkLabel(
                row_frame, text=label, text_color=TEXT_DIM, font=self.f_body_bold, width=60, anchor="w",
            ).pack(side="left")
            col = ctk.CTkFrame(row_frame, fg_color="transparent")
            col.pack(side="left", fill="x", expand=True)
            _pill(col, _format_math(assessment.big_o), CARD_BG_2, TEXT, self.f_pill).pack(anchor="w")
            just_label = ctk.CTkLabel(
                col, text=_format_math(assessment.justification), text_color=MUTED, font=self.f_small,
                justify="left", anchor="w",
            )
            just_label.pack(anchor="w", pady=(5, 0), fill="x")
            bind_responsive_wraplength(just_label)
        ctk.CTkLabel(complexity_card, text="", height=8).pack()
        row += 1

        score = result.structure_and_clarity_score
        score_color = GREEN if score >= 8 else YELLOW if score >= 5 else RED
        clarity_card = self._card(self.results_scroll, 140)
        clarity_card.grid(row=row, column=0)
        clarity_inner = ctk.CTkFrame(clarity_card, fg_color="transparent")
        clarity_inner.pack(fill="x", padx=20, pady=18)
        gauge = tk.Canvas(clarity_inner, width=92, height=92, bg=CARD_BG, highlightthickness=0)
        gauge.pack(side="left", padx=(0, 20))
        _draw_score_gauge(gauge, 0, score_color, self.f_score, self.f_small)
        self.after(220, lambda: animate(
            gauge, 700, lambda t: _draw_score_gauge(gauge, score * t, score_color, self.f_score, self.f_small)
        ))
        text_wrap = ctk.CTkFrame(clarity_inner, fg_color="transparent")
        text_wrap.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(text_wrap, text="Structure & Clarity", font=self.f_card_title, text_color=TEXT).pack(anchor="w")
        clarity_label = ctk.CTkLabel(
            text_wrap, text=_format_math(result.structure_and_clarity_commentary), text_color=TEXT_DIM,
            font=self.f_body, justify="left", anchor="w",
        )
        clarity_label.pack(anchor="w", pady=(6, 0), fill="x")
        bind_responsive_wraplength(clarity_label)
        row += 1

        redundancy_card = self._card(self.results_scroll, 210)
        redundancy_card.grid(row=row, column=0)
        ctk.CTkLabel(
            redundancy_card, text="Redundancies & Suboptimal Choices", font=self.f_card_title, text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(18, 10))
        if result.redundancies:
            for item in result.redundancies:
                bullet = ctk.CTkFrame(redundancy_card, fg_color="transparent")
                bullet.pack(fill="x", padx=20, pady=3)
                ctk.CTkLabel(bullet, text="•", text_color=YELLOW, font=self.f_body_bold, width=16).pack(side="left")
                item_label = ctk.CTkLabel(
                    bullet, text=_format_math(item), text_color=TEXT_DIM, font=self.f_body, justify="left", anchor="w",
                )
                item_label.pack(side="left", fill="x", expand=True)
                bind_responsive_wraplength(item_label, extra_padding=40)
        else:
            ctk.CTkLabel(redundancy_card, text="No redundancies detected.", text_color=GREEN, font=self.f_body).pack(
                anchor="w", padx=20
            )
        ctk.CTkLabel(redundancy_card, text="", height=8).pack()
        row += 1

        code_card = ctk.CTkFrame(self.results_scroll, fg_color="transparent")
        code_card.grid(row=row, column=0, sticky="we", pady=(0, 16))
        ctk.CTkLabel(code_card, text="Refactored Solution", font=self.f_card_title, text_color=TEXT).pack(
            anchor="w", pady=(0, 10)
        )
        refactored_editor = CodeEditor(
            code_card, code_font=self.f_code, ui_font=self.f_small, read_only=True, height=320,
        )
        refactored_editor.pack(fill="both", expand=True)
        refactored_editor.set_text(result.refactored_code)
        self._reveal_frame(refactored_editor, 280, target_fg=EDITOR_CHROME, target_border=BORDER)
        row += 1

        self._refactored_code = result.refactored_code
        self._refactored_code_language = language

        race_note = self._card(self.results_scroll, 340)
        race_note.grid(row=row, column=0)
        ctk.CTkLabel(race_note, text="Performance Race", font=self.f_card_title, text_color=TEXT).pack(
            anchor="w", padx=20, pady=(18, 4)
        )
        race_note_label = ctk.CTkLabel(
            race_note, text="Not available in Playground mode: the Race needs a known function signature "
                            "and problem-scale test input, which only come from a selected LeetCode problem.",
            text_color=MUTED, font=self.f_small, justify="left", anchor="w",
        )
        race_note_label.pack(anchor="w", padx=20, pady=(0, 18), fill="x")
        bind_responsive_wraplength(race_note_label)
        row += 1

        self._build_transpile_card(row, language)
        self._on_language_changed(self.language_menu.get())

    def _complexity_row(self, parent: ctk.CTkFrame, grid_row: int, label: str, user, optimal) -> None:
        match = _normalize_big_o(user.big_o) == _normalize_big_o(optimal.big_o)
        color = GREEN if match else YELLOW
        soft = GREEN_SOFT if match else YELLOW_SOFT

        ctk.CTkLabel(parent, text=label, text_color=TEXT_DIM, font=self.f_body_bold).grid(
            row=grid_row, column=0, sticky="nw", padx=20, pady=8
        )

        user_frame = ctk.CTkFrame(parent, fg_color="transparent")
        user_frame.grid(row=grid_row, column=1, sticky="nwe", padx=8, pady=8)
        _pill(user_frame, _format_math(user.big_o), soft, color, self.f_pill).pack(anchor="w")
        ctk.CTkLabel(
            user_frame, text=_format_math(user.justification), text_color=MUTED, font=self.f_small,
            wraplength=320, justify="left",
        ).pack(anchor="w", pady=(5, 0))

        optimal_frame = ctk.CTkFrame(parent, fg_color="transparent")
        optimal_frame.grid(row=grid_row, column=2, sticky="nwe", padx=8, pady=8)
        _pill(optimal_frame, _format_math(optimal.big_o), CARD_BG_2, TEXT, self.f_pill).pack(anchor="w")
        ctk.CTkLabel(
            optimal_frame, text=_format_math(optimal.justification), text_color=MUTED, font=self.f_small,
            wraplength=320, justify="left",
        ).pack(anchor="w", pady=(5, 0))


def main() -> None:
    app = AnalyzerApp()
    app.mainloop()


if __name__ == "__main__":
    main()

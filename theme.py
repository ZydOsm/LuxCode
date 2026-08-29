"""Shared design system: colors, fonts, animation helpers, and small reusable
widgets used across the main app and every feature panel."""

from __future__ import annotations

import math
import re
import time
import tkinter as tk

import customtkinter as ctk

from settings import load_settings

# ---------------------------------------------------------------- design tokens
#
# Theme selection resolves ONCE, here, at import time — not live. Every other
# module in this app does `from theme import BG, ACCENT, ...` at ITS OWN
# import time, which binds a plain string into that module's namespace;
# nothing here can reach back into gui.py/panel_trace.py/etc. later and
# change what those names point to. So a theme switch takes effect on next
# launch (settings.py persists the choice), not mid-session. The one
# exception is REDUCED_MOTION, further down — see set_reduced_motion().

_PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "BG": "#0c0d11", "SIDEBAR_BG": "#121319", "CARD_BG": "#181a21", "CARD_BG_2": "#1e202a",
        "LIST_BG": "#1c1e26", "LIST_HOVER_BG": "#262835", "EDITOR_BG": "#0e0f13", "EDITOR_CHROME": "#15161d",
        "BORDER": "#25272f",
        "TEXT": "#eef0f4", "TEXT_DIM": "#a8abb8", "MUTED": "#787c8a", "FAINT": "#4b4e5c",
        "ACCENT": "#6e6bf5", "ACCENT_HOVER": "#8582fb", "ACCENT_SOFT": "#211f3c",
        "DISABLED_BG": "#23242c", "DISABLED_ICON": "#5b5e6a",
        "GREEN": "#3ecf8e", "GREEN_SOFT": "#12291f", "YELLOW": "#f0b93f", "YELLOW_SOFT": "#2e2611",
        "RED": "#f2666b", "RED_SOFT": "#301b1e", "BLUE": "#5b9df5", "BLUE_SOFT": "#132338",
        "SELECTION_BG": "#33306e", "CURRENT_LINE": "#181b28", "CARET": "#9c9af8",
        "HOVER_TINT": "#2a2c38", "SCROLLBAR_THUMB": "#33353f", "SCROLLBAR_THUMB_HOVER": "#3d404c",
        "ROW_HOVER": "#252736", "DANGER_HOVER": "#3a2a2a",
        "TRACE_LINE_HIGHLIGHT": "#233047", "DP_TOUCHED_BG": "#242739",
        "CODE_KEYWORD": "#c586c0", "CODE_STRING": "#ce9178", "CODE_COMMENT": "#6a9955",
        "CODE_NUMBER": "#b5cea8", "CODE_FUNC": "#dcdcaa",
        "CODE_BRACKET_MATCH": "#3a3d4d", "CODE_INDENT_GUIDE": "#1a1c24",
        # LuxCode's own brand duotone — used only for the sidebar wordmark,
        # never for functional UI (ACCENT stays purple everywhere else).
        "BRAND_GOLD": "#d4af37", "BRAND_SILVER": "#c9ccd6",
    },
    "high_contrast": {
        "BG": "#000000", "SIDEBAR_BG": "#050505", "CARD_BG": "#111111", "CARD_BG_2": "#1c1c1c",
        "LIST_BG": "#151515", "LIST_HOVER_BG": "#282828", "EDITOR_BG": "#000000", "EDITOR_CHROME": "#0a0a0a",
        "BORDER": "#4a4a4a",
        "TEXT": "#ffffff", "TEXT_DIM": "#d8d8d8", "MUTED": "#aaaaaa", "FAINT": "#777777",
        "ACCENT": "#9b98ff", "ACCENT_HOVER": "#b3b0ff", "ACCENT_SOFT": "#2c2966",
        "DISABLED_BG": "#2a2a2a", "DISABLED_ICON": "#888888",
        "GREEN": "#5cf0a8", "GREEN_SOFT": "#0e3322", "YELLOW": "#ffce4d", "YELLOW_SOFT": "#3a2c00",
        "RED": "#ff8085", "RED_SOFT": "#3d1418", "BLUE": "#7ebaff", "BLUE_SOFT": "#0e2b47",
        "SELECTION_BG": "#4b46a3", "CURRENT_LINE": "#1f1f1f", "CARET": "#c6c4ff",
        "HOVER_TINT": "#333333", "SCROLLBAR_THUMB": "#555555", "SCROLLBAR_THUMB_HOVER": "#666666",
        "ROW_HOVER": "#2a2a2a", "DANGER_HOVER": "#4a2020",
        "TRACE_LINE_HIGHLIGHT": "#2a3550", "DP_TOUCHED_BG": "#2c2c38",
        "CODE_KEYWORD": "#e0a8e0", "CODE_STRING": "#ffb38a", "CODE_COMMENT": "#8fce6a",
        "CODE_NUMBER": "#d6f0b0", "CODE_FUNC": "#ffe9a8",
        "CODE_BRACKET_MATCH": "#4a4d5d", "CODE_INDENT_GUIDE": "#242424",
        "BRAND_GOLD": "#f0c95c", "BRAND_SILVER": "#e6e8ef",
    },
    "light": {
        "BG": "#f5f6f8", "SIDEBAR_BG": "#ffffff", "CARD_BG": "#ffffff", "CARD_BG_2": "#f0f1f4",
        "LIST_BG": "#f3f4f7", "LIST_HOVER_BG": "#e7e8ee", "EDITOR_BG": "#ffffff", "EDITOR_CHROME": "#f7f7fa",
        "BORDER": "#dcdee3",
        "TEXT": "#1a1b1f", "TEXT_DIM": "#4c4f58", "MUTED": "#71747e", "FAINT": "#9a9ca5",
        "ACCENT": "#5451e0", "ACCENT_HOVER": "#433fc7", "ACCENT_SOFT": "#e7e6fb",
        "DISABLED_BG": "#e9eaee", "DISABLED_ICON": "#a7a9b3",
        "GREEN": "#1f9d63", "GREEN_SOFT": "#e2f6ec", "YELLOW": "#a8730a", "YELLOW_SOFT": "#fbf0d9",
        "RED": "#d63f47", "RED_SOFT": "#fbe4e5", "BLUE": "#2f6fd6", "BLUE_SOFT": "#e5eefc",
        "SELECTION_BG": "#c9c6f7", "CURRENT_LINE": "#eef0fa", "CARET": "#433fc7",
        "HOVER_TINT": "#e2e3ea", "SCROLLBAR_THUMB": "#c7c9d1", "SCROLLBAR_THUMB_HOVER": "#b3b5c0",
        "ROW_HOVER": "#eceefa", "DANGER_HOVER": "#f6d9da",
        "TRACE_LINE_HIGHLIGHT": "#dbe6fb", "DP_TOUCHED_BG": "#e4e5f2",
        # VS Code "Light+" syntax colors — well-tested dark-on-white readability.
        "CODE_KEYWORD": "#af00db", "CODE_STRING": "#a31515", "CODE_COMMENT": "#008000",
        "CODE_NUMBER": "#098658", "CODE_FUNC": "#795e26",
        "CODE_BRACKET_MATCH": "#d6d9e6", "CODE_INDENT_GUIDE": "#eef0f5",
        "BRAND_GOLD": "#a8791a", "BRAND_SILVER": "#6b6f7a",
    },
}

_settings = load_settings()
_ACTIVE_PALETTE = _PALETTES.get(_settings.get("theme", "dark"), _PALETTES["dark"])
THEME_MODE = _settings.get("theme", "dark") if _settings.get("theme") in _PALETTES else "dark"

# Every key in the active palette becomes a same-named module-level constant
# — one loop instead of ~40 manually-paired assignment lines, so a new
# palette key added above can never drift out of sync with what actually
# gets exported (a real bug class if these were hand-duplicated).
globals().update(_ACTIVE_PALETTE)

DIFFICULTY_COLOR = {"Easy": GREEN, "Medium": YELLOW, "Hard": RED}
DIFFICULTY_SOFT = {"Easy": GREEN_SOFT, "Medium": YELLOW_SOFT, "Hard": RED_SOFT}

HEADING_FAMILY = "Segoe UI"
HEADING_FAMILY_SEMIBOLD = "Segoe UI Semibold"
BODY_FAMILY = "Segoe UI"
CODE_FAMILY = "Cascadia Code"

# ---------------------------------------------------------------- brand identity
# Single source of truth for the app's name/tagline — window title, sidebar
# wordmark, and README all read from here, so a future rename touches one line.
APP_NAME = "LuxCode"
APP_TAGLINE = "LeetCode Premium, on steroids"

# ---------------------------------------------------------------- reduced motion
#
# Unlike colors above, this one CAN be live: animate() is a function that
# looks up REDUCED_MOTION in theme's own namespace every time it's called,
# so flipping it via set_reduced_motion() changes behavior immediately for
# every future animation, in every file, with no re-import needed.
REDUCED_MOTION = bool(_settings.get("reduced_motion", False))


def set_reduced_motion(enabled: bool) -> None:
    global REDUCED_MOTION
    REDUCED_MOTION = enabled


FONT_SCALE = float(_settings.get("font_scale", 1.0) or 1.0)


def scaled(size: int) -> int:
    return max(8, round(size * FONT_SCALE))

# ---------------------------------------------------------------- spacing / sizing scale
# One shared scale instead of ad hoc padding numbers repeated per call site.
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24

CARD_PAD_X = 18
CARD_PAD_TOP = 16
CARD_PAD_BOTTOM = 16
CARD_TITLE_GAP = 10  # space between a card's title and its first content row

# Three button sizes, used everywhere instead of one-off heights per button.
BTN_H_LG = 42  # primary actions: Run, Analyze
BTN_H_MD = 36  # secondary actions
BTN_H_SM = 28  # inline row actions (step controls, remove buttons)
BTN_H_XS = 22  # tightest inline icon buttons

RADIUS_CARD = 12
RADIUS_ROW = 8
RADIUS_PILL = 999

FOCUS_RING = ACCENT_HOVER

# A tiny hue per tab so cards/accents feel spatially distinct across tabs
# without repainting the whole app per section (item: per-tab accent tint).
TAB_ACCENT = {
    "Editor": ACCENT,
    "Trace": BLUE,
    "Tests": GREEN,
    "Report": ACCENT,
    "Skills": YELLOW,
    "Whiteboard": "#d17bd6",
}

# A 3-step ramp for scored/graded feedback (vs. the old binary green/red) —
# used wherever a 1-10 score or pass-rate needs more than just "good/bad".
SCORE_LOW = RED
SCORE_MID = YELLOW
SCORE_HIGH = GREEN


def score_color(value: float, max_value: float = 10.0) -> str:
    ratio = max(0.0, min(1.0, value / max_value)) if max_value else 0.0
    if ratio < 0.4:
        return SCORE_LOW
    if ratio < 0.75:
        return SCORE_MID
    return SCORE_HIGH


def button_state_colors(base: str, hover: str) -> dict:
    """Consistent normal/hover/disabled trio for CTkButton kwargs, so every
    button's disabled look is the same instead of some graying fg_color and
    others only dimming text."""
    return {"fg_color": base, "hover_color": hover, "text_color_disabled": FAINT}


# ---------------------------------------------------------------- animation

def ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def ease_in_out_sine(t: float) -> float:
    return -(math.cos(math.pi * t) - 1) / 2


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lerp_color(c1: str, c2: str, t: float) -> str:
    c1, c2 = c1.lstrip("#"), c2.lstrip("#")
    r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
    r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
    r = max(0, min(255, round(_lerp(r1, r2, t))))
    g = max(0, min(255, round(_lerp(g1, g2, t))))
    b = max(0, min(255, round(_lerp(b1, b2, t))))
    return f"#{r:02x}{g:02x}{b:02x}"


# Derived rather than a hand-picked literal per palette — guaranteed to stay
# a consistent "one step darker" relationship to ACCENT in every theme.
ACCENT_PRESSED = _lerp_color(ACCENT, "#000000", 0.18)


def animate(widget, duration_ms: float, on_update, on_done=None, easing=ease_out_cubic) -> None:
    """Frame-rate-independent tween: calls on_update(eased_t in [0,1]) every ~15ms.

    Respects REDUCED_MOTION (checked live, not at import time — see the
    module docstring above set_reduced_motion): when enabled, every call
    jumps straight to the end state instead of tweening."""
    if REDUCED_MOTION:
        try:
            on_update(1.0)
        except tk.TclError:
            return
        if on_done:
            on_done()
        return

    start = time.perf_counter()

    def step() -> None:
        if not widget.winfo_exists():
            return
        elapsed = (time.perf_counter() - start) * 1000
        t = min(elapsed / duration_ms, 1.0) if duration_ms > 0 else 1.0
        try:
            on_update(easing(t))
        except tk.TclError:
            return
        if t < 1.0:
            widget.after(15, step)
        elif on_done:
            on_done()

    step()


# ---------------------------------------------------------------- small helpers


def _normalize_big_o(value: str) -> str:
    return value.replace(" ", "").lower()


_SUPERSCRIPT_MAP = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
    "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
    "a": "ᵃ", "b": "ᵇ", "c": "ᶜ", "d": "ᵈ", "e": "ᵉ", "f": "ᶠ", "g": "ᵍ", "h": "ʰ", "i": "ⁱ",
    "j": "ʲ", "k": "ᵏ", "l": "ˡ", "m": "ᵐ", "n": "ⁿ", "o": "ᵒ", "p": "ᵖ", "r": "ʳ", "s": "ˢ",
    "t": "ᵗ", "u": "ᵘ", "v": "ᵛ", "w": "ʷ", "x": "ˣ", "y": "ʸ", "z": "ᶻ",
}
# Two alternatives so the parens are matched as a pair, never independently optional —
# otherwise "n^2)" would swallow the *outer* closing paren of "O(n^2)" itself.
_EXPONENT_RE = re.compile(r"\^\(([\w+\-]+)\)|\^([\w+\-]+)")


def _format_math(text: str) -> str:
    """Turn caret exponents like 'n^2' or '2^n' into real superscript glyphs."""

    def repl(match: re.Match) -> str:
        exponent = match.group(1) or match.group(2)
        return "".join(_SUPERSCRIPT_MAP.get(ch, ch) for ch in exponent)

    return _EXPONENT_RE.sub(repl, text)


def _truncate_to_width(text: str, font: ctk.CTkFont, max_width: int) -> str:
    if font.measure(text) <= max_width:
        return text
    ellipsis = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.measure(text[:mid] + ellipsis) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + ellipsis


def bind_responsive_wraplength(label: ctk.CTkLabel, extra_padding: int = 8) -> None:
    """Keep a label's wraplength in sync with its parent's actual width.

    A fixed wraplength guess is wrong in both directions: too narrow and text
    wraps early with obvious empty space still to the right of it (the
    common case in a resizable main content area); too wide and it overflows
    a narrower window. Call once right after packing/gridding the label.
    """
    parent = label.master

    def _update(event=None) -> None:
        if not label.winfo_exists():
            return
        width = parent.winfo_width() - extra_padding
        if width > 60:
            label.configure(wraplength=width)

    parent.bind("<Configure>", _update, add="+")
    label.after(50, _update)  # initial pass once the parent has its real size


def _pill(parent, text: str, bg: str, fg: str, font: ctk.CTkFont) -> ctk.CTkFrame:
    frame = ctk.CTkFrame(parent, fg_color=bg, corner_radius=999)
    ctk.CTkLabel(frame, text=text, text_color=fg, font=font, fg_color="transparent").pack(
        padx=10, pady=3
    )
    return frame


def _draw_score_gauge(canvas: tk.Canvas, score: float, color: str, font_bold, font_small) -> None:
    canvas.delete("all")
    size = int(canvas.cget("width"))
    stroke = 9
    pad = stroke
    bbox = (pad, pad, size - pad, size - pad)
    canvas.create_oval(*bbox, outline=CARD_BG_2, width=stroke)
    if score > 0:
        extent = -(360 * score / 10)
        canvas.create_arc(*bbox, start=90, extent=extent, style="arc", outline=color, width=stroke)
    canvas.create_text(size / 2, size / 2 - 6, text=str(round(score)), fill=TEXT, font=font_bold)
    canvas.create_text(size / 2, size / 2 + 16, text="/ 10", fill=MUTED, font=font_small)


# ---------------------------------------------------------------- spinner


class Spinner(tk.Canvas):
    def __init__(self, parent, size: int = 14, color: str = ACCENT, bg: str = SIDEBAR_BG, thickness: int = 2) -> None:
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0)
        self.size = size
        self.color = color
        self.thickness = thickness
        self._angle = 0.0
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._spin()

    def stop(self) -> None:
        self._running = False
        if self.winfo_exists():
            self.delete("all")

    def _spin(self) -> None:
        if not self._running or not self.winfo_exists():
            return
        self.delete("all")
        pad = self.thickness + 1
        self.create_arc(
            pad, pad, self.size - pad, self.size - pad, start=self._angle, extent=100,
            style="arc", outline=self.color, width=self.thickness,
        )
        self._angle = (self._angle - 22) % 360
        self.after(35, self._spin)


# ---------------------------------------------------------------- reusable interaction helpers


def add_hover(widget, normal_color: str, hover_color: str) -> None:
    """Lightens a frame's background on mouse-over — used to make table-ish
    rows (variables, watches, breakpoints, boundary cases) feel clickable
    even when they don't have a CTkButton's built-in hover state."""
    def _enter(_e=None):
        if widget.winfo_exists():
            widget.configure(fg_color=hover_color)

    def _leave(_e=None):
        if widget.winfo_exists():
            widget.configure(fg_color=normal_color)

    widget.bind("<Enter>", _enter, add="+")
    widget.bind("<Leave>", _leave, add="+")


def add_press_feedback(button: ctk.CTkButton, pressed_color: str) -> None:
    """A brief darken-on-press so a click registers as tactile, not just a
    hover-then-nothing. CTkButton draws itself on an internal canvas with no
    exposed scale/transform, so a true "squash" isn't available — this swaps
    fg_color for the press duration instead, which reads the same way at a
    glance and needs no layout changes."""
    try:
        normal_color = button.cget("fg_color")
    except Exception:
        return
    if not isinstance(normal_color, str):
        return

    def _press(_e=None):
        if button.winfo_exists() and str(button.cget("state")) != "disabled":
            button.configure(fg_color=pressed_color)

    def _release(_e=None):
        if button.winfo_exists():
            button.configure(fg_color=normal_color)

    button.bind("<ButtonPress-1>", _press, add="+")
    button.bind("<ButtonRelease-1>", _release, add="+")


def stagger_in(widgets: list, delay_ms: int = 45, duration_ms: int = 220) -> None:
    """Fades+lifts a list of already-packed/gridded widgets in one at a time,
    card-by-card, instead of everything popping in simultaneously. Each
    widget needs a `.configure(fg_color=...)`-capable target color already
    set — this only animates opacity-via-color-lerp against CARD_BG."""
    for i, w in enumerate(widgets):
        if not hasattr(w, "winfo_exists"):
            continue
        try:
            target = w.cget("fg_color")
        except Exception:
            continue
        if not isinstance(target, str) or not target.startswith("#"):
            continue

        def _run(widget=w, final_color=target):
            if not widget.winfo_exists():
                return
            widget.configure(fg_color=BG)
            animate(
                widget, duration_ms,
                lambda t, wd=widget, fc=final_color: wd.configure(fg_color=_lerp_color(BG, fc, t))
                if wd.winfo_exists() else None,
            )

        # Under reduced motion, animate() itself will skip straight to the end
        # state — but the staggered .after() delay would still hold each card
        # back sequentially, which is its own kind of motion. Skip it too.
        w.after(0 if REDUCED_MOTION else i * delay_ms, _run)


def animate_number(label: ctk.CTkLabel, start: float, end: float, duration_ms: int = 350, fmt=lambda v: f"{v:.1f}") -> None:
    """Rolls a label's numeric text from start to end instead of snapping —
    used for live-updating figures (memory KB, step counts)."""
    def _update(t: float) -> None:
        if label.winfo_exists():
            label.configure(text=fmt(_lerp(start, end, t)))

    animate(label, duration_ms, _update, easing=ease_out_cubic)


def flash_confirm(label: ctk.CTkLabel, text: str = "✓ Saved", hold_ms: int = 900) -> None:
    """Briefly swaps a label's text for a confirmation, then restores it —
    used after silent state changes (breakpoint condition edits, watch adds)
    that otherwise give the user no feedback that anything happened."""
    if not label.winfo_exists():
        return
    original = label.cget("text")
    original_color = label.cget("text_color")
    label.configure(text=text, text_color=GREEN)

    def _restore():
        if label.winfo_exists():
            label.configure(text=original, text_color=original_color)

    label.after(hold_ms, _restore)


def make_copy_button(parent, get_text, fonts, width: int = 32) -> ctk.CTkButton:
    """A small clipboard-copy icon button that flashes a checkmark on click."""
    btn = ctk.CTkButton(
        parent, text="⧉", width=width, height=BTN_H_XS, corner_radius=6, fg_color=CARD_BG_2,
        hover_color=HOVER_TINT, text_color=TEXT_DIM, font=fonts.small,
    )

    def _copy():
        try:
            parent.clipboard_clear()
            parent.clipboard_append(get_text())
        except Exception:
            return
        original = btn.cget("text")
        btn.configure(text="✓", text_color=GREEN)
        btn.after(1000, lambda: btn.configure(text=original, text_color=TEXT_DIM) if btn.winfo_exists() else None)

    btn.configure(command=_copy)
    return btn


class Skeleton(tk.Canvas):
    """A shimmering placeholder block shown while a card's real content is
    still loading/computing — replaces a bare spinner for content-shaped
    areas so the eventual layout doesn't visually "pop" into existence."""

    def __init__(self, parent, width: int = 200, height: int = 14, bg: str = CARD_BG) -> None:
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0)
        self._phase = 0.0
        self._running = False
        self._w = width
        self._h = height

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tick()

    def stop(self) -> None:
        self._running = False
        if self.winfo_exists():
            self.delete("all")

    def _tick(self) -> None:
        if not self._running or not self.winfo_exists():
            return
        self.delete("all")
        self.create_rectangle(0, 0, self._w, self._h, fill=CARD_BG_2, outline="")
        band_w = self._w * 0.3
        x = (self._phase % 1.6 - 0.3) * self._w
        self.create_rectangle(x, 0, x + band_w, self._h, fill=HOVER_TINT, outline="")
        self._phase += 0.02
        self.after(30, self._tick)


class Toast(ctk.CTkFrame):
    """A small inline confirmation banner (not a real OS toast — an in-panel
    strip) for background completions that happen after the user's attention
    has moved elsewhere, e.g. a long test run finishing on a backgrounded tab.

    Use grid_at(...) or pack_at(...) to place it ONCE, right after
    construction — NOT a raw .grid()/.pack() call. Tkinter's winfo_manager()
    reports empty string once a widget has been grid_remove()'d/pack_forget()'d,
    so re-detecting the manager on every show()/hide() call doesn't work;
    grid_at/pack_at remember it explicitly instead."""

    def __init__(self, parent, fonts) -> None:
        super().__init__(parent, fg_color=CARD_BG_2, corner_radius=8, height=0)
        self.fonts = fonts
        self._label = ctk.CTkLabel(self, text="", text_color=TEXT, font=fonts.small, anchor="w")
        self._label.pack(side="left", padx=12, pady=8, fill="x", expand=True)
        self._manager: str | None = None
        self._place_kwargs: dict = {}

    def grid_at(self, **kwargs) -> None:
        self._manager = "grid"
        self._place_kwargs = kwargs
        self.grid(**kwargs)
        self.grid_remove()

    def pack_at(self, **kwargs) -> None:
        self._manager = "pack"
        self._place_kwargs = kwargs
        self.pack(**kwargs)
        self.pack_forget()

    def show(self, text: str, color: str = GREEN, hold_ms: int = 2600) -> None:
        self._label.configure(text=text, text_color=color)
        if self._manager == "grid":
            self.grid(**self._place_kwargs)
        elif self._manager == "pack":
            self.pack(**self._place_kwargs)
        self.after(hold_ms, self._hide)

    def _hide(self) -> None:
        if not self.winfo_exists():
            return
        if self._manager == "grid":
            self.grid_remove()
        elif self._manager == "pack":
            self.pack_forget()


class Fonts:
    """Lazily-built shared font set — construct once a Tk root exists."""

    def __init__(self) -> None:
        self.title = ctk.CTkFont(family=HEADING_FAMILY_SEMIBOLD, size=scaled(27))
        self.subtitle = ctk.CTkFont(family=BODY_FAMILY, size=scaled(15))
        self.subtitle_bold = ctk.CTkFont(family=BODY_FAMILY, size=scaled(15), weight="bold", slant="italic")
        self.section = ctk.CTkFont(family=BODY_FAMILY, size=scaled(12), weight="bold")
        self.body = ctk.CTkFont(family=BODY_FAMILY, size=scaled(16))
        self.body_bold = ctk.CTkFont(family=BODY_FAMILY, size=scaled(16), weight="bold")
        self.small = ctk.CTkFont(family=BODY_FAMILY, size=scaled(14))
        self.small_bold = ctk.CTkFont(family=BODY_FAMILY, size=scaled(14), weight="bold")
        self.card_title = ctk.CTkFont(family=HEADING_FAMILY_SEMIBOLD, size=scaled(20))
        self.score = ctk.CTkFont(family=HEADING_FAMILY_SEMIBOLD, size=scaled(29))
        self.button = ctk.CTkFont(family=BODY_FAMILY, size=scaled(18), weight="bold")
        self.code = ctk.CTkFont(family=CODE_FAMILY, size=scaled(16))
        self.code_small = ctk.CTkFont(family=CODE_FAMILY, size=scaled(13))
        self.pill = ctk.CTkFont(family=BODY_FAMILY, size=scaled(14), weight="bold")

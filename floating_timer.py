"""A small floating countdown timer, pinned to a corner of the main window
and drawn on top of whichever tab is active — a simulated-interview
pressure clock that isn't locked to the Whiteboard tab, since the point is
timing yourself while you work, not just while you're sketching.

Placed with .place() directly on the app's root window (a sibling of the
CTkTabview, not a child of any one tab's frame) and raised with .lift(), so
switching tabs never hides it — CTkTabview only un-grids its OWN per-tab
content, it has no effect on a completely separate widget stacked on top.
"""

from __future__ import annotations

import customtkinter as ctk

from theme import (
    ACCENT, ACCENT_HOVER, BORDER, CARD_BG, CARD_BG_2, FAINT, GREEN, HOVER_TINT,
    RED, TEXT, TEXT_DIM, YELLOW,
)

_DURATIONS = [("15 min", 15 * 60), ("30 min", 30 * 60), ("45 min", 45 * 60), ("60 min", 60 * 60)]


class FloatingTimer(ctk.CTkFrame):
    def __init__(self, parent, fonts) -> None:
        super().__init__(parent, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
        self.fonts = fonts
        self.total_s = _DURATIONS[1][1]
        self.remaining_s = self.total_s
        self.running = False
        self.expanded = True
        self._timer_job: str | None = None

        self._build_expanded()
        self._build_collapsed()
        self._apply_expanded_state()
        self._update_label()

    # ------------------------------------------------------------------ UI

    def _build_expanded(self) -> None:
        self.expanded_frame = ctk.CTkFrame(self, fg_color="transparent")
        row = ctk.CTkFrame(self.expanded_frame, fg_color="transparent")
        row.pack(padx=10, pady=8)

        self.collapse_btn = ctk.CTkButton(
            row, text="—", width=22, height=22, corner_radius=6, fg_color="transparent",
            hover_color=HOVER_TINT, text_color=FAINT, font=self.fonts.small, command=self.collapse,
        )
        self.collapse_btn.pack(side="left", padx=(0, 6))

        self.duration_menu = ctk.CTkOptionMenu(
            row, values=[d[0] for d in _DURATIONS], width=88, height=28, font=self.fonts.small,
            dropdown_font=self.fonts.small, fg_color=CARD_BG_2, button_color=CARD_BG_2, button_hover_color=HOVER_TINT,
            dropdown_fg_color=CARD_BG_2, dropdown_hover_color=HOVER_TINT, dropdown_text_color=TEXT, text_color=TEXT_DIM,
            command=self._on_duration_change,
        )
        self.duration_menu.set("30 min")
        self.duration_menu.pack(side="left", padx=(0, 8))

        self.timer_label = ctk.CTkLabel(row, text="", font=ctk.CTkFont(family="Cascadia Code", size=22, weight="bold"))
        self.timer_label.pack(side="left", padx=(0, 8))

        self.start_pause_btn = ctk.CTkButton(
            row, text="Start", width=64, height=28, corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=self.fonts.small_bold, command=self.toggle,
        )
        self.start_pause_btn.pack(side="left")

    def _build_collapsed(self) -> None:
        self.collapsed_frame = ctk.CTkFrame(self, fg_color="transparent", cursor="hand2")
        row = ctk.CTkFrame(self.collapsed_frame, fg_color="transparent")
        row.pack(padx=10, pady=6)
        self.collapsed_icon = ctk.CTkLabel(row, text="⏱", font=self.fonts.small, text_color=TEXT_DIM)
        self.collapsed_icon.pack(side="left", padx=(0, 6))
        self.collapsed_label = ctk.CTkLabel(row, text="", font=ctk.CTkFont(family="Cascadia Code", size=14, weight="bold"))
        self.collapsed_label.pack(side="left")
        for widget in (self.collapsed_frame, row, self.collapsed_icon, self.collapsed_label):
            widget.bind("<Button-1>", lambda e: self.expand())

    def _apply_expanded_state(self) -> None:
        if self.expanded:
            self.collapsed_frame.pack_forget()
            self.expanded_frame.pack()
        else:
            self.expanded_frame.pack_forget()
            self.collapsed_frame.pack()

    def collapse(self) -> None:
        self.expanded = False
        self._apply_expanded_state()

    def expand(self) -> None:
        self.expanded = True
        self._apply_expanded_state()

    # -------------------------------------------------------------- timer

    def _on_duration_change(self, label: str) -> None:
        seconds = next(s for l, s in _DURATIONS if l == label)
        self.total_s = seconds
        self.remaining_s = seconds
        self._stop()
        self._update_label()

    def toggle(self, event=None) -> None:
        if self.running:
            self._stop()
        else:
            if self.remaining_s <= 0:
                self.remaining_s = self.total_s
            self.running = True
            self.start_pause_btn.configure(text="Pause")
            self._tick()

    def _stop(self) -> None:
        self.running = False
        self.start_pause_btn.configure(text="Start")
        if self._timer_job:
            self.after_cancel(self._timer_job)
            self._timer_job = None

    def _tick(self) -> None:
        if not self.running:
            return
        self._update_label()
        if self.remaining_s <= 0:
            self._stop()
            return
        self.remaining_s -= 1
        self._timer_job = self.after(1000, self._tick)

    def _update_label(self) -> None:
        minutes, seconds = divmod(max(self.remaining_s, 0), 60)
        frac = self.remaining_s / self.total_s if self.total_s else 0
        color = GREEN if frac > 0.5 else YELLOW if frac > 0.15 else RED
        text = f"{minutes:02d}:{seconds:02d}"
        self.timer_label.configure(text=text, text_color=color)
        self.collapsed_label.configure(text=text, text_color=color)

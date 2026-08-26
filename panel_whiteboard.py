"""Whiteboard tab: a code-less structural scratchpad (freehand drawing, for
sketching data structures/arrows before touching the keyboard) plus a
countdown pressure meter, simulating interview conditions. No AI voice
interviewer — that needs live speech I/O this app's architecture doesn't
have; the honest version of this feature is the scratchpad + timer."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from theme import ACCENT, ACCENT_HOVER, BORDER, CARD_BG, CARD_BG_2, GREEN, HOVER_TINT, MUTED, RED, TEXT, TEXT_DIM, YELLOW

# A real whiteboard should actually look like a whiteboard — light-mode users
# get a light board with a dark default pen, not a hardcoded-black canvas
# that reads as broken/unstyled against the rest of a light UI.
_BOARD_BG = CARD_BG
_INK_COLORS = [(TEXT, "Ink"), ("#6e6bf5", "Violet"), ("#3ecf8e", "Green"), ("#f2666b", "Red")]

_DURATIONS = [("15 min", 15 * 60), ("30 min", 30 * 60), ("45 min", 45 * 60), ("60 min", 60 * 60)]


class WhiteboardPanel(ctk.CTkFrame):
    def __init__(self, parent, fonts) -> None:
        super().__init__(parent, fg_color="transparent")
        self.fonts = fonts
        self.ink_color = _INK_COLORS[0][0]
        self.remaining_s = _DURATIONS[1][1]
        self.total_s = _DURATIONS[1][1]
        self.running = False
        self._last_xy: tuple[float, float] | None = None
        self._timer_job: str | None = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_toolbar()
        self._build_board()
        self._update_timer_label()

    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="we", pady=(0, 12))

        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.pack(side="left")
        ctk.CTkLabel(left, text="Pen:", text_color=TEXT_DIM, font=self.fonts.small).pack(side="left", padx=(0, 8))
        for color, name in _INK_COLORS:
            swatch = ctk.CTkButton(
                left, text="", width=24, height=24, corner_radius=12, fg_color=color, hover_color=color,
                border_width=2, border_color=CARD_BG_2, command=lambda c=color: self._set_ink(c),
            )
            swatch.pack(side="left", padx=3)
        ctk.CTkButton(
            left, text="Clear Board", width=100, height=28, corner_radius=8, font=self.fonts.small,
            fg_color=CARD_BG, hover_color=CARD_BG_2, text_color=TEXT_DIM, command=self._clear_board,
        ).pack(side="left", padx=(16, 0))

        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.pack(side="right")
        self.timer_label = ctk.CTkLabel(right, text="", font=ctk.CTkFont(family="Cascadia Code", size=28, weight="bold"))
        self.timer_label.pack(side="right", padx=(14, 0))
        self.start_pause_btn = ctk.CTkButton(
            right, text="Start", width=80, height=32, corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=self.fonts.small_bold, command=self._toggle_timer,
        )
        self.start_pause_btn.pack(side="right", padx=(8, 0))
        self.duration_menu = ctk.CTkOptionMenu(
            right, values=[d[0] for d in _DURATIONS], width=100, height=32, font=self.fonts.small,
            dropdown_font=self.fonts.small, fg_color=CARD_BG, button_color=CARD_BG_2, button_hover_color=HOVER_TINT,
            dropdown_fg_color=CARD_BG_2, dropdown_hover_color=HOVER_TINT, dropdown_text_color=TEXT, text_color=TEXT_DIM,
            command=self._on_duration_change,
        )
        self.duration_menu.set("30 min")
        self.duration_menu.pack(side="right")

    def _build_board(self) -> None:
        frame = ctk.CTkFrame(self, fg_color=_BOARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
        frame.grid(row=1, column=0, sticky="nswe")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(frame, bg=_BOARD_BG, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nswe", padx=1, pady=1)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        # Easter egg #7: a watermark in the corner, nearly the same shade as
        # the board itself — visible only if you're looking for it.
        self.canvas.bind("<Configure>", self._draw_watermark, add="+")

    def _draw_watermark(self, event=None) -> None:
        self.canvas.delete("watermark")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w > 1 and h > 1:
            self.canvas.create_text(
                w - 10, h - 10, text="zyad", anchor="se", fill=CARD_BG_2, font=("Cascadia Code", 11), tags="watermark",
            )
            self.canvas.tag_lower("watermark")

    # -- drawing ----------------------------------------------------------

    def _set_ink(self, color: str) -> None:
        self.ink_color = color

    def _clear_board(self) -> None:
        self.canvas.delete("all")
        self._draw_watermark()  # "all" clears the easter egg too — redraw it

    def _on_press(self, event) -> None:
        self._last_xy = (event.x, event.y)

    def _on_drag(self, event) -> None:
        if self._last_xy is not None:
            x0, y0 = self._last_xy
            self.canvas.create_line(x0, y0, event.x, event.y, fill=self.ink_color, width=2.5, capstyle="round", smooth=True)
        self._last_xy = (event.x, event.y)

    def _on_release(self, event) -> None:
        self._last_xy = None

    # -- timer --------------------------------------------------------------

    def _on_duration_change(self, label: str) -> None:
        seconds = next(s for l, s in _DURATIONS if l == label)
        self.total_s = seconds
        self.remaining_s = seconds
        self._stop_timer()
        self._update_timer_label()

    def _toggle_timer(self) -> None:
        if self.running:
            self._stop_timer()
        else:
            if self.remaining_s <= 0:
                self.remaining_s = self.total_s
            self.running = True
            self.start_pause_btn.configure(text="Pause")
            self._tick()

    def _stop_timer(self) -> None:
        self.running = False
        self.start_pause_btn.configure(text="Start")
        if self._timer_job:
            self.after_cancel(self._timer_job)
            self._timer_job = None

    def _tick(self) -> None:
        if not self.running:
            return
        self._update_timer_label()
        if self.remaining_s <= 0:
            self._stop_timer()
            return
        self.remaining_s -= 1
        self._timer_job = self.after(1000, self._tick)

    def _update_timer_label(self) -> None:
        minutes, seconds = divmod(max(self.remaining_s, 0), 60)
        frac = self.remaining_s / self.total_s if self.total_s else 0
        color = GREEN if frac > 0.5 else YELLOW if frac > 0.15 else RED
        self.timer_label.configure(text=f"{minutes:02d}:{seconds:02d}", text_color=color)

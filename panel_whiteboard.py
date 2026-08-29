"""Whiteboard tab: a code-less structural scratchpad — freehand pen, shapes,
text, and an eraser, for sketching data structures/arrows before touching
the keyboard. The countdown timer used to live here too; it's now a
floating widget owned by gui.py so it survives switching tabs.
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from theme import ACCENT, BORDER, CARD_BG, CARD_BG_2, HOVER_TINT, TEXT, TEXT_DIM

# A real whiteboard should actually look like a whiteboard — light-mode users
# get a light board with a dark default pen, not a hardcoded-black canvas
# that reads as broken/unstyled against the rest of a light UI.
_BOARD_BG = CARD_BG
_INK_COLORS = [(TEXT, "Ink"), ("#6e6bf5", "Violet"), ("#3ecf8e", "Green"), ("#f2666b", "Red"), ("#f0b93f", "Yellow")]

# (tool id, glyph, tooltip-ish label)
_TOOLS = [
    ("pen", "✏", "Pen"),
    ("eraser", "⌫", "Eraser"),
    ("line", "╱", "Line"),
    ("arrow", "↗", "Arrow"),
    ("rectangle", "▭", "Rectangle"),
    ("ellipse", "◯", "Ellipse"),
    ("text", "T", "Text"),
]

_PEN_SIZES = [("S", 1.5), ("M", 3.0), ("L", 5.5)]

# Canvas item options worth preserving across an undo/redo recreate — every
# other option (state, tags we don't manage, etc.) is left at its default.
_RECREATE_OPTS = ("fill", "outline", "width", "smooth", "capstyle", "arrow", "font", "anchor", "text")

_SHAPE_CREATORS = {
    "line": "create_line",
    "arrow": "create_line",
    "rectangle": "create_rectangle",
    "oval": "create_oval",
    "text": "create_text",
}


class WhiteboardPanel(ctk.CTkFrame):
    def __init__(self, parent, fonts) -> None:
        super().__init__(parent, fg_color="transparent")
        self.fonts = fonts
        self.ink_color = _INK_COLORS[0][0]
        self.pen_size = _PEN_SIZES[1][1]
        self.tool = "pen"
        self._last_xy: tuple[float, float] | None = None
        self._drag_start: tuple[float, float] | None = None
        self._preview_id: int | None = None
        self._current_stroke_ids: list[int] = []
        self._erased_this_drag: list[dict] = []
        self._text_entry: ctk.CTkEntry | None = None
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._tool_buttons: dict[str, ctk.CTkButton] = {}
        self._size_buttons: dict[float, ctk.CTkButton] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_toolbar()
        self._build_board()

    # ------------------------------------------------------------------ UI

    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="we", pady=(0, 12))

        tools_row = ctk.CTkFrame(bar, fg_color="transparent")
        tools_row.pack(fill="x")

        for tool_id, glyph, label in _TOOLS:
            btn = ctk.CTkButton(
                tools_row, text=glyph, width=34, height=30, corner_radius=8, font=self.fonts.small_bold,
                fg_color=ACCENT if tool_id == self.tool else CARD_BG, hover_color=HOVER_TINT,
                text_color=TEXT if tool_id == self.tool else TEXT_DIM,
                command=lambda t=tool_id: self._set_tool(t),
            )
            btn.pack(side="left", padx=(0, 4))
            self._tool_buttons[tool_id] = btn

        ctk.CTkFrame(tools_row, fg_color=BORDER, width=1, height=24).pack(side="left", padx=8, pady=2)

        for color, name in _INK_COLORS:
            swatch = ctk.CTkButton(
                tools_row, text="", width=24, height=24, corner_radius=12, fg_color=color, hover_color=color,
                border_width=2, border_color=CARD_BG_2, command=lambda c=color: self._set_ink(c),
            )
            swatch.pack(side="left", padx=3)

        ctk.CTkFrame(tools_row, fg_color=BORDER, width=1, height=24).pack(side="left", padx=8, pady=2)

        for label, size in _PEN_SIZES:
            btn = ctk.CTkButton(
                tools_row, text=label, width=28, height=30, corner_radius=8, font=self.fonts.small_bold,
                fg_color=ACCENT if size == self.pen_size else CARD_BG, hover_color=HOVER_TINT,
                text_color=TEXT if size == self.pen_size else TEXT_DIM,
                command=lambda s=size: self._set_pen_size(s),
            )
            btn.pack(side="left", padx=(0, 4))
            self._size_buttons[size] = btn

        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.pack(side="right")
        ctk.CTkButton(
            right, text="Clear Board", width=100, height=30, corner_radius=8, font=self.fonts.small,
            fg_color=CARD_BG, hover_color=CARD_BG_2, text_color=TEXT_DIM, command=self._clear_board,
        ).pack(side="left", padx=(8, 0))
        self.redo_btn = ctk.CTkButton(
            right, text="↷", width=34, height=30, corner_radius=8, font=self.fonts.small_bold,
            fg_color=CARD_BG, hover_color=CARD_BG_2, text_color=TEXT_DIM, command=self.redo, state="disabled",
        )
        self.redo_btn.pack(side="left", padx=(8, 0))
        self.undo_btn = ctk.CTkButton(
            right, text="↶", width=34, height=30, corner_radius=8, font=self.fonts.small_bold,
            fg_color=CARD_BG, hover_color=CARD_BG_2, text_color=TEXT_DIM, command=self.undo, state="disabled",
        )
        self.undo_btn.pack(side="left")

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

    # -- tool state ---------------------------------------------------------

    def _set_tool(self, tool_id: str) -> None:
        self._commit_text_input()
        self.tool = tool_id
        for t, btn in self._tool_buttons.items():
            active = t == tool_id
            btn.configure(fg_color=ACCENT if active else CARD_BG, text_color=TEXT if active else TEXT_DIM)
        cursors = {"eraser": "dotbox", "text": "xterm"}
        self.canvas.configure(cursor=cursors.get(tool_id, "crosshair" if tool_id != "pen" else "pencil"))

    def _set_ink(self, color: str) -> None:
        self.ink_color = color

    def _set_pen_size(self, size: float) -> None:
        self.pen_size = size
        for s, btn in self._size_buttons.items():
            active = s == size
            btn.configure(fg_color=ACCENT if active else CARD_BG, text_color=TEXT if active else TEXT_DIM)

    # -- drawing ----------------------------------------------------------

    def _on_press(self, event) -> None:
        self._commit_text_input()
        self._last_xy = (event.x, event.y)
        self._drag_start = (event.x, event.y)
        self._current_stroke_ids = []
        self._preview_id = None
        self._erased_this_drag = []
        if self.tool == "eraser":
            self._erase_at(event.x, event.y)

    def _on_drag(self, event) -> None:
        if self.tool == "pen":
            if self._last_xy is not None:
                x0, y0 = self._last_xy
                seg_id = self.canvas.create_line(
                    x0, y0, event.x, event.y, fill=self.ink_color, width=self.pen_size,
                    capstyle="round", smooth=True,
                )
                self._current_stroke_ids.append(seg_id)
            self._last_xy = (event.x, event.y)
        elif self.tool == "eraser":
            self._erase_at(event.x, event.y)
        elif self.tool in ("line", "arrow", "rectangle", "ellipse") and self._drag_start is not None:
            if self._preview_id is not None:
                self.canvas.delete(self._preview_id)
            x0, y0 = self._drag_start
            self._preview_id = self._create_shape(self.tool, x0, y0, event.x, event.y)

    def _on_release(self, event) -> None:
        if self.tool == "pen":
            if self._current_stroke_ids:
                self._push_undo({"kind": "create", "ids": self._current_stroke_ids})
        elif self.tool == "eraser":
            if self._erased_this_drag:
                self._push_undo({"kind": "erase", "snaps": self._erased_this_drag})
        elif self.tool in ("line", "arrow", "rectangle", "ellipse"):
            if self._preview_id is not None:
                self._push_undo({"kind": "create", "ids": [self._preview_id]})
        elif self.tool == "text" and self._drag_start is not None:
            self._start_text_input(*self._drag_start)

        self._last_xy = None
        self._drag_start = None
        self._preview_id = None
        self._current_stroke_ids = []
        self._erased_this_drag = []

    def _create_shape(self, tool: str, x0: float, y0: float, x1: float, y1: float) -> int:
        if tool == "line":
            return self.canvas.create_line(x0, y0, x1, y1, fill=self.ink_color, width=self.pen_size, capstyle="round")
        if tool == "arrow":
            return self.canvas.create_line(
                x0, y0, x1, y1, fill=self.ink_color, width=self.pen_size, capstyle="round", arrow="last",
            )
        if tool == "rectangle":
            return self.canvas.create_rectangle(x0, y0, x1, y1, outline=self.ink_color, width=self.pen_size)
        if tool == "ellipse":
            return self.canvas.create_oval(x0, y0, x1, y1, outline=self.ink_color, width=self.pen_size)
        raise ValueError(f"not a shape tool: {tool}")

    # -- eraser ---------------------------------------------------------------

    def _erase_at(self, x: float, y: float) -> None:
        radius = 10
        already = {s["id"] for s in self._erased_this_drag}
        for item_id in self.canvas.find_overlapping(x - radius, y - radius, x + radius, y + radius):
            if item_id in already or "watermark" in self.canvas.gettags(item_id):
                continue
            snap = self._snapshot_item(item_id)
            snap["id"] = item_id
            self._erased_this_drag.append(snap)
            already.add(item_id)
            self.canvas.delete(item_id)

    # -- text tool ------------------------------------------------------------

    def _start_text_input(self, x: float, y: float) -> None:
        self._commit_text_input()  # finish whatever text box was already open, if any
        entry = ctk.CTkEntry(
            self.canvas, width=180, height=28, font=self.fonts.body, fg_color=CARD_BG_2,
            border_color=self.ink_color, text_color=self.ink_color,
        )
        window_id = self.canvas.create_window(x, y, window=entry, anchor="nw")
        self._text_entry = entry
        self._text_window_id = window_id
        self._text_origin = (x, y)
        entry.bind("<Return>", lambda e: self._commit_text_input())
        entry.bind("<Escape>", lambda e: self._discard_text_input())
        # NOT relying on <FocusOut> to commit: in practice it can fire the
        # instant the entry is created (a race with Tkinter's own default
        # focus-follows-click handling for the canvas stealing focus right
        # back), closing the box before a single character gets typed.
        # Committing is instead driven explicitly — from _on_press when the
        # user clicks elsewhere, and from _set_tool when they switch tools —
        # both of which are this class's own calls, not Tk's focus subsystem.
        entry.after(50, lambda: entry.focus_set() if entry.winfo_exists() else None)

    def _commit_text_input(self) -> None:
        if self._text_entry is None:
            return
        text = self._text_entry.get().strip()
        x, y = self._text_origin
        self.canvas.delete(self._text_window_id)
        self._text_entry.destroy()
        self._text_entry = None
        if text:
            item_id = self.canvas.create_text(
                x, y, text=text, fill=self.ink_color, anchor="nw",
                font=(self.fonts.body.cget("family"), self.fonts.body.cget("size")),
            )
            self._push_undo({"kind": "create", "ids": [item_id]})

    def _discard_text_input(self) -> None:
        if self._text_entry is None:
            return
        self.canvas.delete(self._text_window_id)
        self._text_entry.destroy()
        self._text_entry = None

    # -- undo / redo ------------------------------------------------------------
    #
    # A tiny command-pattern stack: a "create" action undoes by deleting the
    # items it made (and remembers how to recreate them for redo); an
    # "erase" action undoes by recreating whatever it deleted. Every draw
    # tool funnels into one of these two shapes, so the stack itself doesn't
    # need to know about pens vs. shapes vs. text.

    def _snapshot_item(self, item_id: int) -> dict:
        kind = self.canvas.type(item_id)
        coords = self.canvas.coords(item_id)
        opts = {}
        for key in _RECREATE_OPTS:
            try:
                value = self.canvas.itemcget(item_id, key)
            except tk.TclError:
                continue
            if value not in ("", None):
                opts[key] = value
        return {"shape": kind, "coords": coords, "opts": opts}

    def _recreate_item(self, snap: dict) -> int:
        creator = getattr(self.canvas, _SHAPE_CREATORS[snap["shape"]])
        return creator(*snap["coords"], **snap["opts"])

    def _push_undo(self, action: dict) -> None:
        self._undo_stack.append(action)
        self._redo_stack.clear()
        self._refresh_undo_buttons()

    def _refresh_undo_buttons(self) -> None:
        self.undo_btn.configure(state="normal" if self._undo_stack else "disabled")
        self.redo_btn.configure(state="normal" if self._redo_stack else "disabled")

    def undo(self, event=None) -> None:
        self._discard_text_input()
        if not self._undo_stack:
            return
        action = self._undo_stack.pop()
        if action["kind"] == "create":
            snaps = [self._snapshot_item(i) for i in action["ids"] if self.canvas.type(i)]
            for item_id in action["ids"]:
                self.canvas.delete(item_id)
            self._redo_stack.append({"kind": "create", "snaps": snaps})
        else:  # "erase"
            new_ids = [self._recreate_item(s) for s in action["snaps"]]
            self._redo_stack.append({"kind": "erase", "ids": new_ids})
        self._refresh_undo_buttons()

    def redo(self, event=None) -> None:
        self._discard_text_input()
        if not self._redo_stack:
            return
        action = self._redo_stack.pop()
        if action["kind"] == "create":
            new_ids = [self._recreate_item(s) for s in action["snaps"]]
            self._undo_stack.append({"kind": "create", "ids": new_ids})
        else:  # "erase"
            snaps = [self._snapshot_item(i) for i in action["ids"]]
            for item_id in action["ids"]:
                self.canvas.delete(item_id)
            self._undo_stack.append({"kind": "erase", "snaps": snaps})
        self._refresh_undo_buttons()

    def _clear_board(self) -> None:
        self._discard_text_input()
        real_items = [i for i in self.canvas.find_all() if "watermark" not in self.canvas.gettags(i)]
        if not real_items:
            return
        snaps = [self._snapshot_item(i) for i in real_items]
        for i in real_items:
            self.canvas.delete(i)
        self._push_undo({"kind": "erase", "snaps": snaps})

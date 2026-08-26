"""A syntax-highlighted, line-numbered Python editor widget with no window
chrome — reused for the main solution editor, the refactored-code viewer,
and any other panel that needs to show Python code."""

from __future__ import annotations

import re
import tkinter as tk

import customtkinter as ctk

from theme import (
    ACCENT, BORDER, CARET, CODE_BRACKET_MATCH, CODE_COMMENT, CODE_FUNC, CODE_INDENT_GUIDE,
    CODE_KEYWORD, CODE_NUMBER, CODE_STRING, CURRENT_LINE, EDITOR_BG, EDITOR_CHROME, FAINT, RED,
    RED_SOFT, SCROLLBAR_THUMB, SCROLLBAR_THUMB_HOVER, SELECTION_BG, TEXT, YELLOW, YELLOW_SOFT,
)

_BRACKETS = {"(": ")", "[": "]", "{": "}"}
_BRACKETS_REV = {v: k for k, v in _BRACKETS.items()}

_PY_KEYWORDS = (
    r"\b(False|None|True|and|as|assert|async|await|break|class|continue|def|del|elif|else|"
    r"except|finally|for|from|global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|"
    r"return|try|while|with|yield|self)\b"
)


def configure_highlight_tags(textbox) -> None:
    textbox.tag_config("keyword", foreground=CODE_KEYWORD)
    textbox.tag_config("string", foreground=CODE_STRING)
    textbox.tag_config("comment", foreground=CODE_COMMENT)
    textbox.tag_config("number", foreground=CODE_NUMBER)
    textbox.tag_config("func", foreground=CODE_FUNC)
    textbox.tag_config("currentline", background=CURRENT_LINE)
    textbox.tag_lower("currentline")


def highlight_python(textbox) -> None:
    """Lightweight regex-based Python highlighting (no extra dependencies)."""
    for tag in ("keyword", "string", "comment", "number", "func"):
        textbox.tag_remove(tag, "1.0", "end")

    code = textbox.get("1.0", "end-1c")
    patterns = [
        ("comment", r"#.*"),
        ("string", r"(\"\"\".*?\"\"\"|'''.*?'''|\"[^\"\n]*\"|'[^'\n]*')"),
        ("keyword", _PY_KEYWORDS),
        ("func", r"\bdef\s+(\w+)"),
        ("number", r"\b\d+(\.\d+)?\b"),
    ]
    for tag, pattern in patterns:
        flags = re.DOTALL if tag == "string" else 0
        for match in re.finditer(pattern, code, flags):
            textbox.tag_add(tag, f"1.0+{match.start()}c", f"1.0+{match.end()}c")


class CodeEditor(ctk.CTkFrame):
    """A syntax-highlighted, line-numbered Python editor — no window chrome, just the code."""

    def __init__(
        self,
        parent,
        code_font: ctk.CTkFont,
        ui_font: ctk.CTkFont,
        read_only: bool = False,
        on_change=None,
        on_selection_change=None,
        **kwargs,
    ) -> None:
        super().__init__(parent, fg_color=EDITOR_CHROME, corner_radius=12, border_width=1, border_color=BORDER, **kwargs)
        self.read_only = read_only
        self.on_change = on_change
        self.on_selection_change = on_selection_change
        self._line_count = 1
        self._cursor_text = ""
        self.highlighting_enabled = True

        if "height" in kwargs:
            # Without this, the inner tk.Text widgets' default 24-line height
            # silently overrides the requested height via grid_propagate, no
            # matter what height= was passed to the outer frame.
            self.grid_propagate(False)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        body = ctk.CTkFrame(self, fg_color=EDITOR_BG, corner_radius=0)
        body.grid(row=0, column=0, sticky="nswe", padx=1, pady=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self._code_font_family = code_font.cget("family")
        self._code_font_size = code_font.cget("size")
        self.linenumbers = tk.Text(
            body, width=4, padx=10, pady=12, bg=EDITOR_BG, fg=FAINT, bd=0,
            highlightthickness=0, font=(self._code_font_family, self._code_font_size),
            state="disabled", takefocus=False, cursor="arrow", wrap="none",
        )
        self.linenumbers.tag_configure("right", justify="right")
        self.linenumbers.grid(row=0, column=0, sticky="ns")

        text_state = "disabled" if read_only else "normal"
        self.text = tk.Text(
            body, bg=EDITOR_BG, fg=TEXT, insertbackground=CARET, bd=0, highlightthickness=0,
            font=(code_font.cget("family"), code_font.cget("size")), padx=12, pady=12, wrap="none",
            undo=True, selectbackground=SELECTION_BG, selectforeground=TEXT, state=text_state,
        )
        self.text.grid(row=0, column=1, sticky="nswe")
        configure_highlight_tags(self.text)

        self.vscroll = ctk.CTkScrollbar(
            body, command=self._on_scrollbar, fg_color="transparent",
            button_color=SCROLLBAR_THUMB, button_hover_color=SCROLLBAR_THUMB_HOVER,
        )
        self.vscroll.grid(row=0, column=2, sticky="ns", padx=(0, 2))
        self.text.configure(yscrollcommand=self._on_text_scroll)

        hscroll = ctk.CTkScrollbar(
            body, command=self.text.xview, orientation="horizontal", fg_color="transparent",
            button_color=SCROLLBAR_THUMB, button_hover_color=SCROLLBAR_THUMB_HOVER,
        )
        hscroll.grid(row=1, column=1, sticky="we")
        self.text.configure(xscrollcommand=hscroll.set)

        self.status_label = ctk.CTkLabel(
            body, text="", text_color=FAINT, font=ui_font, anchor="e", fg_color="transparent",
        )
        self.status_label.grid(row=2, column=0, columnspan=3, sticky="we", padx=14, pady=(2, 6))

        if not read_only:
            self.text.bind("<KeyRelease>", self._on_key_release)
            self.text.bind("<ButtonRelease-1>", self._update_cursor)
        self._on_gutter_click = None
        self.linenumbers.bind("<Button-1>", self._handle_gutter_click)
        self._redraw_line_numbers()
        # Skip on_selection_change here: the constructor's caller hasn't
        # finished assigning `self.editor = CodeEditor(...)` yet, so a
        # callback that reaches back into that attribute would fail.
        self._initialized = False
        self._update_cursor()
        self._initialized = True

    # -- scrolling sync --------------------------------------------------

    def _on_text_scroll(self, first, last) -> None:
        self.vscroll.set(first, last)
        self.linenumbers.yview_moveto(first)

    def _on_scrollbar(self, *args) -> None:
        self.text.yview(*args)
        self.linenumbers.yview(*args)

    # -- content -----------------------------------------------------------

    def get_text(self) -> str:
        return self.text.get("1.0", "end-1c")

    def get_selection(self) -> str | None:
        try:
            return self.text.get("sel.first", "sel.last")
        except tk.TclError:
            return None

    def set_text(self, content: str, highlight: bool = True) -> None:
        was_disabled = self.text.cget("state") == "disabled"
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        if highlight and self.highlighting_enabled:
            highlight_python(self.text)
        self._draw_indent_guides()
        self._redraw_line_numbers()
        self._update_cursor()
        if was_disabled or self.read_only:
            self.text.configure(state="disabled")

    def set_highlighting_enabled(self, enabled: bool) -> None:
        self.highlighting_enabled = enabled
        if enabled:
            highlight_python(self.text)
        else:
            for tag in ("keyword", "string", "comment", "number", "func"):
                self.text.tag_remove(tag, "1.0", "end")

    def _on_key_release(self, event=None) -> None:
        if self.highlighting_enabled:
            highlight_python(self.text)
        self._draw_indent_guides()
        self._redraw_line_numbers()
        self._update_cursor()
        if self.on_change:
            self.on_change()

    def _redraw_line_numbers(self) -> None:
        content = self.text.get("1.0", "end-1c")
        n_lines = content.count("\n") + 1
        self._line_count = n_lines
        numbers = "\n".join(str(i) for i in range(1, n_lines + 1))
        self.linenumbers.configure(state="normal")
        self.linenumbers.delete("1.0", "end")
        self.linenumbers.insert("1.0", numbers, ("right",))
        self.linenumbers.configure(state="disabled")
        self._refresh_status_text()

    def _update_cursor(self, event=None) -> None:
        self.text.tag_remove("currentline", "1.0", "end")
        if not self.read_only:
            self.text.tag_add("currentline", "insert linestart", "insert lineend+1c")
            line, col = self.text.index("insert").split(".")
            self._cursor_text = f"Ln {line}, Col {int(col) + 1}"
            self._update_bracket_match()
        self._refresh_status_text()
        if self.on_selection_change and getattr(self, "_initialized", True):
            self.on_selection_change()

    # -- bracket matching --------------------------------------------------

    def _update_bracket_match(self) -> None:
        self.text.tag_configure("bracket_match", background=CODE_BRACKET_MATCH)
        self.text.tag_remove("bracket_match", "1.0", "end")
        pos = self.text.index("insert")
        for probe in (pos, f"{pos}-1c"):
            if self.text.compare(probe, "<", "1.0"):
                continue
            ch = self.text.get(probe, f"{probe}+1c")
            if ch in _BRACKETS or ch in _BRACKETS_REV:
                match_pos = self._find_matching_bracket(probe, ch)
                if match_pos:
                    self.text.tag_add("bracket_match", probe, f"{probe}+1c")
                    self.text.tag_add("bracket_match", match_pos, f"{match_pos}+1c")
                break

    def _find_matching_bracket(self, pos: str, ch: str) -> str | None:
        forward = ch in _BRACKETS
        target_open = ch if forward else _BRACKETS_REV[ch]
        target_close = _BRACKETS[target_open]
        nest_char = target_open if forward else target_close
        hunt_char = target_close if forward else target_open
        depth = 0
        cursor = pos
        limit = 5000  # matches CodeEditor's other soft caps against pathological input
        for _ in range(limit):
            cursor = self.text.index(f"{cursor}+1c" if forward else f"{cursor}-1c")
            if forward and self.text.compare(cursor, ">=", "end-1c"):
                return None
            if not forward and self.text.compare(cursor, "<", "1.0"):
                return None
            c = self.text.get(cursor, f"{cursor}+1c")
            # Brackets inside strings/comments don't count — the syntax
            # highlighter already knows which spans those are.
            tags_here = self.text.tag_names(cursor)
            if "string" in tags_here or "comment" in tags_here:
                continue
            if c == nest_char:
                depth += 1
            elif c == hunt_char:
                if depth == 0:
                    return cursor
                depth -= 1
        return None

    # -- indent guides -------------------------------------------------------

    def _draw_indent_guides(self) -> None:
        self.text.tag_configure("indent_guide", background=CODE_INDENT_GUIDE)
        self.text.tag_remove("indent_guide", "1.0", "end")
        content = self.text.get("1.0", "end-1c")
        for line_no, line in enumerate(content.split("\n"), start=1):
            stripped = line.lstrip(" ")
            indent = len(line) - len(stripped)
            if not stripped or indent < 4:
                continue  # blank/unindented lines: nothing to guide
            for col in range(4, indent, 4):
                self.text.tag_add("indent_guide", f"{line_no}.{col - 1}", f"{line_no}.{col}")
        self.text.tag_lower("indent_guide")

    def _refresh_status_text(self) -> None:
        parts = []
        if self._cursor_text:
            parts.append(self._cursor_text)
        parts.append(f"{self._line_count} line{'s' if self._line_count != 1 else ''}")
        self.status_label.configure(text="   ·   ".join(parts))

    def set_warning_lines(self, line_nos: set[int]) -> None:
        """Flag lines with a subtle tint + amber line number, spell-checker style."""
        self.linenumbers.tag_configure("warn_num", foreground=YELLOW)
        self.linenumbers.tag_remove("warn_num", "1.0", "end")
        self.text.tag_configure("warn_bg", background=YELLOW_SOFT)
        self.text.tag_remove("warn_bg", "1.0", "end")
        for n in line_nos:
            self.linenumbers.tag_add("warn_num", f"{n}.0", f"{n}.end")
            self.text.tag_add("warn_bg", f"{n}.0", f"{n}.0 lineend+1c")
        self.text.tag_lower("warn_bg")
        self.text.tag_lower("currentline")

    def highlight_line(self, line_no: int, tag: str, color: str) -> None:
        """Highlight a single line's background (used by the trace scrubber, etc.)."""
        self.text.tag_config(tag, background=color)
        self.text.tag_remove(tag, "1.0", "end")
        self.text.tag_add(tag, f"{line_no}.0", f"{line_no}.0 lineend+1c")
        self.text.see(f"{line_no}.0")
        # "You are here" gutter cue: bold + accent the line number itself, on
        # top of the background tint, so the current step is unmistakable
        # even at a glance away from the highlighted text.
        self.linenumbers.tag_configure(
            "exec_pos", foreground=ACCENT, font=(self._code_font_family, self._code_font_size, "bold")
        )
        self.linenumbers.tag_remove("exec_pos", "1.0", "end")
        self.linenumbers.tag_add("exec_pos", f"{line_no}.0", f"{line_no}.end")
        self.linenumbers.see(f"{line_no}.0")

    def clear_tag(self, tag: str) -> None:
        self.text.tag_remove(tag, "1.0", "end")

    # -- gutter / breakpoints ------------------------------------------------

    def on_gutter_click(self, callback) -> None:
        """`callback(line_no: int)` fires when the user clicks a line number."""
        self._on_gutter_click = callback

    def _handle_gutter_click(self, event) -> None:
        if self._on_gutter_click is None:
            return
        index = self.linenumbers.index(f"@{event.x},{event.y}")
        line_no = int(index.split(".")[0])
        self._on_gutter_click(line_no)

    def set_breakpoint_lines(self, line_nos: set[int]) -> None:
        """Marks the gutter red for the given lines — a breakpoint dot,
        toggled by clicking a line number (see on_gutter_click)."""
        self.linenumbers.tag_configure("bp_num", foreground=RED)
        self.linenumbers.tag_remove("bp_num", "1.0", "end")
        self.text.tag_configure("bp_bg", background=RED_SOFT)
        self.text.tag_remove("bp_bg", "1.0", "end")
        for n in line_nos:
            self.linenumbers.tag_add("bp_num", f"{n}.0", f"{n}.end")
            self.text.tag_add("bp_bg", f"{n}.0", f"{n}.0 lineend+1c")
        self.text.tag_lower("bp_bg")
        self.text.tag_lower("currentline")

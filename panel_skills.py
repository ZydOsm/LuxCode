"""Skills tab: a spaced-repetition warmup queue plus a skill map — LeetCode's
own topic tags as nodes, colored by how well past analyses scored on them
(tracking pattern mastery, not just raw solve counts)."""

from __future__ import annotations

from datetime import datetime, timezone

import customtkinter as ctk

import history
from theme import (
    BG, BORDER, CARD_BG, CARD_BG_2, FAINT, GREEN, GREEN_SOFT, HOVER_TINT, MUTED, RED, RED_SOFT,
    SCROLLBAR_THUMB, SCROLLBAR_THUMB_HOVER, TEXT, TEXT_DIM, YELLOW, YELLOW_SOFT,
)


class SkillsPanel(ctk.CTkFrame):
    def __init__(self, parent, fonts, on_select_problem, on_switch_profile=None, get_profile_name=None) -> None:
        """`on_select_problem(ProblemSummary)` — jump to a problem in the Editor tab.
        `on_switch_profile()` / `get_profile_name()` — optional, wire these up to
        show which profile's skill history is on screen and let the user switch."""
        super().__init__(parent, fg_color=BG)
        self.fonts = fonts
        self.on_select_problem = on_select_problem
        self.get_profile_name = get_profile_name

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        if on_switch_profile:
            header = ctk.CTkFrame(self, fg_color="transparent")
            header.grid(row=0, column=0, sticky="we", pady=(0, 12))
            self.profile_label = ctk.CTkLabel(header, text="", text_color=MUTED, font=fonts.small)
            self.profile_label.pack(side="left")
            ctk.CTkButton(
                header, text="Switch Profile", width=130, height=28, corner_radius=8,
                fg_color=CARD_BG_2, hover_color=HOVER_TINT, text_color=TEXT_DIM, font=fonts.small,
                command=on_switch_profile,
            ).pack(side="right")
        else:
            self.profile_label = None

        self.scroll = ctk.CTkScrollableFrame(
            self, fg_color=BG, scrollbar_button_color=SCROLLBAR_THUMB, scrollbar_button_hover_color=SCROLLBAR_THUMB_HOVER,
        )
        self.scroll.grid(row=1, column=0, sticky="nswe")
        self.scroll.grid_columnconfigure(0, weight=1)

        self.refresh()

    def refresh(self) -> None:
        if self.profile_label is not None and self.get_profile_name:
            self.profile_label.configure(text=f"Profile: {self.get_profile_name()}")

        for w in self.scroll.winfo_children():
            w.destroy()

        records = history.load()
        due = history.due_for_review(records)
        skills = history.skill_summary(records)

        row = 0
        if not records:
            wrap = ctk.CTkFrame(self.scroll, fg_color="transparent")
            wrap.grid(row=0, column=0, pady=100)
            ctk.CTkLabel(wrap, text="◈", text_color=FAINT, font=ctk.CTkFont(size=30)).pack()
            ctk.CTkLabel(
                wrap, text="Analyze a few submissions and this fills in: a warmup\n"
                           "queue of problems due for review, plus a map of which\n"
                           "topics you're actually strong in.",
                text_color=MUTED, font=self.fonts.body, justify="center",
            ).pack(pady=(10, 0))
            return

        if due:
            due_card = ctk.CTkFrame(self.scroll, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
            due_card.grid(row=row, column=0, sticky="we", pady=(0, 16))
            ctk.CTkLabel(
                due_card, text=f"Warmup: {len(due)} due for review", font=self.fonts.card_title, text_color=TEXT,
            ).pack(anchor="w", padx=20, pady=(18, 4))
            ctk.CTkLabel(
                due_card, text="Spaced repetition: problems you solved well come back less often; "
                               "ones that scored low come back sooner.",
                text_color=MUTED, font=self.fonts.small,
            ).pack(anchor="w", padx=20, pady=(0, 10))
            for rec in due[:8]:
                self._due_row(due_card, rec)
            ctk.CTkLabel(due_card, text="", height=8).pack()
            row += 1

        skill_card = ctk.CTkFrame(self.scroll, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER)
        skill_card.grid(row=row, column=0, sticky="we", pady=(0, 16))
        ctk.CTkLabel(skill_card, text="Skill Map", font=self.fonts.card_title, text_color=TEXT).pack(
            anchor="w", padx=20, pady=(18, 4)
        )
        ctk.CTkLabel(
            skill_card, text="Colored by your average clarity/complexity score on that topic, not just how many you've done.",
            text_color=MUTED, font=self.fonts.small,
        ).pack(anchor="w", padx=20, pady=(0, 8))

        legend = ctk.CTkFrame(skill_card, fg_color="transparent")
        legend.pack(anchor="w", padx=20, pady=(0, 14))
        for label, dot_color in (("< 5.0", RED), ("5.0 – 7.4", YELLOW), ("≥ 7.5", GREEN), ("not scored yet", MUTED)):
            entry = ctk.CTkFrame(legend, fg_color="transparent")
            entry.pack(side="left", padx=(0, 16))
            dot = ctk.CTkFrame(entry, width=8, height=8, corner_radius=4, fg_color=dot_color)
            dot.pack(side="left", pady=1)
            ctk.CTkLabel(entry, text=f" {label}", text_color=MUTED, font=self.fonts.small).pack(side="left")

        tiles_wrap = ctk.CTkFrame(skill_card, fg_color="transparent")
        tiles_wrap.pack(fill="x", padx=20, pady=(0, 18))
        columns = 4
        for c in range(columns):
            tiles_wrap.grid_columnconfigure(c, weight=1)
        ordered = sorted(skills.items(), key=lambda kv: -kv[1]["count"])
        for i, (tag, stats) in enumerate(ordered):
            self._skill_tile(tiles_wrap, tag, stats, row=i // columns, col=i % columns)

    def _due_row(self, parent, rec: history.ProblemRecord) -> None:
        row = ctk.CTkFrame(parent, fg_color=CARD_BG_2, corner_radius=8)
        row.pack(fill="x", padx=20, pady=3)
        ctk.CTkLabel(
            row, text=f"{rec.frontend_id}. {rec.title}", text_color=TEXT, font=self.fonts.small, anchor="w",
        ).pack(side="left", padx=(12, 8), pady=8)
        try:
            due_dt = datetime.fromisoformat(rec.due_at)
            overdue_days = max((datetime.now(timezone.utc) - due_dt).days, 0)
            due_text = f"{overdue_days}d overdue" if overdue_days > 0 else "due today"
        except (TypeError, ValueError):
            due_text = ""
        ctk.CTkLabel(row, text=due_text, text_color=MUTED, font=self.fonts.small).pack(side="right", padx=12)
        ctk.CTkButton(
            row, text="Warm up", width=90, height=26, corner_radius=6, font=self.fonts.small,
            fg_color=CARD_BG, hover_color=HOVER_TINT, text_color=TEXT_DIM,
            command=lambda r=rec: self._start_warmup(r),
        ).pack(side="right", padx=(8, 8))

    def _start_warmup(self, rec: history.ProblemRecord) -> None:
        from leetcode_api import ProblemSummary
        self.on_select_problem(ProblemSummary(
            frontend_id=rec.frontend_id, title=rec.title, title_slug=rec.slug, difficulty=rec.difficulty,
        ))

    def _skill_tile(self, parent, tag: str, stats: dict, row: int, col: int) -> None:
        avg = stats.get("avg_score")
        count = stats["count"]
        if avg is None:
            bg, fg = CARD_BG_2, MUTED
        elif avg >= 7.5:
            bg, fg = GREEN_SOFT, GREEN
        elif avg >= 5:
            bg, fg = YELLOW_SOFT, YELLOW
        else:
            bg, fg = RED_SOFT, RED

        tile = ctk.CTkFrame(parent, fg_color=bg, corner_radius=10)
        tile.grid(row=row, column=col, sticky="w", padx=(0, 10), pady=(0, 10))
        inner = ctk.CTkFrame(tile, fg_color="transparent")
        inner.pack(padx=14, pady=10, anchor="w")
        ctk.CTkLabel(inner, text=tag, text_color=fg, font=self.fonts.small_bold).pack(anchor="w")
        subtitle = f"{count} solved" if avg is None else f"{count} solved · avg {avg:.1f}/10"
        ctk.CTkLabel(inner, text=subtitle, text_color=fg, font=self.fonts.small).pack(anchor="w")

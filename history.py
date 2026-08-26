"""Local persistent history of analyzed problems — powers the skill map and
spaced-repetition warmup suggestions. Stored as a plain JSON file next to
the app (or next to the .exe when packaged); no account, no server, this
machine only."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

_INTERVALS_DAYS = [1, 3, 7, 14, 30, 60]


def _history_path() -> Path:
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return base / "history.json"


@dataclass
class ProblemRecord:
    frontend_id: str
    title: str
    slug: str
    difficulty: str
    topic_tags: list[str] = field(default_factory=list)
    solve_count: int = 0
    last_score: int | None = None
    last_solved: str | None = None  # ISO timestamp
    interval_index: int = 0
    due_at: str | None = None  # ISO timestamp


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load() -> dict[str, ProblemRecord]:
    path = _history_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    records = {}
    for slug, data in raw.items():
        try:
            records[slug] = ProblemRecord(**data)
        except TypeError:
            continue  # skip entries from an incompatible/older schema
    return records


def save(records: dict[str, ProblemRecord]) -> None:
    path = _history_path()
    data = {slug: asdict(r) for slug, r in records.items()}
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass  # history is a nice-to-have, never block the app on a write failure


def record_analysis(
    slug: str, frontend_id: str, title: str, difficulty: str, topic_tags: list[str], score: int,
) -> None:
    records = load()
    rec = records.get(slug) or ProblemRecord(
        frontend_id=frontend_id, title=title, slug=slug, difficulty=difficulty, topic_tags=topic_tags,
    )
    rec.topic_tags = topic_tags
    rec.solve_count += 1
    rec.last_score = score
    rec.last_solved = _now().isoformat()
    # A good score pushes the next review further out (spaced repetition);
    # a poor one resets to the shortest interval so it comes back around soon.
    rec.interval_index = min(rec.interval_index + 1, len(_INTERVALS_DAYS) - 1) if score >= 7 else 0
    days = _INTERVALS_DAYS[rec.interval_index]
    rec.due_at = (_now() + timedelta(days=days)).isoformat()
    records[slug] = rec
    save(records)


def due_for_review(records: dict[str, ProblemRecord] | None = None) -> list[ProblemRecord]:
    records = records if records is not None else load()
    now = _now()
    due = []
    for rec in records.values():
        if not rec.due_at:
            continue
        try:
            due_dt = datetime.fromisoformat(rec.due_at)
        except ValueError:
            continue
        if due_dt <= now:
            due.append(rec)
    due.sort(key=lambda r: r.due_at)
    return due


def skill_summary(records: dict[str, ProblemRecord] | None = None) -> dict[str, dict]:
    """tag -> {count, avg_score}"""
    records = records if records is not None else load()
    summary: dict[str, dict] = {}
    for rec in records.values():
        for tag in rec.topic_tags:
            s = summary.setdefault(tag, {"count": 0, "score_sum": 0, "score_n": 0})
            s["count"] += 1
            if rec.last_score is not None:
                s["score_sum"] += rec.last_score
                s["score_n"] += 1
    for s in summary.values():
        s["avg_score"] = s["score_sum"] / s["score_n"] if s["score_n"] else None
    return summary

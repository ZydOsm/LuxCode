"""Local, private persistence for app-level preferences — theme, motion,
font scale, window geometry, onboarding state. Same pattern as history.py:
one JSON file next to the app, no server, no accounts.

Theme/font-scale changes apply on next launch, not live — theme.py resolves
its color/font constants once at import time (see the comment at the top of
theme.py), and every other module in this app does `from theme import BG,
...` at its own import time, so there is no single place left to "re-push" a
new color into an already-running window's widgets. Reduced-motion is the
one preference that *does* apply live — see theme.set_reduced_motion().
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_base_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
_SETTINGS_PATH = _base_dir / "settings.json"

DEFAULTS: dict[str, Any] = {
    "theme": "dark",  # "dark" | "light" | "high_contrast"
    "reduced_motion": False,
    "font_scale": 1.0,
    "window": None,  # {"x": int, "y": int, "w": int, "h": int} | None
    "onboarded": False,
    "api_key_prompted": False,  # first-run API key setup modal shown at least once
}


def load_settings() -> dict[str, Any]:
    if not _SETTINGS_PATH.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    if isinstance(data, dict):
        merged.update(data)
    return merged


def save_settings(settings: dict[str, Any]) -> None:
    try:
        _SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError:
        pass  # best-effort — a failed preference save shouldn't crash the app


def update_settings(**changes: Any) -> dict[str, Any]:
    settings = load_settings()
    settings.update(changes)
    save_settings(settings)
    return settings

"""Local, private multi-profile support so more than one person can share
one install without mixing skill history — same idea as a streaming app's
profile picker, minus any of the account/sync machinery. Profiles are just
named pointers to separate history.json files (see history.py); there's no
login, no server, nothing leaves this machine."""

from __future__ import annotations

import json
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from history import DEFAULT_PROFILE_ID, GUEST_ID, path_for_profile

_base_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
_PROFILES_PATH = _base_dir / "profiles.json"

AVATAR_COLORS = ["#6e6bf5", "#3ecf8e", "#f2666b", "#f0b93f", "#41b6e6", "#f2789f", "#9b7bf0", "#5fd3bc"]


@dataclass
class Profile:
    id: str
    name: str
    color: str


def _default_profiles() -> list[Profile]:
    # First run after this feature shipped: give the pre-existing, already-
    # populated single-user history.json a home instead of orphaning it.
    return [Profile(id=DEFAULT_PROFILE_ID, name="Player 1", color=AVATAR_COLORS[0])]


def load_profiles() -> list[Profile]:
    if not _PROFILES_PATH.exists():
        return _default_profiles()
    try:
        raw = json.loads(_PROFILES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_profiles()
    profiles = []
    for item in raw:
        try:
            profiles.append(Profile(**item))
        except TypeError:
            continue  # skip entries from an incompatible/older schema
    return profiles or _default_profiles()


def save_profiles(profiles: list[Profile]) -> None:
    try:
        _PROFILES_PATH.write_text(
            json.dumps([asdict(p) for p in profiles], indent=2), encoding="utf-8"
        )
    except OSError:
        pass  # profile list is a nice-to-have, never block the app on a write failure


def create_profile(name: str) -> Profile:
    profiles = load_profiles()
    used_colors = {p.color for p in profiles}
    color = next(
        (c for c in AVATAR_COLORS if c not in used_colors), AVATAR_COLORS[len(profiles) % len(AVATAR_COLORS)]
    )
    profile = Profile(id=uuid.uuid4().hex[:12], name=name, color=color)
    profiles.append(profile)
    save_profiles(profiles)
    return profile


def rename_profile(profile_id: str, new_name: str) -> None:
    profiles = load_profiles()
    for p in profiles:
        if p.id == profile_id:
            p.name = new_name
            break
    save_profiles(profiles)


def delete_profile(profile_id: str) -> None:
    profiles = [p for p in load_profiles() if p.id != profile_id]
    save_profiles(profiles)
    path_for_profile(profile_id).unlink(missing_ok=True)

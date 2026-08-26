"""Local .env-file management for LLM provider API keys — the same file
analyzer.py already reads via python-dotenv at import time. Writing a key
here also sets it directly in os.environ, so it takes effect immediately
(no restart needed), since analyzer.py's os.environ.get(...) calls happen
at request time, not import time.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_base_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
ENV_PATH = _base_dir / ".env"

# Provider display name -> (env var name, model prefix used to route in
# analyzer.call_llm, signup URL). Order matches MODEL_OPTIONS' cheapest-first
# convention in gui.py.
PROVIDERS: dict[str, dict[str, str]] = {
    "Gemini": {
        "env_var": "GEMINI_API_KEY",
        "signup_url": "https://aistudio.google.com/apikey",
    },
    "OpenAI": {
        "env_var": "OPENAI_API_KEY",
        "signup_url": "https://platform.openai.com/api-keys",
    },
    "Anthropic": {
        "env_var": "ANTHROPIC_API_KEY",
        "signup_url": "https://console.anthropic.com/settings/keys",
    },
}


def read_env_file() -> dict[str, str]:
    """Parses .env into a dict. Comments and blank lines are dropped —
    write_key() rewrites the file from this dict plus one change, so this
    only expects plain KEY=VALUE lines, which is all this app ever writes."""
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def write_key(env_var_name: str, value: str) -> None:
    """Updates one KEY=VALUE line in-place, preserving every other line
    (comments, blank lines, other keys) untouched — a naive "parse into a
    dict, rewrite the whole file" approach would silently delete comments
    like the ones in .env.example, which matters for a file users hand-edit."""
    existing_lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    new_line = f"{env_var_name}={value}"
    replaced = False
    output_lines = []
    for line in existing_lines:
        stripped = line.strip()
        if not stripped.startswith("#") and "=" in stripped and stripped.split("=", 1)[0].strip() == env_var_name:
            if value:
                output_lines.append(new_line)
            replaced = True  # drop the line entirely when value is empty (clearing a key)
        else:
            output_lines.append(line)
    if not replaced and value:
        output_lines.append(new_line)
    ENV_PATH.write_text("\n".join(output_lines) + ("\n" if output_lines else ""), encoding="utf-8")
    if value:
        os.environ[env_var_name] = value
    else:
        os.environ.pop(env_var_name, None)


def has_key(env_var_name: str) -> bool:
    return bool(os.environ.get(env_var_name) or read_env_file().get(env_var_name))


def any_key_configured() -> bool:
    return any(has_key(p["env_var"]) for p in PROVIDERS.values())


def get_key(env_var_name: str) -> str:
    return os.environ.get(env_var_name) or read_env_file().get(env_var_name) or ""

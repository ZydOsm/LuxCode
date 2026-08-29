"""HTTP client for Codeforces — the second question provider alongside
LeetCode. Exposes the same shape as leetcode_api.LeetCodeClient
(list_problems/get_problem/close, returning the same ProblemSummary/
ProblemMetadata dataclasses) so gui.py can treat either provider identically.

Two honest limits, both worth stating up front rather than papering over:

1. Codeforces problems are stdin/stdout competitive-programming problems,
   not "implement this function" ones — there's no function signature or
   example testcases to auto-parse the way LeetCode's GraphQL API hands
   them over, so get_problem() always returns empty param_names/
   param_types/function_name/example_testcases. Trace, Tests, Fuzz, and the
   Performance Race already have existing "couldn't find a function"/
   "couldn't auto-detect example input" fallback messaging for exactly this
   shape of metadata (see panel_trace.py, panel_tests.py, and gui.py's
   fuzz/race handlers) — nothing further needed there.

2. Codeforces' public API (codeforces.com/apiHelp) only exposes problem
   metadata — name, rating, tags — never statement text; there's no
   endpoint for that. The problem pages that DO have the statement sit
   behind Codeforces' own bot-check (a JS challenge screen, "Please wait,
   your browser is being checked..."), on the main domain and on every
   mirror (m1/m2/m3.codeforces.com) alike. That's a deliberate anti-bot
   measure, not a technical gap to route around — this client doesn't
   attempt to solve it (no headless browser, no challenge-solving), so
   content_text is built from the metadata the API does give us, with a
   pointer to the problem's real URL for the full statement. See
   gui.py's provider note (_update_provider_note) for how this is
   surfaced to the user rather than silently degraded.
"""

from __future__ import annotations

import re

import httpx

from leetcode_api import ProblemMetadata, ProblemSummary

_API_URL = "https://codeforces.com/api/problemset.problems"
_PROBLEM_URL = "https://codeforces.com/problemset/problem/{contest_id}/{index}"

_HEADERS = {"User-Agent": "LuxCode/1.0 (+https://github.com/ZydOsm/LuxCode)"}

_CODE_RE = re.compile(r"^(\d+)([A-Za-z]\d*)$")


class CodeforcesAPIError(RuntimeError):
    """Raised when the Codeforces API cannot resolve or fetch a problem."""


def _rating_to_difficulty(rating: int | None) -> str:
    if rating is None:
        return "Unrated"
    if rating < 1400:
        return "Easy"
    if rating < 2100:
        return "Medium"
    return "Hard"


class CodeforcesClient:
    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.Client(headers=_HEADERS, timeout=timeout, follow_redirects=True)
        # code ("1500C2") -> {"name", "rating", "tags"}, populated by
        # list_problems() — the only source of this data, since the
        # per-problem statement page isn't reachable (see module docstring).
        self._catalog: dict[str, dict] = {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CodeforcesClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def list_problems(self) -> list[ProblemSummary]:
        try:
            response = self._client.get(_API_URL)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CodeforcesAPIError(f"Failed to reach the Codeforces API: {exc}") from exc

        payload = response.json()
        if payload.get("status") != "OK":
            raise CodeforcesAPIError(str(payload.get("comment") or "Codeforces API returned an error."))

        summaries = []
        for p in payload["result"]["problems"]:
            contest_id, index = p.get("contestId"), p.get("index")
            # A handful of old special-round problems use a purely numeric
            # index ("921" + "01") instead of the usual "A"/"B2" — skip
            # those rather than guessing where contestId ends and index
            # starts in a code that's all digits.
            if contest_id is None or not index or not re.match(r"^[A-Za-z]\d*$", index):
                continue
            code = f"{contest_id}{index}"
            self._catalog[code] = {"name": p.get("name", code), "rating": p.get("rating"), "tags": p.get("tags", [])}
            summaries.append(ProblemSummary(
                frontend_id=code, title=p.get("name", code), title_slug=code,
                difficulty=_rating_to_difficulty(p.get("rating")),
            ))
        summaries.sort(key=lambda s: int(_CODE_RE.match(s.frontend_id).group(1)), reverse=True)
        return summaries

    def resolve_slug(self, identifier: str) -> str:
        return identifier.strip().upper().replace(" ", "")

    def get_problem(self, identifier: str) -> ProblemMetadata:
        code = self.resolve_slug(identifier)
        match = _CODE_RE.match(code)
        if not match:
            raise CodeforcesAPIError(f"'{identifier}' doesn't look like a Codeforces problem code (e.g. '4A').")
        contest_id, index = match.group(1), match.group(2)

        cached = self._catalog.get(code)
        if cached is None:
            raise CodeforcesAPIError(
                f"No cached data for {code} — call list_problems() first to load the Codeforces catalog."
            )

        url = _PROBLEM_URL.format(contest_id=contest_id, index=index)
        content_text = (
            f"{cached['name']}\n"
            f"Rating: {cached['rating'] if cached['rating'] is not None else 'unrated'}\n"
            f"Tags: {', '.join(cached['tags']) or 'none listed'}\n\n"
            "The full statement isn't available here — Codeforces' public API only exposes "
            "problem metadata (name/rating/tags), and the problem page itself sits behind a "
            "bot-check this app doesn't attempt to solve. Open it directly to read it:\n"
            f"{url}"
        )

        return ProblemMetadata(
            question_id=code, frontend_id=code, title=cached["name"], title_slug=code,
            difficulty=_rating_to_difficulty(cached["rating"]),
            content_html=content_text, content_text=content_text,
            topic_tags=cached["tags"], hints=[], example_testcases="",
            param_names=[], param_types=[], function_name="",
        )

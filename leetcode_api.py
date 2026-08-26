"""GraphQL client for resolving and fetching LeetCode problem metadata."""

from __future__ import annotations

import concurrent.futures
import json
import re
from dataclasses import dataclass

import httpx

LEETCODE_GRAPHQL_URL = "https://leetcode.com/graphql"

_HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://leetcode.com",
    "User-Agent": "luxcode/1.0",
}

_PROBLEMSET_QUERY = """
query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
  problemsetQuestionList: questionList(
    categorySlug: $categorySlug
    limit: $limit
    skip: $skip
    filters: $filters
  ) {
    total: totalNum
    questions: data {
      difficulty
      frontendQuestionId: questionFrontendId
      title
      titleSlug
    }
  }
}
"""

_QUESTION_QUERY = """
query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionId
    questionFrontendId
    title
    titleSlug
    content
    difficulty
    exampleTestcases
    metaData
    topicTags {
      name
      slug
    }
    hints
  }
}
"""

_PAGE_SIZE = 100
_MAX_PAGES = 60  # covers the full LeetCode problem set


class LeetCodeAPIError(RuntimeError):
    """Raised when the LeetCode GraphQL API cannot resolve or fetch a problem."""


@dataclass
class ProblemSummary:
    frontend_id: str
    title: str
    title_slug: str
    difficulty: str


@dataclass
class ProblemMetadata:
    question_id: str
    frontend_id: str
    title: str
    title_slug: str
    difficulty: str
    content_html: str
    content_text: str
    topic_tags: list[str]
    hints: list[str]
    example_testcases: str
    param_names: list[str]
    param_types: list[str]
    function_name: str


class LeetCodeClient:
    """Thin wrapper around the public LeetCode GraphQL endpoint."""

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.Client(headers=_HEADERS, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "LeetCodeClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _post(self, query: str, variables: dict) -> dict:
        try:
            response = self._client.post(
                LEETCODE_GRAPHQL_URL, json={"query": query, "variables": variables}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LeetCodeAPIError(f"Failed to reach LeetCode API: {exc}") from exc

        payload = response.json()
        if payload.get("errors"):
            raise LeetCodeAPIError(str(payload["errors"]))
        return payload["data"]

    def list_problems(self) -> list[ProblemSummary]:
        """Fetch the full LeetCode problem catalog (number, title, slug, difficulty).

        Used to populate a pick-list in the UI so users select a real problem
        instead of typing a number/slug that might not exist.
        """
        first = self._post(
            _PROBLEMSET_QUERY, {"categorySlug": "", "skip": 0, "limit": _PAGE_SIZE, "filters": {}}
        )
        listing = first["problemsetQuestionList"]
        total = listing["total"]
        questions = list(listing["questions"])

        remaining_skips = list(range(_PAGE_SIZE, total, _PAGE_SIZE))

        def fetch_page(skip: int) -> list[dict]:
            data = self._post(
                _PROBLEMSET_QUERY,
                {"categorySlug": "", "skip": skip, "limit": _PAGE_SIZE, "filters": {}},
            )
            return data["problemsetQuestionList"]["questions"]

        if remaining_skips:
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                for page in pool.map(fetch_page, remaining_skips):
                    questions.extend(page)

        summaries = [
            ProblemSummary(
                frontend_id=q["frontendQuestionId"],
                title=q["title"],
                title_slug=q["titleSlug"],
                difficulty=q["difficulty"],
            )
            for q in questions
        ]
        summaries.sort(key=lambda s: int(s.frontend_id) if s.frontend_id.isdigit() else 10**9)
        return summaries

    def resolve_slug(self, identifier: str) -> str:
        """Accept either a problem number ('1') or a slug ('two-sum')."""
        identifier = identifier.strip()
        if re.fullmatch(r"\d+", identifier):
            return self._slug_for_frontend_id(identifier)
        return identifier.lower().replace(" ", "-")

    def _slug_for_frontend_id(self, frontend_id: str) -> str:
        skip = 0
        for _ in range(_MAX_PAGES):
            data = self._post(
                _PROBLEMSET_QUERY,
                {"categorySlug": "", "skip": skip, "limit": _PAGE_SIZE, "filters": {}},
            )
            questions = data["problemsetQuestionList"]["questions"]
            if not questions:
                break
            for question in questions:
                if question["frontendQuestionId"] == frontend_id:
                    return question["titleSlug"]
            skip += _PAGE_SIZE
        raise LeetCodeAPIError(f"Could not find a LeetCode problem numbered {frontend_id}")

    def get_problem(self, identifier: str) -> ProblemMetadata:
        slug = self.resolve_slug(identifier)
        data = self._post(_QUESTION_QUERY, {"titleSlug": slug})
        question = data.get("question")
        if question is None:
            raise LeetCodeAPIError(f"No LeetCode problem found for '{identifier}'")

        content_html = question.get("content") or ""
        param_names: list[str] = []
        param_types: list[str] = []
        function_name = ""
        meta_raw = question.get("metaData")
        if meta_raw:
            try:
                meta = json.loads(meta_raw)
                params = meta.get("params", [])
                param_names = [p["name"] for p in params]
                param_types = [p.get("type", "") for p in params]
                function_name = meta.get("name", "")
            except (json.JSONDecodeError, KeyError, TypeError):
                param_names = []
                param_types = []

        return ProblemMetadata(
            question_id=question["questionId"],
            frontend_id=question["questionFrontendId"],
            title=question["title"],
            title_slug=question["titleSlug"],
            difficulty=question["difficulty"],
            content_html=content_html,
            content_text=_strip_html(content_html),
            topic_tags=[tag["name"] for tag in question.get("topicTags", [])],
            hints=question.get("hints", []),
            example_testcases=question.get("exampleTestcases") or "",
            param_names=param_names,
            param_types=param_types,
            function_name=function_name,
        )


def _strip_html(html: str) -> str:
    # Do this before the generic tag-strip below, or "10<sup>4</sup>" collapses
    # into the misleading plain number "104" instead of the exponent "10^4".
    text = re.sub(r"<sup>\s*(-?\d+)\s*</sup>", r"^\1", html)
    text = re.sub(r"<[^>]+>", "", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

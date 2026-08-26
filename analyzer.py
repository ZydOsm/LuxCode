"""Pydantic response schema and LLM prompt orchestration for submission review."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

from leetcode_api import ProblemMetadata

# Load API keys from a .env file next to the script (or next to the .exe when
# packaged with PyInstaller), so the GUI works when double-clicked without
# needing an environment variable set up in a terminal first.
_base_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
load_dotenv(_base_dir / ".env")


class ComplexityAssessment(BaseModel):
    big_o: str = Field(..., description="Big-O notation, e.g. 'O(n log n)'")
    justification: str = Field(..., description="Short justification for this complexity")


class ReviewResult(BaseModel):
    user_time_complexity: ComplexityAssessment
    user_space_complexity: ComplexityAssessment
    optimal_time_complexity: ComplexityAssessment
    optimal_space_complexity: ComplexityAssessment
    structure_and_clarity_score: int = Field(..., ge=1, le=10)
    structure_and_clarity_commentary: str = Field(
        ..., description="Commentary on naming, PEP 8, and modularity"
    )
    redundancies: list[str] = Field(
        default_factory=list,
        description="Unnecessary variables, redundant logic, or suboptimal algorithmic choices",
    )
    refactored_code: str = Field(
        ..., description="Cleaner, pythonic, optimal version of the submission with inline comments"
    )


class AnalyzerError(RuntimeError):
    """Raised when the LLM call fails or its response cannot be validated."""


_SYSTEM_PROMPT = """You are a senior algorithms interviewer and Python code reviewer.
Given a LeetCode problem statement and a candidate's Python submission, evaluate:
- The actual (user) time/space complexity of the submitted code, with a short justification.
- The optimal achievable time/space complexity for this problem given its constraints.
- The structure, clarity, naming, PEP 8 compliance, and modularity of the code (1-10 scale).
- Concrete redundancies: unnecessary variables, redundant logic, or suboptimal algorithmic choices.
- A refactored, idiomatic, optimal version of the solution with inline comments on key steps.

Respond with ONLY a single JSON object matching the required schema. Do not include markdown
fences, headings, or any prose outside the JSON object."""

# A compact hand-written example beats a full model_json_schema() dump here —
# the auto-generated schema runs ~1900 chars; this is ~350, and small/cheap
# models follow a concrete example just as reliably as a verbose spec.
_COMPACT_FORMAT = """{
  "user_time_complexity": {"big_o": "O(...)", "justification": "..."},
  "user_space_complexity": {"big_o": "O(...)", "justification": "..."},
  "optimal_time_complexity": {"big_o": "O(...)", "justification": "..."},
  "optimal_space_complexity": {"big_o": "O(...)", "justification": "..."},
  "structure_and_clarity_score": <int 1-10>,
  "structure_and_clarity_commentary": "...",
  "redundancies": ["...", "..."],
  "refactored_code": "..."
}"""


def _build_user_prompt(problem: ProblemMetadata, code: str) -> str:
    tags = ", ".join(problem.topic_tags) or "unknown"
    return f"""# LeetCode Problem {problem.frontend_id}: {problem.title}
Difficulty: {problem.difficulty}
Topics: {tags}

## Problem statement
{problem.content_text[:4000]}

## Candidate submission (Python)
```python
{code}
```

Return ONLY a JSON object in exactly this shape (fill in the "..." values):
{_COMPACT_FORMAT}
"""


def analyze_submission(problem: ProblemMetadata, code: str, model: str) -> ReviewResult:
    user_prompt = _build_user_prompt(problem, code)
    raw = call_llm(model, _SYSTEM_PROMPT, user_prompt)
    return _parse_response(raw)


def call_llm(model: str, system_prompt: str, user_prompt: str) -> str:
    """Dispatch a single JSON-mode LLM call to whichever provider `model` names."""
    if model.startswith(("gpt", "o1", "o3", "o4")):
        return _call_openai(model, system_prompt, user_prompt)
    elif model.startswith("claude"):
        return _call_anthropic(model, system_prompt, user_prompt)
    elif model.startswith("gemini"):
        return _call_gemini(model, system_prompt, user_prompt)
    raise AnalyzerError(
        f"Unrecognized model '{model}'. Expected a name starting with "
        "'gemini' (Google), 'gpt'/'o1'/'o3'/'o4' (OpenAI), or 'claude' (Anthropic)."
    )


def _call_openai(model: str, system_prompt: str, user_prompt: str) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AnalyzerError(
            "The 'openai' package is required for OpenAI models. Install it with: pip install openai"
        ) from exc

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise AnalyzerError("OPENAI_API_KEY environment variable is not set.")

    client = OpenAI(api_key=api_key)
    try:
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
    except Exception as exc:  # openai raises its own exception hierarchy
        raise AnalyzerError(f"OpenAI API call failed: {exc}") from exc

    return response.choices[0].message.content or ""


def _call_anthropic(model: str, system_prompt: str, user_prompt: str) -> str:
    try:
        import anthropic
    except ImportError as exc:
        raise AnalyzerError(
            "The 'anthropic' package is required for Claude models. Install it with: pip install anthropic"
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise AnalyzerError("ANTHROPIC_API_KEY environment variable is not set.")

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            temperature=0.2,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:  # anthropic raises its own exception hierarchy
        raise AnalyzerError(f"Anthropic API call failed: {exc}") from exc

    return "".join(block.text for block in response.content if block.type == "text")


def _call_gemini(model: str, system_prompt: str, user_prompt: str) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise AnalyzerError(
            "The 'google-genai' package is required for Gemini models. "
            "Install it with: pip install google-genai"
        ) from exc

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise AnalyzerError("GEMINI_API_KEY environment variable is not set.")

    client = genai.Client(api_key=api_key)
    contents = f"{system_prompt}\n\n{user_prompt}"

    def _generate(with_minimal_thinking: bool):
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
            thinking_config=(
                types.ThinkingConfig(thinking_level="minimal")
                if with_minimal_thinking
                else None
            ),
        )
        return client.models.generate_content(model=model, contents=contents, config=config)

    try:
        # thinking_level=minimal keeps reasoning tokens (and cost) to a minimum;
        # older Gemini models don't support it, so fall back if the call rejects it.
        try:
            response = _generate(with_minimal_thinking=True)
        except Exception:
            response = _generate(with_minimal_thinking=False)
    except Exception as exc:
        raise AnalyzerError(f"Gemini API call failed: {exc}") from exc

    return response.text or ""


def _extract_json(raw: str):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AnalyzerError(
            f"LLM response was not valid JSON: {exc}\nRaw response:\n{raw[:1000]}"
        ) from exc


def _parse_response(raw: str) -> ReviewResult:
    data = _extract_json(raw)
    try:
        return ReviewResult.model_validate(data)
    except ValidationError as exc:
        raise AnalyzerError(f"LLM response did not match the expected schema:\n{exc}") from exc


_HINTS_SYSTEM_PROMPT = """You are a Socratic coding tutor. Given a LeetCode problem, produce exactly
4 progressively-revealing hints, each one tier more specific than the last:
1. A high-level conceptual nudge (what category of idea applies — no algorithm name).
2. The specific technique/algorithm/pattern to use, in one sentence — still no code.
3. A pseudocode-level outline of the approach (a few short steps, no real code).
4. A near-solution: the key implementation detail or trick that unlocks it, in one or two
   sentences — still not full code, so there is always something left to write yourself.
Respond with ONLY a JSON array of exactly 4 strings, no markdown fences, no other keys."""


_REFACTOR_SYSTEM_PROMPT = """You are a senior Python code reviewer. Given a snippet selected from a
larger function, propose exactly 3 alternative ways to write JUST that snippet — idiomatic,
lower-space, or otherwise cleaner. Each alternative must be a drop-in replacement for the
selected snippet only (same indentation level, same variables available), not a rewrite of
the whole function. Respond with ONLY a JSON array of exactly 3 objects, each with keys
"label" (a short 2-5 word name for the alternative), "code" (the replacement snippet, no
markdown fences), and "why" (one short sentence). No other keys, no prose outside the JSON."""


def suggest_alternatives(selected_code: str, full_code: str, model: str) -> list[dict]:
    prompt = f"""## Full function (for context only — do not rewrite this)
```python
{full_code}
```

## Selected snippet to replace
```python
{selected_code}
```

Return a JSON array of exactly 3 alternative snippets for the SELECTED portion only."""
    raw = call_llm(model, _REFACTOR_SYSTEM_PROMPT, prompt)
    data = _extract_json(raw)
    if not isinstance(data, list) or not all(isinstance(x, dict) and "code" in x for x in data):
        raise AnalyzerError("LLM refactor response did not match the expected shape.")
    return data


_TRANSPILE_SYSTEM_PROMPT = """You translate a Python function into idiomatic, correct {language} that
solves the same problem the same way (same algorithm/complexity, not a different approach). After
the code, note 2-4 concrete low-level performance trade-offs versus the Python version — memory
layout, allocation behavior, runtime overhead, whatever is genuinely relevant for THIS language pair.
Respond with ONLY a JSON object: {{"code": "...", "notes": "..."}}. No markdown fences, no other keys.
This is an LLM-generated translation for educational comparison, not a verified/compiled result —
do not claim it has been run or benchmarked."""


def transpile(code: str, target_language: str, model: str) -> dict:
    system_prompt = _TRANSPILE_SYSTEM_PROMPT.format(language=target_language)
    prompt = f"""## Python source
```python
{code}
```

Translate this to {target_language}. Return the JSON object described in your instructions."""
    raw = call_llm(model, system_prompt, prompt)
    data = _extract_json(raw)
    if not isinstance(data, dict) or "code" not in data:
        raise AnalyzerError("LLM transpile response did not match the expected shape.")
    return data


_EXPLAIN_EXCEPTION_SYSTEM_PROMPT = """You are a debugging assistant. Given a Python function, the
exception it raised, and the local variable state at the moment it failed, explain in 2-4 sentences
why THIS SPECIFIC input triggered THIS SPECIFIC exception — reference the actual variable values
given, not generic advice. End with one concrete sentence on the smallest fix. Respond with ONLY a
JSON object: {"explanation": "..."}. No markdown fences, no other keys."""


def explain_exception(code: str, error: str, locals_repr: dict[str, str], model: str) -> str:
    """One-shot LLM explanation of a captured exception, given the exact local
    variable state at the point of failure (from the Trace tab's recorded steps)."""
    state = "\n".join(f"{k} = {v}" for k, v in locals_repr.items()) or "(no local variables)"
    prompt = f"""## Solution
```python
{code}
```

## Exception raised
{error}

## Local variables at the point of failure
{state}

Return the JSON object described in your instructions."""
    raw = call_llm(model, _EXPLAIN_EXCEPTION_SYSTEM_PROMPT, prompt)
    data = _extract_json(raw)
    if not isinstance(data, dict) or "explanation" not in data:
        raise AnalyzerError("LLM exception-explanation response did not match the expected shape.")
    return data["explanation"]


def generate_hints(problem: ProblemMetadata, model: str) -> list[str]:
    tags = ", ".join(problem.topic_tags) or "unknown"
    prompt = f"""# LeetCode Problem {problem.frontend_id}: {problem.title}
Topics: {tags}

## Problem statement
{problem.content_text[:3000]}

Return a JSON array of exactly 4 hint strings, tier 1 (vaguest) to tier 4 (most specific)."""
    raw = call_llm(model, _HINTS_SYSTEM_PROMPT, prompt)
    data = _extract_json(raw)
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise AnalyzerError("LLM hint response was not a JSON array of strings.")
    return data

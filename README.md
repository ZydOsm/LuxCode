# LuxCode

### *LeetCode Premium — on steroids*

A desktop app that fetches a LeetCode problem straight from LeetCode's own API, runs your Python
solution through an LLM code review, and then goes well past that: it actually **executes** your
code (line-by-line tracing, real timing, real memory) to back up what it tells you with facts
instead of just LLM narration. A full interactive debugger, a regression suite, spaced-repetition
practice tracking, and a code editor that doesn't feel like an afterthought — the LeetCode workflow
Premium never gave you.

Built with CustomTkinter. Uses Gemini by default (`gemini-3.5-flash-lite` — picked specifically to
keep token usage and cost minimal), with OpenAI and Anthropic also supported.

## Setup

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Run it:

   ```bash
   py gui.py
   ```

   The first time it launches with no key configured, it asks you to pick a provider and paste an
   API key — no manual `.env` editing needed. Get a Gemini key (the cheapest option) at
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey); the modal links straight to
   whichever provider you pick. You can skip this and add a key later from **Settings (⚙) → API
   Keys**, which manages all three providers (Gemini/OpenAI/Anthropic) with masked entries and a
   configured/not-set indicator per key.

   Keys are written to a `.env` file next to the app (same mechanism `.env.example` describes, for
   anyone who'd rather hand-edit it directly) and take effect immediately — no restart needed.

   A CLI is also available for a single one-shot review without the UI (still reads the same
   `.env`):

   ```bash
   py cli.py -p 1 -f solution.py
   ```

## What it does

Pick a problem from the searchable list (scraped live from LeetCode — no typing a number/slug
that might not exist), paste your solution, and it's analyzed against the official problem
statement.

### Editor

- Line-numbered, syntax-highlighted Python editor
- **AST anti-pattern HUD** — flags `x in list` inside loops, `range(len(x))`, string concatenation
  in loops, live as you type (pure static analysis via Python's `ast` module, no LLM call)
- **Constraint-to-complexity predictor** — parses the problem's stated bounds (e.g. `n ≤ 10⁵`) and
  tells you which Big-O classes are actually fast enough
- **Code stencils** — one-click boilerplate for binary search, tries, union-find, BFS/DFS,
  monotonic stacks, 1D/2D DP
- **Blindfold mode** — toggles syntax highlighting off, for practicing raw recall
- **Socratic hints** — a 4-tier slider from a conceptual nudge to a near-solution, so you only see
  as much help as you ask for
- **Refactor Selection** — select any snippet, get 3 alternative implementations with one-click
  replace

### Trace

Runs your own solution — on your own machine, exactly like running `python solution.py` yourself,
just with a trace hook attached (`sys.settrace` + `tracemalloc`, no sandboxing) — against an
auto-detected example input, then lets you scrub through it step by step:

- Timeline scrubber with play/pause, like a media player
- **Step controls** — step into/back one recorded event, step over a call without descending into
  it, step out until the current call returns, or continue straight to the next breakpoint
- **Breakpoints** — click a line number to set one; add an optional condition (e.g. `i > 3`),
  evaluated against that step's real local variables
- **Watch expressions** — any Python expression (`len(seen)`, `nums[i]`), re-evaluated live as you
  scrub, against a small safe set of builtins (no file/import/exec access)
- **Call stack inspector** — the real, live call stack at the current step, innermost frame first
- **Variable history & mutation tracking** — click a variable for its full changelog across the
  trace; container variables (list/dict/set) show a one-line diff of what changed since the
  previous step
- **Exception debugging** — jump straight to the step where an unhandled exception was raised, and
  optionally ask the LLM to explain why that specific input triggered it
- Variables panel (changed values highlighted)
- Recursion tree (real call tree, active path highlighted)
- DP grid visualizer (auto-detected 2D arrays, cells colored as they update)
- Memory sparkline (real `tracemalloc` data)

### Tests

One-click regression suite, run entirely against your own solution on your own machine:

- **Official Examples** — reruns *every* example from the problem statement (not just the first
  one the Trace tab uses), comparing against an expected output parsed best-effort from the
  problem's prose; a case that ran fine but couldn't be confidently matched is marked "ran" rather
  than guessed pass/fail
- **Determinism Check** — runs the same input 5 times and flags it if the output differs between
  runs (hidden reliance on set/dict iteration order, uninitialized state, etc.)
- **Boundary Cases** — a curated set of edge cases (empty, single-element, max-size, zero,
  negative — one parameter varied at a time) rather than random fuzzing, surfacing any that crash
- **Shrink to Minimal Failing Input** — on any crash (example or boundary), one click runs greedy
  delta-debugging to reduce the failing input down to the smallest one that still reproduces it

### Report

The core LLM review: time/space complexity (yours vs. optimal), a structure & clarity score, a
list of concrete redundancies, and a refactored solution — plus:

- **Performance Race** — runs your code and the refactored suggestion on a large synthetic input
  at the problem's own scale, timing both for real (not estimated)
- **Counter-Example Fuzzer** — generates random inputs matching the problem's parameter types and
  looks for ones that crash or time out your solution
- **Transpilation Inspector** — translates your solution to C++, Rust, or Go with real low-level
  tradeoff commentary

### Skills

Local, private history of what you've analyzed:

- **Warmup queue** — spaced repetition; problems you scored well on come back less often, ones you
  scored poorly on come back sooner
- **Skill map** — LeetCode topic tags colored by your *average score* on that topic, not just how
  many you've solved

### Whiteboard

A blank scratchpad (freehand drawing, for sketching structures before touching the keyboard) plus
a countdown timer, for simulating interview pressure.

## Choosing a model

The model dropdown covers Gemini, OpenAI, and Anthropic. `gemini-3.5-flash-lite` is the default
and cheapest option (minimal-thinking mode, lowest token usage) — the other models are there if
you want higher-quality analysis and don't mind the extra cost.

## Settings (⚙) and shortcuts

The gear icon next to the app name opens a small settings panel:

- **API Keys** — one row per provider (Gemini/OpenAI/Anthropic), each showing whether a key is
  configured, with a masked entry and a show/hide toggle. Saves immediately to `.env` and to the
  running process — no restart needed, unlike the theme/font settings below.
- **Theme** — Dark, Light, or High Contrast. Every color in the app resolves once at startup from
  `theme.py`; there's no live re-paint, so a theme change applies on next launch, not immediately.
- **Font size** — an 80–140% scale applied to every font in the app. Also next-launch.
- **Reduced motion** — the one setting that *is* live: flips instantly, no restart needed, and
  makes every animation (card entrances, number roll-ups, gauges) jump straight to its end state.

The ✨ icon opens a short changelog. Window position/size persist across launches automatically.

In the **Trace** tab: `Space` play/pauses the scrubber, `←`/`→` step one recorded event,
`Shift+←`/`Shift+→` step out/over — all inert while you're typing in a text field.

Preferences live in a local `settings.json` next to the app — same pattern as `history.json`,
nothing sent anywhere.

## Building a standalone binary

```bash
./build.sh     # macOS/Linux
./build.ps1    # Windows
```

Produces `dist/leetcode-eval` (CLI) and `dist/leetcode-eval-gui` (windowed, no console). Put your
`.env` file next to the built executable — it's read from disk at runtime, not bundled in.

## Notes and honest limitations

- **LeetCode has no public API** — this uses the same unauthenticated GraphQL endpoint the
  website's frontend uses. It works today but could change without notice.
- **Auto-detected example inputs are best-effort.** LeetCode has no per-problem test harness, so
  the Trace/Race/Fuzz features parse the problem's own example testcases and parameter types;
  unusual input shapes (custom classes like `TreeNode`/`ListNode`, multi-example ambiguity) may
  fail to parse. When that happens, the feature says so rather than guessing.
- **The Fuzzer finds crashes and timeouts, not "wrong answers."** There's no verified reference
  solution to diff against — the "optimal" solution shown in the Report is itself LLM-generated,
  not guaranteed correct — so fuzzing deliberately stays scoped to unambiguous failures.
- **The Transpilation Inspector is a translation, not a compiler.** The C++/Rust/Go output has not
  been compiled or benchmarked; treat the code and its commentary as a reference, not verified fact.
- **History and hints cost real tokens.** Hints are cached per problem after the first fetch, and
  history/skills tracking is 100% local (a `history.json` file next to the app) — nothing is sent
  anywhere beyond the LLM calls you'd make anyway.
- **Theme and font-size changes need a restart.** Every color/font in the app is resolved once,
  at import time, from constants in `theme.py`; nothing re-reads them later. Reduced motion is the
  exception — it's checked live on every animation call, so that one toggle applies instantly.

## Project layout

| File | What it does |
|---|---|
| `gui.py` | Main application window and all tab wiring |
| `cli.py` | One-shot terminal alternative to the GUI |
| `analyzer.py` | LLM prompt orchestration (review, hints, refactor suggestions, transpilation) |
| `leetcode_api.py` | GraphQL client for problem metadata |
| `tracer.py` | `sys.settrace`-based execution tracer, shared by Trace/Race/Fuzz |
| `fuzzer.py` | Random input generation, boundary cases, determinism check, minimal-input shrinking |
| `regression.py` | Reruns every official example against a best-effort parsed expected output |
| `race.py` | Real timing/memory comparison between two solutions |
| `ast_lint.py` | Static anti-pattern detection |
| `constraints.py` | Constraint parsing + Big-O feasibility heuristics |
| `stencils.py` | Boilerplate code templates |
| `history.py` | Local JSON persistence for the Skills tab |
| `settings.py` | Local JSON persistence for theme/motion/font-scale/window/onboarding prefs |
| `api_keys.py` | Reads/writes provider API keys in `.env`, preserving comments and other lines |
| `theme.py` | Design tokens (3 palettes: dark/light/high-contrast), fonts, animation helpers |
| `code_editor.py` | Reusable syntax-highlighted code widget (also owns the breakpoint gutter) |
| `panel_trace.py` | Trace tab — scrubber, step controls, breakpoints, watches, call stack, mutation tracking |
| `panel_tests.py` | Tests tab — regression suite, boundary cases, determinism, shrinking |
| `panel_skills.py`, `panel_whiteboard.py` | The remaining two non-Editor/Report tabs |

# LuxCode

### *LeetCode Premium, on steroids*

A desktop app that fetches a LeetCode or Codeforces problem straight from the source, runs your
solution through an LLM code review, and then goes well past that: it actually **executes** your
code (line-by-line tracing, real timing, real memory) to back up what it tells you with facts
instead of just LLM narration. A full interactive debugger, a regression suite, spaced-repetition
practice tracking, a Netflix-style profile picker so more than one person can share an install, and
a code editor that doesn't feel like an afterthought: the LeetCode workflow Premium never gave you.
100% free, no subscription, nothing gated.

Built with CustomTkinter. Uses Gemini by default (`gemini-3.5-flash-lite`, picked specifically to
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

   Every launch starts with a "Who's coding?" picker: pick an existing profile, create a new one,
   or continue as a guest whose skill history never touches disk. The first time it launches with
   no key configured, it then asks you to pick a provider and paste an API key, no manual `.env`
   editing needed. Get a Gemini key (the cheapest option) at
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey); the modal links straight to
   whichever provider you pick. You can skip this and add a key later from **Settings (⚙) → API
   Keys**, which manages all three providers (Gemini/OpenAI/Anthropic) with masked entries and a
   configured/not-set indicator per key.

   Keys are written to a `.env` file next to the app (same mechanism `.env.example` describes, for
   anyone who'd rather hand-edit it directly) and take effect immediately, no restart needed.

   A CLI is also available for a single one-shot review without the UI (still reads the same
   `.env`):

   ```bash
   py cli.py -p 1 -f solution.py
   ```

## What it does

Pick a **Provider** (LeetCode or Codeforces), then a problem from the searchable list, paste your
solution, and it's analyzed against the official problem statement. Or switch the Provider to
**Playground** and skip picking a problem entirely: paste any code and the LLM infers what it does
on its own.

### Editor

- Line-numbered, syntax-highlighted code editor
- **Language selector**: submit in any of the 19 languages LeetCode itself supports. Trace, Tests,
  Fuzz, and the Performance Race stay Python-only since they execute the code for real, but Report
  analysis, Hints, and Refactor Selection all work in any language
- **AST anti-pattern HUD**: flags `x in list` inside loops, `range(len(x))`, string concatenation
  in loops, live as you type (pure static analysis via Python's `ast` module, no LLM call)
- **Constraint-to-complexity predictor**: parses the problem's stated bounds (e.g. `n <= 10^5`) and
  tells you which Big-O classes are actually fast enough
- **Code stencils**: one-click boilerplate for binary search, tries, union-find, BFS/DFS,
  monotonic stacks, 1D/2D DP
- **Blindfold mode**: toggles syntax highlighting off, for practicing raw recall
- **Socratic hints**: a 4-tier slider from a conceptual nudge to a near-solution, so you only see
  as much help as you ask for
- **Refactor Selection**: select any snippet, get 3 alternative implementations with one-click
  replace

### Trace

Runs your own solution, on your own machine, exactly like running `python solution.py` yourself,
just with a trace hook attached (`sys.settrace` + `tracemalloc`, no sandboxing) against an
auto-detected example input, then lets you scrub through it step by step:

- Timeline scrubber with play/pause, like a media player
- **Step controls**: step into/back one recorded event, step over a call without descending into
  it, step out until the current call returns, or continue straight to the next breakpoint
- **Breakpoints**: click a line number to set one; add an optional condition (e.g. `i > 3`),
  evaluated against that step's real local variables
- **Watch expressions**: any Python expression (`len(seen)`, `nums[i]`), re-evaluated live as you
  scrub, against a small safe set of builtins (no file/import/exec access)
- **Call stack inspector**: the real, live call stack at the current step, innermost frame first
- **Variable history & mutation tracking**: click a variable for its full changelog across the
  trace; container variables (list/dict/set) show a one-line diff of what changed since the
  previous step
- **Exception debugging**: jump straight to the step where an unhandled exception was raised, and
  optionally ask the LLM to explain why that specific input triggered it
- Variables panel (changed values highlighted)
- Recursion tree (real call tree, active path highlighted)
- DP grid visualizer (auto-detected 2D arrays, cells colored as they update)
- Memory sparkline (real `tracemalloc` data)

### Tests

One-click regression suite, run entirely against your own solution on your own machine:

- **Official Examples**: reruns *every* example from the problem statement (not just the first
  one the Trace tab uses), comparing against an expected output parsed best-effort from the
  problem's prose. Problems that explicitly allow multiple valid orderings ("in any order") are
  compared order-independently, so a correct `[1, 0]` isn't flagged wrong just because the
  reference text says `[0, 1]`
- **Determinism Check**: runs the same input 5 times and flags it if the output differs between
  runs (hidden reliance on set/dict iteration order, uninitialized state, etc.)
- **Boundary Cases**: a curated set of edge cases (empty, single-element, max-size, zero,
  negative, one parameter varied at a time) rather than random fuzzing, surfacing any that crash
- **Shrink to Minimal Failing Input**: on any crash (example or boundary), one click runs greedy
  delta-debugging to reduce the failing input down to the smallest one that still reproduces it

### Report

The core LLM review: time/space complexity (yours vs. optimal), a structure & clarity score, a
list of concrete redundancies, and a refactored solution, plus:

- **Performance Race**: runs your code and the refactored suggestion on a large synthetic input
  at the problem's own scale, timing both for real (not estimated). LeetCode only: needs a known
  function signature and problem-scale input to generate
- **Counter-Example Fuzzer**: generates random inputs matching the problem's parameter types and
  looks for ones that crash or time out your solution
- **Transpilation Inspector**: translates your solution to any other language LeetCode supports,
  with real low-level tradeoff commentary
- A perfect 10/10 structure and clarity score gets a small confetti celebration

### Skills

Local, private, per-profile history of what you've analyzed:

- **Warmup queue**: spaced repetition; problems you scored well on come back less often, ones you
  scored poorly on come back sooner
- **Skill map**: topic tags colored by your *average score* on that topic, not just how many
  you've solved
- **Profiles**: a Netflix-style "Who's coding?" picker at every launch, and a Switch Profile
  button right here in Skills. Each profile has its own separate history; Guest mode keeps
  everything in memory only, so nothing is written to disk

### Whiteboard

A freehand scratchpad, pen, eraser, shapes, text, undo/redo, for sketching structures before
touching the keyboard, plus a floating countdown timer that persists across every tab for
simulating interview pressure.

## Providers

- **LeetCode**: the full catalog, with example inputs, parameter types, and function signatures
  auto-parsed, which is what powers Trace/Tests/Fuzz/Race.
- **Codeforces**: real, working problem browsing and selection via Codeforces' own public API.
  Codeforces problems are stdin/stdout, not "implement this function," so there's no signature to
  auto-detect and Trace/Tests/Fuzz/Race don't apply. Codeforces also doesn't expose full problem
  statements through its public API, and the problem pages themselves sit behind a bot-check this
  app doesn't attempt to solve, so Report analysis and the problem viewer work from the name,
  rating, and tags rather than the full statement text.
- **Playground**: no problem at all. Paste any code and the LLM infers its purpose, then runs the
  same complexity/structure/redundancy review as normal analysis.

## Choosing a model

The model dropdown covers Gemini, OpenAI, and Anthropic. `gemini-3.5-flash-lite` is the default
and cheapest option (minimal-thinking mode, lowest token usage); the other models are there if
you want higher-quality analysis and don't mind the extra cost.

## Settings (⚙) and shortcuts

The gear icon next to the app name opens a small settings panel:

- **API Keys**: one row per provider (Gemini/OpenAI/Anthropic), each showing whether a key is
  configured, with a masked entry and a show/hide toggle. Saves immediately to `.env` and to the
  running process, no restart needed, unlike the theme/font settings below.
- **Theme**: Dark, Light, or High Contrast. Saving a theme change restarts the app automatically
  to apply it (window size/position are kept, but anything unsaved in the editor is not).
- **Font size**: an 80 to 140% scale applied to every font in the app. Also restarts to apply.
- **Reduced motion**: the one setting that *is* live: flips instantly, no restart needed, and
  makes every animation (card entrances, number roll-ups, gauges) jump straight to its end state.

The ✨ icon opens a short changelog, and the **?** icon opens a help modal covering every tab and
shortcut. Window position/size persist across launches automatically.

In the **Trace** tab: `Space` play/pauses the scrubber, `<-`/`->` step one recorded event,
`Shift+<-`/`Shift+->` step out/over, all inert while you're typing in a text field. In the
**Whiteboard** tab: `Ctrl+Z`/`Ctrl+Y` undo/redo.

Preferences live in a local `settings.json` next to the app, same pattern as `history.json`,
nothing sent anywhere.

## Building a standalone binary

```bash
./build.sh     # macOS/Linux
./build.ps1    # Windows
```

Produces `dist/leetcode-eval` (CLI) and `dist/leetcode-eval-gui` (windowed, no console). Put your
`.env` file next to the built executable, it's read from disk at runtime, not bundled in.

## Notes and honest limitations

- **LeetCode has no public API.** This uses the same unauthenticated GraphQL endpoint the
  website's frontend uses. It works today but could change without notice.
- **Codeforces' public API is metadata-only.** It returns problem name/rating/tags but never
  statement text, and the statement pages themselves are behind an active bot-check. This app
  doesn't attempt to solve that challenge, so the problem viewer and Report analysis work from
  metadata plus a link to the real page, not the full text.
- **Auto-detected example inputs are best-effort.** LeetCode has no per-problem test harness, so
  the Trace/Race/Fuzz features parse the problem's own example testcases and parameter types;
  unusual input shapes (custom classes like `TreeNode`/`ListNode`, multi-example ambiguity) may
  fail to parse. When that happens, the feature says so rather than guessing.
- **The Fuzzer finds crashes and timeouts, not "wrong answers."** There's no verified reference
  solution to diff against; the "optimal" solution shown in the Report is itself LLM-generated,
  not guaranteed correct, so fuzzing deliberately stays scoped to unambiguous failures.
- **The Transpilation Inspector is a translation, not a compiler.** The output has not been
  compiled or benchmarked; treat the code and its commentary as a reference, not verified fact.
- **History and hints cost real tokens.** Hints are cached per problem after the first fetch, and
  history/skills tracking is 100% local (a `history_<profile>.json` file next to the app, or
  nothing at all for Guest), nothing is sent anywhere beyond the LLM calls you'd make anyway.
- **Theme and font-size changes restart the app.** Every color/font in the app is resolved once,
  at import time, from constants in `theme.py`; nothing re-reads them later, so a change restarts
  the process to apply it (window geometry is preserved). Reduced motion is the exception: it's
  checked live on every animation call, so that one toggle applies instantly.

## Project layout

| File | What it does |
|---|---|
| `gui.py` | Main application window and all tab wiring |
| `cli.py` | One-shot terminal alternative to the GUI |
| `analyzer.py` | LLM prompt orchestration (review, playground analysis, hints, refactor suggestions, transpilation) |
| `leetcode_api.py` | GraphQL client for LeetCode problem metadata |
| `codeforces_api.py` | HTTP client for Codeforces problem metadata, same interface as `leetcode_api.py` |
| `tracer.py` | `sys.settrace`-based execution tracer, shared by Trace/Race/Fuzz |
| `fuzzer.py` | Random input generation, boundary cases, determinism check, minimal-input shrinking |
| `regression.py` | Reruns every official example against a best-effort parsed expected output |
| `race.py` | Real timing/memory comparison between two solutions |
| `ast_lint.py` | Static anti-pattern detection |
| `constraints.py` | Constraint parsing and Big-O feasibility heuristics |
| `stencils.py` | Boilerplate code templates |
| `history.py` | Local, profile-scoped JSON persistence for the Skills tab |
| `profiles.py` | Profile create/rename/delete, backing the "Who's coding?" picker |
| `settings.py` | Local JSON persistence for theme/motion/font-scale/window/onboarding prefs |
| `api_keys.py` | Reads/writes provider API keys in `.env`, preserving comments and other lines |
| `theme.py` | Design tokens (3 palettes: dark/light/high-contrast), fonts, animation helpers |
| `code_editor.py` | Reusable syntax-highlighted code widget (also owns the breakpoint gutter) |
| `floating_timer.py` | The countdown timer widget that persists across every tab |
| `panel_trace.py` | Trace tab: scrubber, step controls, breakpoints, watches, call stack, mutation tracking |
| `panel_tests.py` | Tests tab: regression suite, boundary cases, determinism, shrinking |
| `panel_skills.py` | Skills tab: warmup queue, skill map, profile switching |
| `panel_whiteboard.py` | Whiteboard tab: freehand drawing, shapes, undo/redo |

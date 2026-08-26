"""Typer CLI entrypoint: evaluates a LeetCode submission and renders a rich report."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from analyzer import AnalyzerError, ReviewResult, analyze_submission
from leetcode_api import LeetCodeAPIError, LeetCodeClient, ProblemMetadata

app = typer.Typer(
    add_completion=False,
    help="LuxCode CLI — evaluate a LeetCode submission's complexity, clarity, and redundancies.",
)
console = Console()

DEFAULT_MODEL = "gemini-3.5-flash-lite"


def _complexity_style(user_big_o: str, optimal_big_o: str) -> str:
    normalize = lambda s: s.replace(" ", "").lower()
    return "green" if normalize(user_big_o) == normalize(optimal_big_o) else "yellow"


def _load_code(file: Optional[Path], code: Optional[str]) -> str:
    if file and code:
        console.print("[red]Error:[/red] pass only one of --file or --code, not both.")
        raise typer.Exit(code=1)
    if file:
        if not file.exists():
            console.print(f"[red]Error:[/red] file not found: {file}")
            raise typer.Exit(code=1)
        return file.read_text(encoding="utf-8")
    if code:
        return code
    console.print("[red]Error:[/red] provide a submission via --file/-f or --code/-c.")
    raise typer.Exit(code=1)


def _render_report(problem: ProblemMetadata, result: ReviewResult) -> None:
    console.print(
        Panel(
            f"[bold]{problem.frontend_id}. {problem.title}[/bold]  "
            f"[dim]({problem.difficulty})[/dim]\n"
            f"Topics: {', '.join(problem.topic_tags) or 'n/a'}",
            title="LeetCode Problem",
        )
    )

    complexity_table = Table(title="Complexity Analysis", show_lines=True)
    complexity_table.add_column("Metric")
    complexity_table.add_column("Your Submission")
    complexity_table.add_column("Optimal")

    time_style = _complexity_style(
        result.user_time_complexity.big_o, result.optimal_time_complexity.big_o
    )
    space_style = _complexity_style(
        result.user_space_complexity.big_o, result.optimal_space_complexity.big_o
    )

    complexity_table.add_row(
        "Time",
        f"[{time_style}]{result.user_time_complexity.big_o}[/{time_style}]\n"
        f"[dim]{result.user_time_complexity.justification}[/dim]",
        f"{result.optimal_time_complexity.big_o}\n"
        f"[dim]{result.optimal_time_complexity.justification}[/dim]",
    )
    complexity_table.add_row(
        "Space",
        f"[{space_style}]{result.user_space_complexity.big_o}[/{space_style}]\n"
        f"[dim]{result.user_space_complexity.justification}[/dim]",
        f"{result.optimal_space_complexity.big_o}\n"
        f"[dim]{result.optimal_space_complexity.justification}[/dim]",
    )
    console.print(complexity_table)

    score = result.structure_and_clarity_score
    score_style = "green" if score >= 8 else "yellow" if score >= 5 else "red"
    console.print(
        Panel(
            f"[{score_style}]{score}/10[/{score_style}]\n{result.structure_and_clarity_commentary}",
            title="Structure & Clarity",
        )
    )

    if result.redundancies:
        redundancy_table = Table(title="Redundancies & Suboptimal Choices")
        redundancy_table.add_column("#", width=3)
        redundancy_table.add_column("Issue")
        for i, item in enumerate(result.redundancies, start=1):
            redundancy_table.add_row(str(i), item)
        console.print(redundancy_table)
    else:
        console.print(Panel("No redundancies detected.", style="green", title="Redundancies"))

    console.print(
        Panel(
            Syntax(result.refactored_code, "python", theme="monokai", line_numbers=True),
            title="Refactored Solution",
        )
    )


@app.command()
def evaluate(
    problem: str = typer.Option(
        ..., "--problem", "-p", help="LeetCode problem number or slug, e.g. 1 or two-sum."
    ),
    file: Optional[Path] = typer.Option(
        None, "--file", "-f", help="Path to the local Python solution file."
    ),
    code: Optional[str] = typer.Option(
        None, "--code", "-c", help="Inline Python submission string (alternative to --file)."
    ),
    model: str = typer.Option(
        DEFAULT_MODEL,
        "--model",
        help="LLM backend model, e.g. gemini-3.5-flash-lite, gpt-4o, or claude-3-5-sonnet-latest.",
    ),
) -> None:
    """Evaluate a LeetCode submission against the official problem and print a code review report."""
    submission = _load_code(file, code)

    with console.status(f"Fetching LeetCode problem '{problem}'..."):
        try:
            with LeetCodeClient() as client:
                metadata = client.get_problem(problem)
        except LeetCodeAPIError as exc:
            console.print(f"[red]Error fetching problem:[/red] {exc}")
            raise typer.Exit(code=1)

    with console.status(f"Analyzing submission with {model}..."):
        try:
            result = analyze_submission(metadata, submission, model)
        except AnalyzerError as exc:
            console.print(f"[red]Error during analysis:[/red] {exc}")
            raise typer.Exit(code=1)

    _render_report(metadata, result)


@app.command(hidden=True)
def zyad() -> None:
    """Easter egg #8 — not listed in --help, just a quiet credit."""
    console.print(Panel("This app was built by [bold]Zyad[/bold].", title="LuxCode", style="yellow"))


def main() -> None:
    app()


if __name__ == "__main__":
    main()

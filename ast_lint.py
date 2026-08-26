"""Static analysis over the user's own code (Python's built-in `ast` module,
no execution, no new dependencies) that flags common algorithmic traps —
membership tests on lists inside loops, range(len(x)) instead of enumerate,
string concatenation in loops, etc."""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass
class Finding:
    line: int
    message: str
    suggestion: str


def _is_list_like_name(name: str, list_names: set[str]) -> bool:
    return name in list_names


def lint(code: str) -> list[Finding]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    findings: list[Finding] = []

    # Collect names assigned from a list literal/comprehension anywhere in the
    # module — used as a (best-effort, static-only) signal for "this is a list".
    list_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.ListComp)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    list_names.add(target.id)

    loop_stack: list[ast.AST] = []

    class Visitor(ast.NodeVisitor):
        def visit_For(self, node: ast.For) -> None:
            loop_stack.append(node)
            self._check_range_len(node)
            self.generic_visit(node)
            loop_stack.pop()

        def visit_While(self, node: ast.While) -> None:
            loop_stack.append(node)
            self.generic_visit(node)
            loop_stack.pop()

        def visit_Compare(self, node: ast.Compare) -> None:
            if loop_stack and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
                for comparator in node.comparators:
                    if isinstance(comparator, ast.Name) and _is_list_like_name(comparator.id, list_names):
                        findings.append(Finding(
                            line=node.lineno,
                            message=f"`in {comparator.id}` inside a loop is an O(n) scan each time.",
                            suggestion=f"Convert {comparator.id} to a set for O(1) average-case lookups.",
                        ))
            self.generic_visit(node)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            if (
                loop_stack and isinstance(node.op, ast.Add) and isinstance(node.target, ast.Name)
            ):
                findings.append(Finding(
                    line=node.lineno,
                    message=f"`{node.target.id} += ...` inside a loop looks like string/list building.",
                    suggestion="If building a string, collect pieces in a list and ''.join(...) once after the loop.",
                ))
            self.generic_visit(node)

        def _check_range_len(self, node: ast.For) -> None:
            it = node.iter
            if (
                isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "range"
                and len(it.args) == 1 and isinstance(it.args[0], ast.Call)
                and isinstance(it.args[0].func, ast.Name) and it.args[0].func.id == "len"
            ):
                arg = it.args[0].args[0] if it.args[0].args else None
                name = arg.id if isinstance(arg, ast.Name) else "x"
                findings.append(Finding(
                    line=node.lineno,
                    message="`range(len(...))` is often clearer as a direct or enumerated loop.",
                    suggestion=f"Consider `for item in {name}:` or `for i, item in enumerate({name}):`.",
                ))

    Visitor().visit(tree)
    # De-dupe same (line, message) pairs and keep stable order.
    seen: set[tuple[int, str]] = set()
    unique: list[Finding] = []
    for f in sorted(findings, key=lambda f: f.line):
        key = (f.line, f.message)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique

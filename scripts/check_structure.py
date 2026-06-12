#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIRS = ("tuna_core", "tuna_blackbox", "tuna_fcs", "tuna_console")

# Keep the shortest agent path from regressing back into godfiles. These files
# should remain routing/orchestration entrypoints; feature behavior belongs in
# owned modules beside them.
LINE_BUDGETS = {
    Path("tuna_core/cli/main.py"): 80,
    Path("tuna_console/web/app.py"): 130,
    Path("tuna_blackbox/csv_summary.py"): 120,
    Path("tuna_fcs/fcs_bridge/blackbox_download.py"): 240,
}
DEFAULT_PACKAGE_LINE_BUDGET = 450

FORBIDDEN_IMPORTS = {
    "tuna_core": ("tuna_console", "tuna_fcs"),
    "tuna_blackbox": ("tuna_core", "tuna_console", "tuna_fcs"),
    "tuna_console": ("tuna_fcs",),
    "tuna_fcs": ("tuna_core", "tuna_console"),
}


def _package_for(path: Path) -> str | None:
    try:
        return path.relative_to(ROOT).parts[0]
    except ValueError:
        return None


def _import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def _check_line_budgets(path: Path, errors: list[str]) -> None:
    relative = path.relative_to(ROOT)
    line_count = len(path.read_text().splitlines())
    budget = LINE_BUDGETS.get(relative, DEFAULT_PACKAGE_LINE_BUDGET)
    if line_count > budget:
        errors.append(f"{relative}: {line_count} lines exceeds structural budget {budget}")


def _check_import_boundaries(path: Path, tree: ast.AST, errors: list[str]) -> None:
    package = _package_for(path)
    if package not in FORBIDDEN_IMPORTS:
        return
    forbidden = set(FORBIDDEN_IMPORTS[package])
    violations = sorted(_import_roots(tree) & forbidden)
    if violations:
        relative = path.relative_to(ROOT)
        errors.append(f"{relative}: forbidden package import(s): {', '.join(violations)}")


def main() -> int:
    errors: list[str] = []
    files = [path for package in PACKAGE_DIRS for path in (ROOT / package).rglob("*.py")]
    for path in sorted(files):
        relative = path.relative_to(ROOT)
        try:
            tree = ast.parse(path.read_text(), filename=str(relative))
        except SyntaxError as exc:
            errors.append(f"{relative}: syntax error: {exc}")
            continue
        _check_line_budgets(path, errors)
        _check_import_boundaries(path, tree, errors)

    if errors:
        print("Structural checks failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Structural checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

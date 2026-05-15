"""
Tools/i18n_coverage.py
Reports translation coverage progress per source file.

For each .py under src/, identifies:
  * "translated" strings — t("...") calls
  * "untranslated" strings — hardcoded English literals in widget args
    such as text="...", label="...", titles, and messagebox dialogs.

Heuristics: a literal is treated as a translation candidate when it
contains at least one ASCII letter and either starts with an uppercase
letter or contains a space; pure symbols (e.g., "◀", "✔", emojis only)
and pure digits/whitespace are skipped.

Usage:
    python Tools/i18n_coverage.py            # summary table
    python Tools/i18n_coverage.py --verbose  # list every untranslated literal
    python Tools/i18n_coverage.py --file src/ui/menu_bar.py   # one file
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

# Widget kwargs that carry user-visible text.
TEXT_KWARGS = {"text", "label"}
# Methods whose first positional argument is a window title.
TITLE_METHODS = {"title"}
# Messagebox functions: positional args 0 and 1 are user-visible.
MESSAGEBOX_FUNCS = {
    "showinfo",
    "showerror",
    "showwarning",
    "askyesno",
    "askokcancel",
    "askretrycancel",
    "askquestion",
}

ASCII_LETTER_RE = re.compile(r"[A-Za-z]")


@dataclass
class FileReport:
    path: Path
    translated: int = 0
    untranslated: list[tuple[int, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.translated + len(self.untranslated)

    @property
    def coverage_pct(self) -> float:
        return 0.0 if self.total == 0 else (self.translated / self.total) * 100


def is_likely_ui_text(s: str) -> bool:
    """Filter out pure symbols, digits, and short tokens."""
    if not s or len(s.strip()) < 2:
        return False
    if not ASCII_LETTER_RE.search(s):
        return False
    return True


def extract_string(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def analyze_file(path: Path) -> FileReport:
    report = FileReport(path=path.relative_to(REPO_ROOT))
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return report

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func

        # 1. t("literal") calls
        is_t = (
            (isinstance(func, ast.Name) and func.id == "t")
            or (isinstance(func, ast.Attribute) and func.attr == "t")
        )
        if is_t:
            if node.args and isinstance(node.args[0], ast.Constant):
                report.translated += 1
            continue

        # 2. Widget kwargs (text=, label=)
        for kw in node.keywords:
            if kw.arg in TEXT_KWARGS:
                s = extract_string(kw.value)
                if s and is_likely_ui_text(s):
                    report.untranslated.append((node.lineno, s))

        # 3. .title("literal") and notebook .add(..., text="...")
        if isinstance(func, ast.Attribute) and func.attr in TITLE_METHODS:
            if node.args:
                s = extract_string(node.args[0])
                if s and is_likely_ui_text(s):
                    report.untranslated.append((node.lineno, s))

        # 4. messagebox.<func>("title", "message", ...)
        if isinstance(func, ast.Attribute) and func.attr in MESSAGEBOX_FUNCS:
            for arg in node.args[:2]:
                s = extract_string(arg)
                if s and is_likely_ui_text(s):
                    report.untranslated.append((node.lineno, s))

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="List every untranslated literal with line number.",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Analyze only the given file (relative to repo root).",
    )
    args = parser.parse_args()

    if args.file:
        target = REPO_ROOT / args.file
        if not target.is_file():
            print(f"file not found: {target}", file=sys.stderr)
            return 1
        files = [target]
    else:
        files = sorted(SRC_DIR.rglob("*.py"))

    reports = [analyze_file(p) for p in files]
    reports = [r for r in reports if r.total > 0]

    total_translated = sum(r.translated for r in reports)
    total_untranslated = sum(len(r.untranslated) for r in reports)
    grand_total = total_translated + total_untranslated
    overall_pct = 0.0 if grand_total == 0 else (total_translated / grand_total) * 100

    # Sort by coverage ascending so the most-pending files surface first.
    reports.sort(key=lambda r: (r.coverage_pct, str(r.path)))

    print(f"{'COVERAGE':>8}  {'TRANS':>5}  {'TODO':>5}  FILE")
    print("-" * 70)
    for r in reports:
        bar_len = 20
        filled = int(round(r.coverage_pct / 100 * bar_len))
        bar = "█" * filled + "·" * (bar_len - filled)
        print(
            f"{r.coverage_pct:6.1f}%  {r.translated:>5}  "
            f"{len(r.untranslated):>5}  {r.path}  {bar}"
        )

        if args.verbose and r.untranslated:
            for lineno, text in r.untranslated:
                trimmed = text if len(text) <= 60 else text[:57] + "..."
                print(f"           L{lineno}: {trimmed!r}")

    print("-" * 70)
    print(
        f"TOTAL: {total_translated}/{grand_total} translated  "
        f"({overall_pct:.1f}%)  —  {total_untranslated} remaining"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

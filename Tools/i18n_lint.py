"""
Tools/i18n_lint.py
Verifies the integrity of the i18n catalogs and their relationship with
the source code. Exits non-zero on any error.

Checks performed:
  1. en.json + zh_CN.json are valid JSON
  2. Both catalogs share an identical key set
  3. Per-key placeholder names match between en and zh (so .format() never
     KeyErrors at runtime)
  4. No empty values
  5. Every t("...") call in src/ references an existing catalog key
     (a missing key would silently echo the literal key at runtime)
  6. Optional: warn on catalog keys that are not referenced anywhere in
     src/ (dead keys). Non-fatal during incremental rollout.

Usage:
    python Tools/i18n_lint.py           # full lint, exit non-zero on error
    python Tools/i18n_lint.py --strict  # also fail on dead-key warnings
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EN_PATH = REPO_ROOT / "src" / "locales" / "en.json"
ZH_PATH = REPO_ROOT / "src" / "locales" / "zh_CN.json"
SRC_DIR = REPO_ROOT / "src"

PLACEHOLDER_RE = re.compile(r"\{(\w+)(?::[^}]*)?\}")


def load_catalog(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(text or ""))


def collect_t_calls(src_dir: Path) -> dict[str, list[tuple[Path, int]]]:
    """Walks every .py under src_dir and returns {key: [(file, lineno), ...]}
    for every t("literal") call found.

    Only literal string keys are tracked; t(dynamic_var) calls are ignored
    on purpose because we cannot statically resolve them.
    """
    found: dict[str, list[tuple[Path, int]]] = {}
    for py_path in src_dir.rglob("*.py"):
        try:
            tree = ast.parse(py_path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_t = (
                (isinstance(func, ast.Name) and func.id == "t")
                or (isinstance(func, ast.Attribute) and func.attr == "t")
            )
            if not is_t:
                continue
            if not node.args:
                continue
            arg0 = node.args[0]
            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                found.setdefault(arg0.value, []).append(
                    (py_path.relative_to(REPO_ROOT), node.lineno)
                )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat dead-key warnings as errors.",
    )
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    # --- 1. JSON validity ---
    try:
        en = load_catalog(EN_PATH)
    except Exception as exc:
        print(f"FATAL: failed to load {EN_PATH}: {exc}", file=sys.stderr)
        return 1
    try:
        zh = load_catalog(ZH_PATH)
    except Exception as exc:
        print(f"FATAL: failed to load {ZH_PATH}: {exc}", file=sys.stderr)
        return 1

    # --- 2. Key parity ---
    en_keys = set(en.keys())
    zh_keys = set(zh.keys())
    missing_in_zh = en_keys - zh_keys
    missing_in_en = zh_keys - en_keys
    for k in sorted(missing_in_zh):
        errors.append(f"key in en.json but missing from zh_CN.json: {k}")
    for k in sorted(missing_in_en):
        errors.append(f"key in zh_CN.json but missing from en.json: {k}")

    # --- 3. Placeholder parity ---
    for k in sorted(en_keys & zh_keys):
        ph_en = placeholders(en[k])
        ph_zh = placeholders(zh[k])
        if ph_en != ph_zh:
            errors.append(
                f"placeholder mismatch [{k}]: "
                f"en={sorted(ph_en) or '∅'} zh={sorted(ph_zh) or '∅'}"
            )

    # --- 4. Empty values ---
    for k, v in en.items():
        if v == "":
            errors.append(f"empty en value for key '{k}'")
    for k, v in zh.items():
        if v == "":
            errors.append(f"empty zh value for key '{k}'")

    # --- 5/6. Source code key references ---
    used = collect_t_calls(SRC_DIR)
    catalog_keys = en_keys | zh_keys

    for key, locations in sorted(used.items()):
        if key not in catalog_keys:
            for path, lineno in locations:
                errors.append(
                    f"unknown i18n key '{key}' referenced at {path}:{lineno}"
                )

    dead = sorted(catalog_keys - set(used.keys()))
    if dead:
        warnings.append(
            f"{len(dead)} catalog keys are not yet referenced via t(...). "
            f"This is expected during incremental rollout; only worry once "
            f"Phase D is complete."
        )
        if args.strict:
            for k in dead:
                errors.append(f"dead key (not used in code): {k}")

    # --- Reporting ---
    print(f"i18n_lint: en.json={len(en)} zh_CN.json={len(zh)} "
          f"referenced={len(used)} unreferenced={len(dead)}")
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)

    if errors:
        print(f"\ni18n_lint FAILED ({len(errors)} errors).", file=sys.stderr)
        return 2
    print("i18n_lint OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

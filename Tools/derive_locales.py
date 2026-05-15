"""
tools/derive_locales.py
Generates the production locale catalogs (src/locales/en.json and
src/locales/zh_CN.json) by flattening docs/translation_review_zh_CN.json.

Behavior:
- Walks the nested review JSON.
- For every leaf object with both 'en' and 'zh' keys, emits a flattened
  dotted key (e.g. "menu.file.preferences") pointing to the corresponding
  string value.
- Skips any key whose name begins with '_' (reserved for _meta and
  _do_not_translate reference data).
- Skips entries with status == "do_not_translate" (these are kept English
  in code by other means).
- Verifies placeholder consistency between en and zh; aborts on mismatch.

Run:
    python tools/derive_locales.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REVIEW_FILE = REPO_ROOT / "docs" / "translation_review_zh_CN.json"
OUT_DIR = REPO_ROOT / "src" / "locales"
PLACEHOLDER_RE = re.compile(r"\{(\w+)(?::[^}]*)?\}")


def is_leaf(node: dict) -> bool:
    return isinstance(node, dict) and "en" in node and "zh" in node


def extract_placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(text or ""))


def walk(node, path: list[str], en_out: dict, zh_out: dict, errors: list[str]):
    if not isinstance(node, dict):
        return
    for key, val in node.items():
        if key.startswith("_"):
            continue
        if is_leaf(val):
            if val.get("status") == "do_not_translate":
                continue
            dotted = ".".join(path + [key])
            en = val.get("en", "")
            zh = val.get("zh", "")
            ph_en = extract_placeholders(en)
            ph_zh = extract_placeholders(zh)
            if ph_en != ph_zh:
                errors.append(
                    f"{dotted}: placeholder mismatch en={sorted(ph_en)} zh={sorted(ph_zh)}"
                )
            en_out[dotted] = en
            zh_out[dotted] = zh
        elif isinstance(val, dict):
            walk(val, path + [key], en_out, zh_out, errors)


def main() -> int:
    if not REVIEW_FILE.exists():
        print(f"ERROR: review file not found at {REVIEW_FILE}", file=sys.stderr)
        return 1

    with REVIEW_FILE.open("r", encoding="utf-8") as f:
        review = json.load(f)

    en_out: dict[str, str] = {}
    zh_out: dict[str, str] = {}
    errors: list[str] = []

    walk(review, [], en_out, zh_out, errors)

    if errors:
        print("PLACEHOLDER ERRORS (refusing to write):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    en_path = OUT_DIR / "en.json"
    zh_path = OUT_DIR / "zh_CN.json"
    with en_path.open("w", encoding="utf-8") as f:
        json.dump(en_out, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    with zh_path.open("w", encoding="utf-8") as f:
        json.dump(zh_out, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")

    print(f"Wrote {en_path} ({len(en_out)} entries)")
    print(f"Wrote {zh_path} ({len(zh_out)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

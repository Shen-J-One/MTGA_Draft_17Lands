"""
src/i18n.py
Lightweight localization loader for the MTGA Draft Tool.

Design:
- Catalogs live as flat key->string JSON files under src/locales/.
- load(lang) populates an in-memory dict from the bundled catalog and
  optionally overlays a user-side override file at
  <BASE_DIR>/locale_overrides/<lang>.json. Override entries replace
  bundled entries on a per-key basis.
- t(key, **kwargs) returns the translated string; if the key is missing
  it returns the key itself so the UI never crashes during partial
  rollout. .format(**kwargs) is applied when kwargs are supplied.

The module is safe to import before load() is called: t() will simply
echo the key back until a catalog is loaded.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from src.constants import BASE_DIR, RESOURCE_DIR

logger = logging.getLogger(__name__)

DEFAULT_LANG = "zh_CN"
FALLBACK_LANG = "en"
SUPPORTED_LANGS = ("zh_CN", "en")

# Display labels shown in the language dropdown.
LANGUAGE_DISPLAY = {
    "zh_CN": "简体中文",
    "en": "English",
}

_CATALOG: dict[str, str] = {}
_CURRENT_LANG: str = DEFAULT_LANG


def _bundled_catalog_path(lang: str) -> str:
    return os.path.join(RESOURCE_DIR, "src", "locales", f"{lang}.json")


def _override_catalog_path(lang: str) -> str:
    return os.path.join(BASE_DIR, "locale_overrides", f"{lang}.json")


def _read_json(path: str) -> dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning(f"i18n: {path} is not a flat dict; ignoring.")
            return {}
        return {k: str(v) for k, v in data.items()}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning(f"i18n: failed to load {path}: {exc}")
        return {}


def load(lang: Optional[str] = None) -> str:
    """Loads the bundled catalog for `lang` and applies any user overrides.

    Returns the language code that was actually loaded.
    """
    global _CATALOG, _CURRENT_LANG

    requested = lang or DEFAULT_LANG
    if requested not in SUPPORTED_LANGS:
        logger.warning(f"i18n: unsupported language '{requested}', falling back to {DEFAULT_LANG}.")
        requested = DEFAULT_LANG

    base = _read_json(_bundled_catalog_path(requested))
    if not base and requested != FALLBACK_LANG:
        logger.warning(
            f"i18n: bundled catalog for '{requested}' is empty/missing; "
            f"falling back to '{FALLBACK_LANG}'."
        )
        base = _read_json(_bundled_catalog_path(FALLBACK_LANG))
        requested = FALLBACK_LANG

    overrides = _read_json(_override_catalog_path(requested))
    if overrides:
        logger.info(f"i18n: applying {len(overrides)} override entries for '{requested}'.")
        base.update(overrides)

    _CATALOG = base
    _CURRENT_LANG = requested
    return requested


def current_language() -> str:
    return _CURRENT_LANG


def t(key: str, **kwargs) -> str:
    """Looks up `key` in the active catalog and formats with kwargs.

    Missing keys return the key itself to keep the UI alive during
    incremental rollout. Formatting failures fall back to the raw
    template.
    """
    template = _CATALOG.get(key, key)
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError) as exc:
        logger.debug(f"i18n: format failed for key '{key}' ({exc}); returning raw template.")
        return template


def has(key: str) -> bool:
    """True when the active catalog has an entry for `key`."""
    return key in _CATALOG


def entry_count() -> int:
    return len(_CATALOG)

"""
src/chinese_names.py
Fetch + cache the English->Chinese MTG card-name mapping used by the UI
overlay when the active language is zh_CN.

Design notes:
- Pure stdlib (urllib.request, threading, json) so we add no new
  dependencies and the module is safe to import even with no network.
- The dataset is a JSON array of 5-tuples
  ``[english_name, chinese_name, image_url, scryfall_id, oracle_id]``;
  only indices 0 and 1 are consumed here. Malformed rows are skipped.
- Disk cache is refreshed at most once every ``STALENESS_SECONDS`` (24h)
  via a conditional ``If-None-Match`` GET. A network failure is logged
  as a warning and the on-disk cache (even if stale) is used as-is.
- All public functions are non-raising at the UI level. ``display_name``
  silently returns its English argument whenever any precondition
  (language gate, cache loaded, mapping present) is not met.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
from typing import Optional
from urllib.request import Request, urlopen

from src import constants
from src.i18n import current_language

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public constants (overridable in tests via monkeypatch)
# ---------------------------------------------------------------------------

URL = "https://mtgch.com/static/card_names.json"
CACHE_DIR = os.path.join(constants.TEMP_FOLDER, "RawCache")
CACHE_FILE = os.path.join(CACHE_DIR, "card_names_zh_CN.json")
ETAG_FILE = os.path.join(CACHE_DIR, "card_names_zh_CN.etag")
STALENESS_SECONDS = 24 * 3600
USER_AGENT = (
    f"MTGA_Draft_Tool/{constants.APPLICATION_VERSION} "
    "(+https://github.com/Shen-J-One/MTGA_Draft_17Lands)"
)
NETWORK_TIMEOUT_SECONDS = 30

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_MAP: dict[str, str] = {}
_LOADED: bool = False
_LOAD_THREAD: Optional[threading.Thread] = None
_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_loaded() -> bool:
    return _LOADED


def entry_count() -> int:
    return len(_MAP)


def display_name(english_name: str) -> str:
    """Return the Chinese display name for an English card name, or the
    English name unchanged when any precondition is not met. Never raises.
    """
    try:
        if not _LOADED:
            return english_name
        if current_language() != "zh_CN":
            return english_name
        return _MAP.get(english_name, english_name)
    except Exception as exc:  # defence in depth: never crash the UI
        logger.debug(f"chinese_names: display_name fallback: {exc}")
        return english_name


def start_background_load() -> None:
    """Kick off a daemon thread that runs ``_load_sync`` in the
    background. Idempotent: returns immediately if a load is in flight
    or has already completed."""
    global _LOAD_THREAD
    with _LOCK:
        if _LOADED:
            return
        if _LOAD_THREAD is not None and _LOAD_THREAD.is_alive():
            return
        thread = threading.Thread(
            target=_load_sync,
            name="chinese_names-loader",
            daemon=True,
        )
        _LOAD_THREAD = thread
    thread.start()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _load_sync() -> None:
    """Refresh the cache (if stale) and load it into memory.

    Network failures are absorbed: on any exception the function falls
    through to whatever is already on disk. If nothing is on disk the
    map stays empty and ``is_loaded`` remains False so the UI keeps
    rendering English names.
    """
    try:
        _ensure_cache_dir()
        if not _disk_cache_is_fresh():
            _refresh_from_network()

        if not os.path.exists(CACHE_FILE):
            logger.info(
                "chinese_names: no cache on disk after refresh attempt; "
                "Chinese overlay will be disabled this session."
            )
            return

        _load_from_disk()
    except Exception as exc:  # never let the loader crash the caller
        logger.warning(f"chinese_names: unexpected error during load: {exc}")


def _ensure_cache_dir() -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
    except OSError as exc:
        logger.warning(f"chinese_names: failed to create {CACHE_DIR}: {exc}")


def _disk_cache_is_fresh() -> bool:
    if not os.path.exists(CACHE_FILE):
        return False
    try:
        age = time.time() - os.path.getmtime(CACHE_FILE)
    except OSError:
        return False
    return age < STALENESS_SECONDS


def _read_etag() -> Optional[str]:
    if not os.path.exists(ETAG_FILE):
        return None
    try:
        with open(ETAG_FILE, "r", encoding="utf-8") as f:
            value = f.read().strip()
        return value or None
    except OSError as exc:
        logger.debug(f"chinese_names: could not read ETag: {exc}")
        return None


def _refresh_from_network() -> None:
    """Issue a conditional GET. On 200 rewrite cache + ETag. On 304 bump
    mtime so the next call short-circuits. Other failures are logged
    and silently swallowed so the disk fallback path can run."""
    etag = _read_etag()
    req = Request(URL, headers={"User-Agent": USER_AGENT})
    if etag:
        req.add_header("If-None-Match", etag)

    try:
        resp = urlopen(req, timeout=NETWORK_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            logger.debug("chinese_names: HTTP 304, cache still fresh.")
            try:
                os.utime(CACHE_FILE, None)
            except OSError as utime_exc:
                logger.debug(
                    f"chinese_names: could not bump cache mtime: {utime_exc}"
                )
            return
        logger.warning(
            f"chinese_names: HTTP {exc.code} while refreshing cache: {exc}"
        )
        return
    except urllib.error.URLError as exc:
        logger.warning(f"chinese_names: network error: {exc}")
        return
    except Exception as exc:  # ssl/socket/etc.
        logger.warning(f"chinese_names: unexpected network error: {exc}")
        return

    try:
        payload = resp.read()
    except Exception as exc:
        logger.warning(f"chinese_names: failed to read response body: {exc}")
        return

    try:
        with open(CACHE_FILE, "wb") as f:
            f.write(payload)
    except OSError as exc:
        logger.warning(
            f"chinese_names: failed to write cache {CACHE_FILE}: {exc}"
        )
        return

    new_etag = None
    try:
        new_etag = resp.headers.get("ETag")
    except Exception:
        new_etag = None

    if new_etag:
        try:
            with open(ETAG_FILE, "w", encoding="utf-8") as f:
                f.write(new_etag)
        except OSError as exc:
            logger.debug(f"chinese_names: failed to write ETag: {exc}")


def _load_from_disk() -> None:
    """Parse CACHE_FILE into ``_MAP`` and mark the module as loaded."""
    global _LOADED
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"chinese_names: failed to parse cache: {exc}")
        return

    if not isinstance(data, list):
        logger.warning("chinese_names: cache root is not a list; ignoring.")
        return

    mapping: dict[str, str] = {}
    for entry in data:
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        english, chinese = entry[0], entry[1]
        if not isinstance(english, str) or not isinstance(chinese, str):
            continue
        if not english or not chinese:
            continue
        mapping[english] = chinese

    with _LOCK:
        _MAP.clear()
        _MAP.update(mapping)
        _LOADED = True

    logger.info(f"chinese_names: loaded {len(_MAP)} entries from disk.")


# ---------------------------------------------------------------------------
# Test-only helper (kept in module so tests can reset shared state)
# ---------------------------------------------------------------------------


def _reset_for_tests() -> None:
    """Clear all module-level state. Test-only — do not call from app code."""
    global _LOADED, _LOAD_THREAD
    with _LOCK:
        _MAP.clear()
        _LOADED = False
        _LOAD_THREAD = None

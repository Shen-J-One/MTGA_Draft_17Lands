"""
tests/test_chinese_names.py

TDD tests for the src.chinese_names module. The module fetches a public
JSON dataset of English->Chinese MTG card-name mappings, caches it on
disk with ETag conditional refresh, and exposes display_name() for the
UI layer.

The tests monkeypatch the module-level CACHE_DIR/CACHE_FILE/ETAG_FILE
constants to point inside tmp_path per test, and an autouse fixture
calls _reset_for_tests() to wipe module state between tests.
"""
from __future__ import annotations

import io
import json
import os
import time
import urllib.error

import pytest

from src import chinese_names


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_chinese_names(tmp_path, monkeypatch):
    """Redirect cache paths into tmp_path and reset module state per test."""
    cache_dir = tmp_path / "RawCache"
    cache_file = cache_dir / "card_names_zh_CN.json"
    etag_file = cache_dir / "card_names_zh_CN.etag"

    monkeypatch.setattr(chinese_names, "CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(chinese_names, "CACHE_FILE", str(cache_file))
    monkeypatch.setattr(chinese_names, "ETAG_FILE", str(etag_file))

    chinese_names._reset_for_tests()
    yield
    chinese_names._reset_for_tests()


def _seed_cache(entries):
    """Write the given list of [en, zh, ...] entries to CACHE_FILE."""
    os.makedirs(chinese_names.CACHE_DIR, exist_ok=True)
    with open(chinese_names.CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False)


def _seed_etag(value):
    os.makedirs(chinese_names.CACHE_DIR, exist_ok=True)
    with open(chinese_names.ETAG_FILE, "w", encoding="utf-8") as f:
        f.write(value)


def _make_stale(seconds_ago):
    """Backdate CACHE_FILE's mtime so it is past the staleness window."""
    past = time.time() - seconds_ago
    os.utime(chinese_names.CACHE_FILE, (past, past))


def _block_network(monkeypatch):
    """Make any urlopen call fail the test loudly."""

    def _boom(*args, **kwargs):
        raise AssertionError("network should not be touched in this test")

    monkeypatch.setattr(chinese_names, "urlopen", _boom)


def _force_zh(monkeypatch):
    monkeypatch.setattr(chinese_names, "current_language", lambda: "zh_CN")


def _force_en(monkeypatch):
    monkeypatch.setattr(chinese_names, "current_language", lambda: "en")


# ---------------------------------------------------------------------------
# 1. display_name returns English when nothing is loaded
# ---------------------------------------------------------------------------


def test_display_name_returns_english_when_not_loaded():
    assert chinese_names.is_loaded() is False
    assert chinese_names.entry_count() == 0
    assert chinese_names.display_name("Bulk Up") == "Bulk Up"


# ---------------------------------------------------------------------------
# 2. Fresh cache on disk => no network call
# ---------------------------------------------------------------------------


def test_load_from_fresh_cache_no_network(monkeypatch):
    _seed_cache(
        [
            ["Bulk Up", "力量突长", "", "", ""],
            ["Lightning Bolt", "闪电击", "", "", ""],
        ]
    )
    _force_zh(monkeypatch)
    _block_network(monkeypatch)

    chinese_names._load_sync()

    assert chinese_names.is_loaded() is True
    assert chinese_names.entry_count() == 2
    assert chinese_names.display_name("Bulk Up") == "力量突长"
    assert chinese_names.display_name("Lightning Bolt") == "闪电击"
    # Unknown card falls back to English.
    assert chinese_names.display_name("Nonexistent Card") == "Nonexistent Card"


# ---------------------------------------------------------------------------
# 3. Language gate: when not zh_CN, display_name returns English
# ---------------------------------------------------------------------------


def test_display_name_returns_english_when_language_not_zh_cn(monkeypatch):
    _seed_cache([["Bulk Up", "力量突长", "", "", ""]])
    _force_en(monkeypatch)
    _block_network(monkeypatch)

    chinese_names._load_sync()

    assert chinese_names.is_loaded() is True
    assert chinese_names.display_name("Bulk Up") == "Bulk Up"


# ---------------------------------------------------------------------------
# 4. HTTP 304 keeps the existing cache and bumps mtime
# ---------------------------------------------------------------------------


def test_http_304_uses_existing_cache(monkeypatch):
    _seed_cache([["Bulk Up", "力量突长", "", "", ""]])
    _seed_etag('"abc123"')
    _make_stale(chinese_names.STALENESS_SECONDS + 60)
    _force_zh(monkeypatch)

    captured_requests = []

    def fake_urlopen(req, timeout=None):
        captured_requests.append(req)
        raise urllib.error.HTTPError(
            chinese_names.URL, 304, "Not Modified", {}, None
        )

    monkeypatch.setattr(chinese_names, "urlopen", fake_urlopen)

    chinese_names._load_sync()

    # The conditional GET must have been issued with the saved ETag.
    assert len(captured_requests) == 1
    sent = captured_requests[0]
    assert sent.get_header("If-none-match") == '"abc123"'

    # Cache still loaded, and mtime was refreshed to "now".
    assert chinese_names.is_loaded() is True
    assert chinese_names.display_name("Bulk Up") == "力量突长"
    assert time.time() - os.path.getmtime(chinese_names.CACHE_FILE) < 5


# ---------------------------------------------------------------------------
# 5. Network failure falls back to whatever is on disk, even if stale
# ---------------------------------------------------------------------------


def test_network_failure_falls_back_to_stale_cache(monkeypatch):
    _seed_cache([["Bulk Up", "力量突长", "", "", ""]])
    _make_stale(chinese_names.STALENESS_SECONDS + 3600)
    _force_zh(monkeypatch)

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(chinese_names, "urlopen", fake_urlopen)

    chinese_names._load_sync()

    assert chinese_names.is_loaded() is True
    assert chinese_names.display_name("Bulk Up") == "力量突长"


# ---------------------------------------------------------------------------
# 6. First-time fetch writes the cache file and the ETag file
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload_bytes, headers):
        self._payload = payload_bytes
        self.headers = headers

    def read(self):
        return self._payload


def test_first_time_fetch_writes_cache_and_etag(monkeypatch):
    _force_zh(monkeypatch)

    payload = json.dumps([["Bulk Up", "力量突长", "", "", ""]]).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        return _FakeResponse(payload, {"ETag": '"new-etag"'})

    monkeypatch.setattr(chinese_names, "urlopen", fake_urlopen)

    chinese_names._load_sync()

    assert chinese_names.is_loaded() is True
    assert chinese_names.display_name("Bulk Up") == "力量突长"
    assert os.path.exists(chinese_names.CACHE_FILE)

    with open(chinese_names.ETAG_FILE, "r", encoding="utf-8") as f:
        assert f.read() == '"new-etag"'


# ---------------------------------------------------------------------------
# 7. start_background_load() is idempotent and non-blocking
# ---------------------------------------------------------------------------


def test_start_background_load_is_idempotent(monkeypatch):
    _seed_cache([["Bulk Up", "力量突长", "", "", ""]])
    _force_zh(monkeypatch)
    _block_network(monkeypatch)

    chinese_names.start_background_load()

    # Poll up to 2.5s for the load to complete.
    for _ in range(50):
        if chinese_names.is_loaded():
            break
        time.sleep(0.05)

    assert chinese_names.is_loaded() is True

    # Second call must be a no-op and never raise.
    chinese_names.start_background_load()
    assert chinese_names.is_loaded() is True
    assert chinese_names.display_name("Bulk Up") == "力量突长"

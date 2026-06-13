"""Tests for AudioCache: clip ids, URL resolution, pruning, ffmpeg warning."""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path

from homeassistant.core import HomeAssistant

from custom_components.haikubox.audio_cache import AudioCache
from custom_components.haikubox.const import CACHE_URL_BASE

SERIAL = "100000003d7c9f2b"
_MARKER = "ffmpeg is unavailable"


def _fresh_dir(directory: Path) -> Path:
    # The test config dir persists across tests/runs — start each prune test
    # from a clean cache directory.
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write_clip(directory: Path, name: str, age_days: float = 0) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.flac"
    path.write_bytes(b"clip")
    if age_days:
        old = time.time() - age_days * 86400
        os.utime(path, (old, old))
    return path


async def test_async_init_warns_when_ffmpeg_missing(
    hass: HomeAssistant, caplog
) -> None:
    cache = AudioCache(hass, None, SERIAL, ffmpeg_bin=None)
    with caplog.at_level(logging.WARNING):
        await cache.async_init()
    assert _MARKER in caplog.text


async def test_async_init_silent_when_ffmpeg_present(
    hass: HomeAssistant, caplog
) -> None:
    cache = AudioCache(hass, None, SERIAL, ffmpeg_bin="/usr/bin/ffmpeg")
    with caplog.at_level(logging.WARNING):
        await cache.async_init()
    assert _MARKER not in caplog.text


def test_clip_id_is_stable_across_signed_urls() -> None:
    base = "https://s3.amazonaws.com/box/clip.flac"
    a = AudioCache.clip_id(f"{base}?sig=AAA&exp=1")
    b = AudioCache.clip_id(f"{base}?sig=BBB&exp=2")
    # Keyed on the object path, not the (rotating) query/signature.
    assert a == b
    assert len(a) == 16


def test_clip_id_none_for_missing_url() -> None:
    assert AudioCache.clip_id(None) is None
    assert AudioCache.clip_id("") is None


def test_url_for_only_when_cached(hass: HomeAssistant) -> None:
    cache = AudioCache(hass, None, SERIAL)
    wav = "https://s3.amazonaws.com/box/clip.flac?sig=x"
    assert cache.url_for(wav) is None  # not cached yet
    cid = AudioCache.clip_id(wav)
    cache._cached.add(cid)
    assert cache.url_for(wav) == f"{CACHE_URL_BASE}/audio/{SERIAL}/{cid}.flac"


async def test_prune_drops_clips_older_than_window(hass: HomeAssistant) -> None:
    # Distinct serial per prune test: the cache dir is keyed by serial, and the
    # test config dir can persist files between tests.
    cache = AudioCache(hass, None, "aaaaaaaaaaaaaaa1")
    _fresh_dir(cache._dir)
    _write_clip(cache._dir, "fresh", age_days=1)
    _write_clip(cache._dir, "stale", age_days=40)

    await cache.async_prune(max_age_days=30, max_clips=100)

    remaining = {p.stem for p in cache._dir.glob("*.flac")}
    assert remaining == {"fresh"}


async def test_prune_trims_to_clip_cap_oldest_first(hass: HomeAssistant) -> None:
    cache = AudioCache(hass, None, "aaaaaaaaaaaaaaa2")
    _fresh_dir(cache._dir)
    # all within the age window, but more than the cap; ages give a clear order
    for i in range(5):
        _write_clip(cache._dir, f"clip{i}", age_days=i)  # clip0 newest … clip4 oldest

    await cache.async_prune(max_age_days=365, max_clips=3)

    remaining = {p.stem for p in cache._dir.glob("*.flac")}
    assert remaining == {"clip0", "clip1", "clip2"}  # the 3 newest survive
